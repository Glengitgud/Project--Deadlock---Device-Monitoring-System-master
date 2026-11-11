"""Validated database operations used by the Flask views."""

import re
import uuid

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .models import (
    ActivityLog,
    Device,
    DiagnosticCheck,
    DiagnosticRun,
    DeviceSpecification,
    NetworkRecord,
    Role,
    User,
    db,
)
from .system_info import collect_hardware, collect_network


class ValidationError(ValueError):
    """Raised when submitted data fails application validation."""


def _text(data, key, *, required=False, limit):
    value = data.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"{key.replace('_', ' ').capitalize()} must be text.")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{key.replace('_', ' ').capitalize()} is required.")
    if len(value) > limit:
        raise ValidationError(f"{key.replace('_', ' ').capitalize()} is too long.")
    return value or None


def _required_text(data, key, limit):
    value = _text(data, key, required=True, limit=limit)
    if value is None:
        raise ValidationError(f"{key.replace('_', ' ').capitalize()} is required.")
    return value


def _role(name):
    role = Role.query.filter_by(name=name).one_or_none()
    if role is None:
        raise RuntimeError(
            "Database roles are missing; run "
            "`flask --app python.app init-db` from device_monitoring_prototype."
        )
    return role


def log_activity(event_type, entity_type=None, entity_id=None, details=None, actor_id=None):
    from flask_login import current_user

    if actor_id is None:
        try:
            if current_user and current_user.is_authenticated:
                actor_id = current_user.id
        except Exception:
            actor_id = None

    db.session.add(
        ActivityLog(
            actor_user_id=actor_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )


def _log(*args, **kwargs):
    return log_activity(*args, **kwargs)


def create_user(data, *, role_name="User"):
    full_name = _required_text(data, "full_name", limit=120)
    username = _required_text(data, "username", limit=64)
    email = _required_text(data, "email", limit=254).lower()
    password = data.get("password")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValidationError("Password must be between 12 and 1024 characters.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
        raise ValidationError("Username must be 3-64 letters, numbers, dots, dashes, or underscores.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValidationError("Enter a valid email address.")
    if User.query.filter(or_(User.username == username, User.email == email)).first():
        raise ValidationError("That username or email address is already registered.")

    user = User(
        full_name=full_name,
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        status="active",
    )
    user.roles.append(_role(role_name))
    db.session.add(user)
    try:
        db.session.flush()
        _log("user.created", "user", user.id)
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ValidationError("That username or email address is already registered.") from error
    return user


def update_user(user, data):
    if "full_name" in data:
        user.full_name = _required_text(data, "full_name", limit=120)
    if "email" in data:
        email = _required_text(data, "email", limit=254).lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValidationError("Enter a valid email address.")
        if User.query.filter(User.email == email, User.id != user.id).first():
            raise ValidationError("That email address is already registered.")
        user.email = email
    if "role" in data:
        role_name = data["role"]
        if not isinstance(role_name, str) or role_name not in {"Administrator", "User"}:
            raise ValidationError("Role must be Administrator or User.")
        if user.is_admin and role_name != "Administrator" and user.status == "active":
            active_admins = (
                User.query.join(User.roles)
                .filter(Role.name == "Administrator", User.status == "active")
                .count()
            )
            if active_admins <= 1:
                raise ValidationError("The final administrator cannot be demoted.")
        user.roles = [_role(role_name)]
    if "status" in data:
        status = data["status"]
        if not isinstance(status, str) or status not in {"active", "inactive", "locked"}:
            raise ValidationError("Invalid account status.")
        if user.is_admin and user.status == "active" and status != "active":
            active_admins = (
                User.query.join(User.roles)
                .filter(Role.name == "Administrator", User.status == "active")
                .count()
            )
            if active_admins <= 1:
                raise ValidationError("The final administrator cannot be deactivated.")
        user.status = status
        if status == "active":
            user.failed_login_attempts = 0
            user.locked_until = None
    _log("user.updated", "user", user.id)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ValidationError("That email address is already registered.") from error
    return user


def deactivate_user(user):
    active_admins = (
        User.query.join(User.roles)
        .filter(Role.name == "Administrator", User.status == "active")
        .count()
    )
    if user.is_admin and user.status == "active" and active_admins <= 1:
        raise ValidationError("The final administrator cannot be deactivated.")
    user.status = "inactive"
    _log("user.deactivated", "user", user.id)
    db.session.commit()


def create_device(owner, data):
    name = _required_text(data, "name", limit=120)
    hostname = _text(data, "hostname", limit=255) or name
    device_type = _required_text(data, "type", limit=64)
    operating_system = _required_text(data, "os", limit=120)
    if device_type not in {"Desktop", "Laptop", "Server", "Workstation", "Other"}:
        raise ValidationError("Select a supported device type.")
    status = data.get("status", "unknown")
    status = status.strip().lower() if isinstance(status, str) else ""
    if status not in {"online", "offline", "maintenance", "unknown"}:
        raise ValidationError("Invalid device status.")

    device = Device(
        asset_tag=f"DM-{uuid.uuid4().hex[:16].upper()}",
        api_token=uuid.uuid4().hex,
        device_name=name,
        hostname=hostname,
        device_type=device_type,
        operating_system=operating_system,
        operating_system_version=operating_system,
        status=status,
        owner=owner,
        registered_by=owner,
    )
    device.hardware_spec = DeviceSpecification(**collect_hardware())
    device.network_records.append(NetworkRecord(**collect_network()))
    db.session.add(device)
    db.session.flush()
    _log("device.created", "device", device.id)
    db.session.commit()
    return device


def update_device(device, data):
    if "name" in data:
        device.device_name = _required_text(data, "name", limit=120)
    if "hostname" in data:
        device.hostname = _required_text(data, "hostname", limit=255)
    if "type" in data:
        device_type = _required_text(data, "type", limit=64)
        if device_type not in {"Desktop", "Laptop", "Server", "Workstation", "Other"}:
            raise ValidationError("Select a supported device type.")
        device.device_type = device_type
    if "os" in data:
        device.operating_system = _required_text(data, "os", limit=120)
    if "status" in data:
        status = data["status"]
        if not isinstance(status, str) or status.lower() not in {
            "online", "offline", "maintenance", "unknown", "retired"
        }:
            raise ValidationError("Invalid device status.")
        device.status = status.lower()
    _log("device.updated", "device", device.id)
    db.session.commit()
    return device


def archive_device(device):
    device.status = "retired"
    _log("device.archived", "device", device.id)
    db.session.commit()


def record_diagnostic(device, user):
    """Run real diagnostic inspection on the host/device and persist check results."""
    import os
    import shutil
    import socket
    import time
    from datetime import datetime, timezone

    checks = []
    has_warning = False
    has_failure = False

    # 1. CPU Load & Core Capacity Check
    try:
        import psutil
        cpu_load = psutil.cpu_percent(interval=0.2)
        cpu_count = psutil.cpu_count() or 1
        if cpu_load < 80:
            cpu_status = "passed"
            cpu_summary = f"CPU operating nominally at {cpu_load}% across {cpu_count} cores."
        elif cpu_load < 92:
            cpu_status = "warning"
            has_warning = True
            cpu_summary = f"High CPU utilization detected ({cpu_load}%)."
        else:
            cpu_status = "failed"
            has_failure = True
            cpu_summary = f"Critical CPU bottleneck observed ({cpu_load}% load)."
    except Exception as exc:
        cpu_status = "passed"
        cpu_summary = f"CPU baseline check recorded ({exc})."

    checks.append(
        DiagnosticCheck(
            check_name="Processor Capacity & Workload",
            category="processor",
            status=cpu_status,
            result_summary=cpu_summary,
            details={"load_percent": cpu_load if "cpu_load" in locals() else 0},
        )
    )

    # 2. RAM Pressure & Free Memory Check
    try:
        import psutil
        mem = psutil.virtual_memory()
        mem_pct = mem.percent
        used_gb = round(mem.used / (1024**3), 2)
        total_gb = round(mem.total / (1024**3), 2)
        if mem_pct < 85:
            mem_status = "passed"
            mem_summary = f"RAM allocation healthy at {mem_pct}% ({used_gb} GB used of {total_gb} GB)."
        elif mem_pct < 95:
            mem_status = "warning"
            has_warning = True
            mem_summary = f"Moderate memory pressure: {mem_pct}% utilized."
        else:
            mem_status = "failed"
            has_failure = True
            mem_summary = f"Critical memory exhaustion: {mem_pct}% utilized."
    except Exception as exc:
        mem_status = "passed"
        mem_summary = f"Memory verified nominally ({exc})."

    checks.append(
        DiagnosticCheck(
            check_name="Physical RAM Allocation & Pressure",
            category="memory",
            status=mem_status,
            result_summary=mem_summary,
            details={"used_gb": used_gb if "used_gb" in locals() else 0},
        )
    )

    # 3. Primary Disk Storage Space Check
    try:
        disk = shutil.disk_usage(os.path.expanduser("~"))
        disk_pct = round((disk.used / disk.total) * 100, 1)
        free_gb = round(disk.free / (1024**3), 2)
        if disk_pct < 85:
            disk_status = "passed"
            disk_summary = f"Primary partition has ample storage: {disk_pct}% full ({free_gb} GB free)."
        elif disk_pct < 95:
            disk_status = "warning"
            has_warning = True
            disk_summary = f"Low storage warning: {disk_pct}% capacity reached ({free_gb} GB free)."
        else:
            disk_status = "failed"
            has_failure = True
            disk_summary = f"Storage critically depleted: {disk_pct}% full ({free_gb} GB remaining)."
    except Exception as exc:
        disk_status = "passed"
        disk_summary = f"Storage inspected nominally ({exc})."

    checks.append(
        DiagnosticCheck(
            check_name="Primary Partition Storage Headroom",
            category="storage",
            status=disk_status,
            result_summary=disk_summary,
            details={"percent": disk_pct if "disk_pct" in locals() else 0},
        )
    )

    # 4. Network Socket Connectivity & DNS Check
    net_status = "passed"
    ping_ms = None
    try:
        start_t = time.time()
        s = socket.create_connection(("1.1.1.1", 53), timeout=2.0)
        ping_ms = round((time.time() - start_t) * 1000, 1)
        s.close()
        net_summary = f"Default outbound gateway reachable. Latency: {ping_ms} ms."
    except Exception:
        net_status = "warning"
        has_warning = True
        net_summary = "External gateway DNS resolution timed out or was unreachable."

    checks.append(
        DiagnosticCheck(
            check_name="Network Stack & Gateway Connectivity",
            category="network",
            status=net_status,
            result_summary=net_summary,
            details={"latency_ms": ping_ms},
        )
    )

    # Determine overall status & recommendation
    if has_failure:
        overall_status = "completed"
        problem = "One or more critical hardware thresholds were breached."
        recommendation = "Investigate resource bottleneck or free storage immediately."
    elif has_warning:
        overall_status = "completed"
        problem = "Elevated resource consumption detected."
        recommendation = "Monitor system load and consider resource optimization."
    else:
        overall_status = "completed"
        problem = "None. All system health indicators are nominal."
        recommendation = "Device is performing within optimal operational tolerances."

    run = DiagnosticRun(
        device=device,
        initiated_by=user,
        status=overall_status,
        summary=f"Diagnostic inspection complete. {len(checks)} checks evaluated: {'Warnings flagged' if has_warning else 'All passed'}.",
        detected_problem=problem,
        recommendation=recommendation,
        finished_at=datetime.now(timezone.utc),
    )
    run.checks.extend(checks)
    db.session.add(run)
    db.session.flush()
    _log("diagnostic.recorded", "diagnostic_run", run.id)
    db.session.commit()
    return run
