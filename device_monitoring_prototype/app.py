"""Flask application with database-backed accounts and device inventory."""

import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit
#
import click
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from dotenv import load_dotenv
from sqlalchemy import String, cast, func, or_
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from device_monitoring_prototype.models import (
    ActivityLog,
    Device,
    Log,
    NetworkRecord,
    Permission,
    Role,
    User,
    db,
)
from device_monitoring_prototype.services import (
    DatabaseSetupError,
    ValidationError,
    archive_device,
    create_device,
    create_user,
    deactivate_user,
    record_diagnostic,
    update_device,
    update_user,
)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "warning"


def _database_uri():
    """Build the MySQL connection string from environment settings."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    # XAMPP's local MySQL defaults are root, localhost, and port 3306.
    user = quote_plus(os.environ.get("MYSQL_USER", "root"))
    password = quote_plus(os.environ.get("MYSQL_PASSWORD", ""))
    host = os.environ.get("MYSQL_HOST", "localhost")
    port = os.environ.get("MYSQL_PORT", "3306")
    database = quote_plus(os.environ.get("MYSQL_DATABASE", "devmonitor"))
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


def create_app(test_config=None):
    project_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=project_dir / ".env")
    app = Flask(
        __name__,
        template_folder=str(project_dir / "templates"),
        static_folder=str(project_dir / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=_database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "").lower() == "true",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "").lower() == "true",
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not os.environ.get("SECRET_KEY") and not app.testing:
        app.logger.warning("SECRET_KEY is unset; configure a persistent random secret in production.")

    # Connect the shared SQLAlchemy extension after the app has loaded its settings.
    db.init_app(app)
    login_manager.init_app(app)

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error):
        db.session.rollback()
        app.logger.error("Database request failed (%s).", type(error).__name__)
        message = (
            "The database is unavailable. Check the MySQL settings in "
            "device_monitoring_prototype\\.env and run the database setup commands."
        )
        if request.path.startswith("/api/"):
            return jsonify(error=message), 503
        return render_template("service_unavailable.html", message=message), 503

    @app.errorhandler(403)
    def handle_forbidden(error):
        message = "Administrator access is required for this action."
        if request.path.startswith("/api/"):
            return jsonify(error=message), 403
        return render_template("access_denied.html", message=message), 403

    @login_manager.unauthorized_handler
    def handle_unauthorized():
        if request.path.startswith("/api/"):
            return jsonify(error="Authentication required."), 401
        return redirect(url_for("login", next=request.url))

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.before_request
    def validate_csrf():
        if current_user.is_authenticated and not current_user.is_active:
            logout_user()
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify(error="This account is inactive."), 401
            return redirect(url_for("login"))
        if request.method == "POST":
            submitted = request.headers.get("X-CSRF-Token")
            if not submitted:
                submitted = request.form.get("csrf_token")
            if not submitted or not secrets.compare_digest(
                submitted, session.get("_csrf_token", "")
            ):
                if request.path.startswith("/api/"):
                    return jsonify(error="Invalid or missing CSRF token."), 400
                abort(400, description="Invalid or missing CSRF token.")

    @app.context_processor
    def inject_template_values():
        def csrf_token():
            token = session.get("_csrf_token")
            if token is None:
                token = secrets.token_urlsafe(32)
                session["_csrf_token"] = token
            return token

        return {"csrf_token": csrf_token}

    def admin_required(view):
        from functools import wraps

        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_admin:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    def api_data():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError("Request body must be a JSON object.")
        return data

    def api_error(error, status=400):
        return jsonify(error=str(error)), status

    def can_manage_device(device):
        if device.status == "retired":
            abort(404)
        if not current_user.is_admin and device.owner_user_id != current_user.id:
            abort(404)

    def serialize_device(device):
        spec = device.hardware_spec
        return {
            "id": device.id,
            "name": device.device_name,
            "hostname": device.hostname,
            "owner": device.owner.full_name,
            "owner_id": device.owner_user_id,
            "type": device.device_type,
            "os": device.operating_system or "",
            "cpu": spec.cpu_model if spec and spec.cpu_model else "—",
            "ram": (
                f"{spec.memory_bytes // (1024 ** 3)} GB"
                if spec and spec.memory_bytes
                else "—"
            ),
            "storage": (
                f"{spec.storage_bytes // (1024 ** 3)} GB"
                if spec and spec.storage_bytes
                else "—"
            ),
            "status": device.status.capitalize(),
            "registered": device.registered_at.isoformat() if device.registered_at else "",
            "lastUpdated": (
                device.last_seen_at.isoformat()
                if device.last_seen_at
                else device.updated_at.isoformat()
                if device.updated_at
                else ""
            ),
        }

    def serialize_user(user):
        return {
            "id": user.id,
            "fullName": user.full_name or "",
            "username": user.username,
            "email": user.email,
            "role": user.role_name,
            "status": user.status.capitalize(),
        }

    @app.route("/", methods=["GET", "POST"])
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated and request.method == "GET":
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter(func.lower(User.username) == username.lower()).first()
            if (
                not user
                or not user.is_active
                or not check_password_hash(user.password_hash, password)
            ):
                db.session.add(
                    ActivityLog(
                        actor_user_id=user.id if user else None,
                        event_type="auth.login_failed",
                        entity_type="user" if user else None,
                        entity_id=user.id if user else None,
                        details={"username": username},
                    )
                )
                db.session.commit()
                flash("Invalid username or password.", "danger")
                return render_template("login.html"), 401
            next_url = request.form.get("next", "") or request.args.get("next", "")
            if next_url:
                target = urlsplit(urljoin(request.host_url, next_url))
                if target.scheme not in {"http", "https"} or target.netloc != request.host:
                    next_url = ""
            session.clear()
            login_user(user, remember=False, fresh=True)
            user.last_login_at = datetime.now(timezone.utc)
            db.session.add(
                ActivityLog(
                    actor_user_id=user.id,
                    event_type="auth.login_succeeded",
                    entity_type="user",
                    entity_id=user.id,
                    details={"username": user.username},
                )
            )
            db.session.commit()
            return redirect(next_url or url_for("dashboard"))
        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated and request.method == "GET":
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            try:
                create_user(request.form, role_name="User")
            except ValidationError as error:
                flash(str(error), "danger")
                return render_template("register.html"), 400
            except DatabaseSetupError as error:
                app.logger.error("Account registration blocked: %s", error)
                return render_template(
                    "service_unavailable.html",
                    message=str(error),
                ), 503
            flash("Account created. You can now sign in.", "success")
            return redirect(url_for("login"))
        return render_template("register.html")

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        session.clear()
        flash("You have been signed out.", "info")
        return redirect(url_for("login"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", active_page="dashboard")

    @app.get("/devices")
    @login_required
    def devices():
        return render_template("devices.html", active_page="devices")

    @app.get("/admin")
    @admin_required
    def admin():
        return render_template("admin.html", active_page="admin")

    @app.get("/api/devices")
    @login_required
    def list_devices():
        query = Device.query.filter(Device.status != "retired")
        if not current_user.is_admin:
            query = query.filter_by(owner_user_id=current_user.id)
        return jsonify([serialize_device(device) for device in query.order_by(Device.id.desc()).all()])

    @app.post("/api/devices")
    @login_required
    def add_device():
        try:
            device = create_device(current_user, api_data())
        except ValidationError as error:
            return api_error(error)
        return jsonify(serialize_device(device)), 201

    @app.patch("/api/devices/<int:device_id>")
    @login_required
    def edit_device(device_id):
        device = db.get_or_404(Device, device_id)
        can_manage_device(device)
        try:
            update_device(device, api_data())
        except ValidationError as error:
            return api_error(error)
        return jsonify(serialize_device(device))

    @app.get("/api/devices/<int:device_id>")
    @login_required
    def device_details(device_id):
        device = db.get_or_404(Device, device_id)
        can_manage_device(device)
        diagnostic_ids = [run.id for run in device.diagnostic_runs]
        activity_query = ActivityLog.query.filter(
            or_(
                (ActivityLog.entity_type == "device")
                & (ActivityLog.entity_id == device.id),
                (ActivityLog.entity_type == "diagnostic_run")
                & (ActivityLog.entity_id.in_(diagnostic_ids or [-1])),
            )
        )
        return jsonify(
            id=device.id,
            asset_tag=device.asset_tag,
            device_name=device.device_name,
            hostname=device.hostname,
            device_type=device.device_type,
            serial_number=device.serial_number,
            manufacturer=device.manufacturer,
            model=device.model,
            operating_system=device.operating_system,
            operating_system_version=device.operating_system_version,
            status=device.status,
            owner_user_id=device.owner_user_id,
            registered_by_user_id=device.registered_by_user_id,
            owner={
                "id": device.owner.id,
                "username": device.owner.username,
                "full_name": device.owner.full_name,
                "email": device.owner.email,
            },
            registered_by={
                "id": device.registered_by.id,
                "username": device.registered_by.username,
                "full_name": device.registered_by.full_name,
                "email": device.registered_by.email,
            } if device.registered_by else None,
            registered_at=device.registered_at.isoformat() if device.registered_at else None,
            updated_at=device.updated_at.isoformat() if device.updated_at else None,
            last_seen_at=device.last_seen_at.isoformat() if device.last_seen_at else None,
            specification={
                "device_id": device.hardware_spec.device_id,
                "cpu_model": device.hardware_spec.cpu_model,
                "cpu_cores": device.hardware_spec.cpu_cores,
                "cpu_threads": device.hardware_spec.cpu_threads,
                "memory_bytes": device.hardware_spec.memory_bytes,
                "storage_bytes": device.hardware_spec.storage_bytes,
                "gpu_model": device.hardware_spec.gpu_model,
                "bios_version": device.hardware_spec.bios_version,
                "motherboard_model": device.hardware_spec.motherboard_model,
                "operating_system_version": device.hardware_spec.operating_system_version,
                "collected_at": (
                    device.hardware_spec.collected_at.isoformat()
                    if device.hardware_spec.collected_at else None
                ),
            } if device.hardware_spec else None,
            network_records=[
                {
                    "id": record.id,
                    "device_id": record.device_id,
                    "ip_address": record.ip_address,
                    "subnet_mask": record.subnet_mask,
                    "default_gateway": record.default_gateway,
                    "dns_server": record.dns_server,
                    "connectivity_status": record.connectivity_status,
                    "recorded_at": record.recorded_at.isoformat(),
                }
                for record in sorted(
                    device.network_records,
                    key=lambda item: item.recorded_at,
                    reverse=True,
                )
            ],
            network_interfaces=[
                {
                    "id": interface.id,
                    "device_id": interface.device_id,
                    "interface_name": interface.interface_name,
                    "mac_address": interface.mac_address,
                    "interface_type": interface.interface_type,
                    "is_primary": interface.is_primary,
                    "created_at": interface.created_at.isoformat(),
                    "observations": [
                        {
                            "id": observation.id,
                            "interface_id": observation.interface_id,
                            "ip_address": observation.ip_address,
                            "subnet_prefix": observation.subnet_prefix,
                            "gateway": observation.gateway,
                            "dns_servers": observation.dns_servers,
                            "ssid": observation.ssid,
                            "connection_type": observation.connection_type,
                            "observed_at": observation.observed_at.isoformat(),
                        }
                        for observation in sorted(
                            interface.observations,
                            key=lambda item: item.observed_at,
                            reverse=True,
                        )
                    ],
                }
                for interface in device.network_interfaces
            ],
            diagnostics=[
                {
                    "id": run.id,
                    "device_id": run.device_id,
                    "initiated_by_user_id": run.initiated_by_user_id,
                    "initiated_by": {
                        "username": run.initiated_by.username,
                        "full_name": run.initiated_by.full_name,
                    } if run.initiated_by else None,
                    "status": run.status,
                    "summary": run.summary,
                    "detected_problem": run.detected_problem,
                    "recommendation": run.recommendation,
                    "started_at": run.started_at.isoformat(),
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "checks": [
                        {
                            "id": check.id,
                            "run_id": check.run_id,
                            "check_name": check.check_name,
                            "category": check.category,
                            "status": check.status,
                            "result_summary": check.result_summary,
                            "details": check.details,
                            "measured_at": check.measured_at.isoformat(),
                        }
                        for check in run.checks
                    ],
                }
                for run in sorted(
                    device.diagnostic_runs,
                    key=lambda item: item.started_at,
                    reverse=True,
                )
            ],
            metrics=[
                {
                    "id": metric.id,
                    "device_id": metric.device_id,
                    "cpu_percent": metric.cpu_percent,
                    "memory_percent": metric.memory_percent,
                    "storage_percent": metric.storage_percent,
                    "memory_used_bytes": metric.memory_used_bytes,
                    "storage_used_bytes": metric.storage_used_bytes,
                    "network_rx_bytes": metric.network_rx_bytes,
                    "network_tx_bytes": metric.network_tx_bytes,
                    "collected_at": metric.collected_at.isoformat(),
                }
                for metric in sorted(
                    device.metric_samples,
                    key=lambda item: item.collected_at,
                    reverse=True,
                )
            ],
            logs=[
                {
                    "id": entry.id,
                    "device_id": entry.device_id,
                    "event": entry.event,
                    "timestamp": entry.timestamp.isoformat(),
                }
                for entry in sorted(
                    device.logs,
                    key=lambda item: item.timestamp,
                    reverse=True,
                )
            ],
            activity_logs=[
                {
                    "event": entry.event_type,
                    "actor_user_id": entry.actor_user_id,
                    "entity_type": entry.entity_type,
                    "entity_id": entry.entity_id,
                    "actor": entry.actor.full_name or entry.actor.username
                    if entry.actor else "System",
                    "details": entry.details,
                    "id": entry.id,
                    "occurred_at": entry.occurred_at.isoformat(),
                }
                for entry in activity_query.order_by(ActivityLog.occurred_at.desc())
            ],
        )

    @app.delete("/api/devices/<int:device_id>")
    @login_required
    def delete_device(device_id):
        device = db.get_or_404(Device, device_id)
        can_manage_device(device)
        archive_device(device)
        return "", 204

    @app.post("/api/devices/<int:device_id>/diagnostics")
    @login_required
    def scan_device(device_id):
        device = db.get_or_404(Device, device_id)
        can_manage_device(device)
        run = record_diagnostic(device, current_user)
        return jsonify(
            id=run.id,
            status=run.status,
            result=run.summary,
            detected_problem=run.detected_problem,
            recommendation=run.recommendation,
            scanned_at=run.started_at.isoformat(),
        ), 201

    @app.get("/api/devices/<int:device_id>/history")
    @login_required
    def device_history(device_id):
        device = db.get_or_404(Device, device_id)
        can_manage_device(device)
        return jsonify(
            diagnostics=[
                {
                    "id": run.id,
                    "status": run.status,
                    "result": run.summary,
                    "problem": run.detected_problem,
                    "recommendation": run.recommendation,
                    "scanned_at": run.started_at.isoformat(),
                }
                for run in sorted(device.diagnostic_runs, key=lambda item: item.started_at, reverse=True)
            ],
            network=[
                {
                    "ip_address": record.ip_address,
                    "subnet_mask": record.subnet_mask,
                    "default_gateway": record.default_gateway,
                    "dns_server": record.dns_server,
                    "connectivity_status": record.connectivity_status,
                    "recorded_at": record.recorded_at.isoformat(),
                }
                for record in sorted(device.network_records, key=lambda item: item.recorded_at, reverse=True)
            ],
            logs=[
                {
                    "id": entry.id,
                    "event": entry.event,
                    "timestamp": entry.timestamp.isoformat(),
                }
                for entry in sorted(
                    device.logs, key=lambda item: item.timestamp, reverse=True
                )
            ],
        )

    @app.get("/api/users")
    @admin_required
    def list_users():
        users = User.query.order_by(User.id.asc()).all()
        return jsonify([serialize_user(user) for user in users])

    @app.post("/api/users")
    @admin_required
    def add_user():
        try:
            data = api_data()
            role_name = data.get("role", "User")
            if not isinstance(role_name, str) or role_name not in {"Administrator", "User"}:
                return api_error("Role must be Administrator or User.")
            user = create_user(data, role_name=role_name)
        except ValidationError as error:
            return api_error(error)
        return jsonify(serialize_user(user)), 201

    @app.patch("/api/users/<int:user_id>")
    @admin_required
    def edit_user(user_id):
        user = db.get_or_404(User, user_id)
        try:
            data = api_data()
        except ValidationError as error:
            return api_error(error)
        if user.id == current_user.id and (
            data.get("status", "active") != "active"
            or data.get("role", "Administrator") != "Administrator"
        ):
            return api_error("You cannot deactivate or demote your own account.")
        try:
            update_user(user, data)
        except ValidationError as error:
            db.session.rollback()
            return api_error(error)
        return jsonify(serialize_user(user))

    @app.delete("/api/users/<int:user_id>")
    @admin_required
    def delete_user(user_id):
        user = db.get_or_404(User, user_id)
        if user.id == current_user.id:
            return api_error("You cannot deactivate your own account.")
        try:
            deactivate_user(user)
        except ValidationError as error:
            db.session.rollback()
            return api_error(error)
        return "", 204

    @app.get("/api/dashboard")
    @login_required
    def dashboard_data():
        query = Device.query.filter(Device.status != "retired")
        if not current_user.is_admin:
            query = query.filter_by(owner_user_id=current_user.id)
        devices = query.order_by(Device.id.desc()).all()
        return jsonify(
            devices=[serialize_device(device) for device in devices],
            total=len(devices),
            online=sum(device.status == "online" for device in devices),
            offline=sum(device.status == "offline" for device in devices),
        )

    @app.cli.command("init-db")
    def init_db_command():
        """Create missing model tables and seed standard RBAC roles/permissions."""
        # Existing tables are not altered; upgrade the original XAMPP schema
        # with migrations/003_upgrade_xampp_prototype.sql before this command.
        db.create_all()
        role_definitions = {
            "Administrator": "Full administrative access",
            "User": "Standard device owner access",
        }
        roles = {}
        for name, description in role_definitions.items():
            role = Role.query.filter_by(name=name).one_or_none()
            if role is None:
                role = Role(name=name, description=description)
                db.session.add(role)
            roles[name] = role
        permissions = {
            "devices.read": "View authorized devices",
            "devices.write": "Register and update authorized devices",
            "users.manage": "Manage user accounts",
            "diagnostics.read": "View diagnostic history",
            "diagnostics.write": "Record diagnostic results",
        }
        permission_rows = {}
        for code, description in permissions.items():
            permission = Permission.query.filter_by(code=code).one_or_none()
            if permission is None:
                permission = Permission(code=code, description=description)
                db.session.add(permission)
            permission_rows[code] = permission
        db.session.flush()
        roles["Administrator"].permissions = list(permission_rows.values())
        roles["User"].permissions = [
            permission_rows["devices.read"],
            permission_rows["devices.write"],
            permission_rows["diagnostics.read"],
            permission_rows["diagnostics.write"],
        ]
        db.session.commit()

        default_admin = User.query.filter(func.lower(User.username) == "admin").one_or_none()
        if default_admin is None:
            if User.query.filter(func.lower(User.email) == "admin@localhost").first():
                raise click.ClickException(
                    "Cannot create the default admin account because admin@localhost is already in use."
                )
            default_admin = User(
                username="admin",
                email="admin@localhost",
                full_name="Administrator",
                password_hash=generate_password_hash(
                    os.environ.get("ADMIN_INITIAL_PASSWORD", "admin123")
                ),
                status="active",
            )
            default_admin.roles.append(roles["Administrator"])
            db.session.add(default_admin)
            db.session.flush()
            db.session.add(
                ActivityLog(
                    actor_user_id=None,
                    event_type="auth.admin_bootstrapped",
                    entity_type="user",
                    entity_id=default_admin.id,
                    details={"username": default_admin.username},
                )
            )
            db.session.commit()
            click.echo("Created the default Administrator account.")
        elif not default_admin.is_admin:
            raise click.ClickException(
                "The username 'admin' already belongs to a non-administrator account. "
                "Resolve that account before initializing the default Administrator."
            )
        else:
            click.echo("The Administrator account already exists; it was not changed.")
        click.echo("Database tables and default RBAC roles are ready.")

    @app.cli.command("seed-sample-data")
    @click.option("--username", default="sample_user", show_default=True)
    def seed_sample_data_command(username):
        """Create a test user, device, network record, and device log."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
            raise click.ClickException(
                "Username must be 3-64 letters, numbers, dots, dashes, or underscores."
            )
        if User.query.filter_by(username=username).first():
            raise click.ClickException(f"User {username!r} already exists.")

        role = Role.query.filter_by(name="User").one_or_none()
        if role is None:
            raise click.ClickException(
                "Run `flask --app device_monitoring_prototype.app init-db` first."
            )

        password = click.prompt(
            "Sample account password (minimum 12 characters)",
            hide_input=True,
            confirmation_prompt=True,
        )
        if len(password) < 12:
            raise click.ClickException("Password must contain at least 12 characters.")

        user = User(
            username=username,
            email=f"{username}@example.test",
            full_name="Sample User",
            password_hash=generate_password_hash(password),
            status="active",
        )
        user.roles.append(role)
        device = Device(
            asset_tag=f"DM-{uuid.uuid4().hex[:16].upper()}",
            device_name="Sample Laptop",
            hostname="sample-laptop",
            device_type="Laptop",
            operating_system="Windows 11",
            operating_system_version="Windows 11",
            status="online",
            owner=user,
            registered_by=user,
        )
        device.network_records.append(
            NetworkRecord(
                ip_address="192.0.2.10",
                subnet_mask="255.255.255.0",
                connectivity_status="connected",
            )
        )
        device.logs.append(Log(event="Sample device registered for testing"))
        db.session.add(user)
        db.session.commit()
        click.echo(
            f"Created sample user {username!r} and a linked device with a log entry."
        )

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--full-name", prompt="Full name")
    def create_admin_command(username, email, full_name):
        """Create an administrator account without exposing a password in shell history."""
        username = username.strip()
        email = email.strip().lower()
        full_name = full_name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
            raise click.ClickException("Username must be 3-64 letters, numbers, dots, dashes, or underscores.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise click.ClickException("Enter a valid email address.")
        if not full_name or len(full_name) > 120:
            raise click.ClickException("Full name is required and must be at most 120 characters.")
        if User.query.filter(
            (func.lower(User.username) == username.lower())
            | (func.lower(User.email) == email.lower())
        ).first():
            raise click.ClickException("That username or email address already exists.")
        role = Role.query.filter_by(name="Administrator").one_or_none()
        if role is None:
            raise click.ClickException(
                "Run `flask --app device_monitoring_prototype.app init-db` from the repository root."
            )
        password = click.prompt("Password (minimum 12 characters)", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("Password must contain at least 12 characters.")
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=generate_password_hash(password),
            status="active",
        )
        user.roles.append(role)
        db.session.add(user)
        db.session.commit()
        click.echo("Administrator account created.")

    @app.get("/api/admin/logs")
    @admin_required
    def admin_logs():
        kind = request.args.get("kind", "all")
        query_text = request.args.get("q", "").strip()
        if kind not in {"all", "activity", "device"}:
            return api_error("Log kind must be all, activity, or device.")
        if len(query_text) > 100:
            return api_error("Log search text must be 100 characters or fewer.")

        pattern = f"%{query_text}%"
        results = []
        if kind in {"all", "activity"}:
            activity_query = ActivityLog.query.outerjoin(
                User, ActivityLog.actor_user_id == User.id
            )
            if query_text:
                activity_query = activity_query.filter(
                    or_(
                        ActivityLog.event_type.ilike(pattern),
                        ActivityLog.entity_type.ilike(pattern),
                        User.username.ilike(pattern),
                        User.display_name.ilike(pattern),
                        cast(ActivityLog.details, String).ilike(pattern),
                    )
                )
            results.extend(
                {
                    "id": entry.id,
                    "kind": "activity",
                    "event": entry.event_type,
                    "entity": entry.entity_type,
                    "entity_id": entry.entity_id,
                    "actor": entry.actor.full_name or entry.actor.username
                    if entry.actor else "System",
                    "details": entry.details,
                    "timestamp": entry.occurred_at.isoformat(),
                }
                for entry in activity_query.order_by(
                    ActivityLog.occurred_at.desc()
                ).limit(200)
            )

        if kind in {"all", "device"}:
            device_query = Log.query.join(Device, Log.device_id == Device.id)
            if query_text:
                device_query = device_query.filter(
                    or_(
                        Log.event.ilike(pattern),
                        Device.device_name.ilike(pattern),
                        cast(Log.device_id, String).ilike(pattern),
                    )
                )
            results.extend(
                {
                    "id": entry.id,
                    "kind": "device",
                    "event": entry.event,
                    "entity": "device",
                    "entity_id": entry.device_id,
                    "actor": "—",
                    "details": {"device_name": entry.device.device_name},
                    "timestamp": entry.timestamp.isoformat(),
                }
                for entry in device_query.order_by(Log.timestamp.desc()).limit(200)
            )

        results.sort(key=lambda entry: entry["timestamp"], reverse=True)
        return jsonify(results[:200])

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "").lower() == "true", port=5000)
