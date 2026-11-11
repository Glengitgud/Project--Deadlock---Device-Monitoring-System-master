"""Flask application with database-backed accounts and device inventory."""

import json
import os
import queue
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit

import click
from flask import (
    Flask,
    Response,
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
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from .models import (
    ActivityLog,
    Alert,
    Device,
    DeviceMetric,
    DeviceSpecification,
    DiagnosticCheck,
    DiagnosticRun,
    NetworkRecord,
    Permission,
    Role,
    User,
    db,
)
from .security import (
    generate_reset_token,
    generate_totp_secret,
    get_totp_uri,
    rate_limit,
    verify_reset_token,
    verify_totp_code,
)
from .services import (
    ValidationError,
    _required_text,
    _text,
    archive_device,
    create_device,
    create_user,
    deactivate_user,
    log_activity,
    record_diagnostic,
    update_device,
    update_user,
)
from .system_info import collect_hardware, collect_network


login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "warning"


def _database_uri():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    user = quote_plus(os.environ.get("MYSQL_USER", "root"))
    password = quote_plus(os.environ.get("MYSQL_PASSWORD", ""))
    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("MYSQL_PORT", "3306")
    database = quote_plus(os.environ.get("MYSQL_DATABASE", "devmonitor"))
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


def create_app(test_config=None):
    project_dir = Path(__file__).resolve().parent.parent
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

    db.init_app(app)
    login_manager.init_app(app)

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
        if request.method in {"POST", "PATCH", "DELETE", "PUT"}:
            if request.path.startswith("/api/agent/"):
                pass  # Authenticated by token header, not session CSRF
            else:
                submitted = request.headers.get("X-CSRF-Token")
                if not submitted:
                    submitted = request.form.get("csrf_token")
                if not submitted or not secrets.compare_digest(
                    submitted, session.get("_csrf_token", "")
                ):
                    if request.path.startswith("/api/"):
                        return jsonify(error="Invalid or missing CSRF token."), 400
                    abort(400, description="Invalid or missing CSRF token.")

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

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

    _event_listeners = []

    def broadcast_event(event_type, data):
        payload = json.dumps({"event": event_type, "data": data})
        for q in list(_event_listeners):
            try:
                q.put_nowait(payload)
            except Exception:
                if q in _event_listeners:
                    _event_listeners.remove(q)

    def trigger_alert(device, severity, title, message):
        recent = Alert.query.filter(
            Alert.device_id == device.id,
            Alert.title == title,
            Alert.created_at >= datetime.now(timezone.utc) - timedelta(minutes=15),
        ).first()
        if not recent:
            alert = Alert(
                device=device,
                severity=severity,
                title=title,
                message=message,
                is_read=False,
            )
            db.session.add(alert)
            broadcast_event(
                "alert.created",
                {
                    "id": alert.id,
                    "device_id": device.id,
                    "device_name": device.device_name,
                    "severity": severity,
                    "title": title,
                    "message": message,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    def serialize_device(device):
        spec = device.hardware_spec
        latest_metric = (
            DeviceMetric.query.filter_by(device_id=device.id)
            .order_by(DeviceMetric.collected_at.desc())
            .first()
        )
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
            "cpu_percent": (
                float(latest_metric.cpu_percent)
                if latest_metric and latest_metric.cpu_percent is not None
                else None
            ),
            "memory_percent": (
                float(latest_metric.memory_percent)
                if latest_metric and latest_metric.memory_percent is not None
                else None
            ),
            "storage_percent": (
                float(latest_metric.storage_percent)
                if latest_metric and latest_metric.storage_percent is not None
                else None
            ),
            "api_token": device.api_token or "",
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
    @rate_limit(limit=10, period=60)
    def login():
        if current_user.is_authenticated and request.method == "GET":
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter(func.lower(User.username) == username.lower()).first()

            if user and user.status == "locked":
                log_activity("auth.login.locked", "user", user.id, {"username": username})
                db.session.commit()
                flash("Account is locked due to multiple failed login attempts. Reset your password or contact an administrator.", "danger")
                return render_template("login.html"), 401

            if not user or not user.is_active or not check_password_hash(user.password_hash, password):
                if user and user.is_active:
                    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                    if user.failed_login_attempts >= 5:
                        user.status = "locked"
                        log_activity("auth.account_locked", "user", user.id, {"username": username, "reason": "excessive_failed_logins"})
                        db.session.commit()
                        flash("Account locked due to 5 consecutive failed login attempts. Please reset your password.", "danger")
                        return render_template("login.html"), 401
                    else:
                        remaining = 5 - user.failed_login_attempts
                        log_activity("auth.login.failed", "user", user.id, {"attempt": user.failed_login_attempts})
                        db.session.commit()
                        flash(f"Invalid username or password. ({remaining} attempt{'s' if remaining != 1 else ''} remaining before lockout)", "danger")
                        return render_template("login.html"), 401
                else:
                    log_activity("auth.login.failed_unknown", details={"username": username})
                    db.session.commit()
                    flash("Invalid username or password.", "danger")
                    return render_template("login.html"), 401

            user.failed_login_attempts = 0
            db.session.commit()

            next_url = request.form.get("next", "") or request.args.get("next", "")
            if next_url:
                target = urlsplit(urljoin(request.host_url, next_url))
                if target.scheme not in {"http", "https"} or target.netloc != request.host:
                    next_url = ""

            if user.mfa_enabled and user.totp_secret:
                session["mfa_pending_user_id"] = user.id
                session["mfa_next_url"] = next_url
                return redirect(url_for("mfa_verify"))

            session.clear()
            login_user(user, remember=False, fresh=True)
            user.last_login_at = datetime.now(timezone.utc)
            log_activity("auth.login.success", "user", user.id)
            db.session.commit()
            return redirect(next_url or url_for("dashboard"))
        return render_template("login.html")

    @app.route("/login/mfa", methods=["GET", "POST"])
    @rate_limit(limit=10, period=60)
    def mfa_verify():
        pending_id = session.get("mfa_pending_user_id")
        if not pending_id:
            return redirect(url_for("login"))
        user = db.session.get(User, pending_id)
        if not user or not user.is_active:
            session.pop("mfa_pending_user_id", None)
            return redirect(url_for("login"))

        if request.method == "POST":
            code = request.form.get("totp_code", "").strip()
            if verify_totp_code(user.totp_secret, code):
                next_url = session.pop("mfa_next_url", "")
                session.pop("mfa_pending_user_id", None)
                session.clear()
                login_user(user, remember=False, fresh=True)
                user.last_login_at = datetime.now(timezone.utc)
                log_activity("auth.mfa.success", "user", user.id)
                db.session.commit()
                return redirect(next_url or url_for("dashboard"))
            flash("Invalid or expired authentication code. Please try again.", "danger")
            log_activity("auth.mfa.failed", "user", user.id)
            db.session.commit()
            return render_template("mfa_verify.html"), 401

        return render_template("mfa_verify.html")

    @app.route("/forgot-password", methods=["GET", "POST"])
    @rate_limit(limit=5, period=60)
    def forgot_password():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            identity = request.form.get("identity", "").strip()
            user = User.query.filter(
                (func.lower(User.username) == identity.lower())
                | (func.lower(User.email) == identity.lower())
            ).first()
            if user:
                token = generate_reset_token(user.email, app.config["SECRET_KEY"])
                reset_url = url_for("reset_password", token=token, _external=True)
                log_activity("auth.password_reset_requested", "user", user.id)
                db.session.commit()
                flash(
                    f"Recovery token generated. Use this link to reset your password: <a href='{reset_url}' class='alert-link'>{reset_url}</a>",
                    "info",
                )
            else:
                flash(
                    "If that username or email exists in our system, recovery instructions have been prepared.",
                    "info",
                )
            return render_template("forgot_password.html")
        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    @rate_limit(limit=5, period=60)
    def reset_password(token):
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        email = verify_reset_token(token, app.config["SECRET_KEY"])
        if not email:
            flash("The recovery link is invalid or has expired.", "danger")
            return redirect(url_for("forgot_password"))

        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for("login"))

        if request.method == "POST":
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if len(new_password) < 12 or len(new_password) > 1024:
                flash("Password must contain at least 12 characters.", "danger")
                return render_template("reset_password.html", token=token), 400
            if new_password != confirm_password:
                flash("Passwords do not match.", "danger")
                return render_template("reset_password.html", token=token), 400

            user.password_hash = generate_password_hash(new_password)
            user.failed_login_attempts = 0
            user.locked_until = None
            if user.status == "locked":
                user.status = "active"
            log_activity("auth.password_reset_completed", "user", user.id)
            db.session.commit()
            flash("Your password has been successfully reset. You may now sign in.", "success")
            return redirect(url_for("login"))

        return render_template("reset_password.html", token=token)

    @app.route("/register", methods=["GET", "POST"])
    @rate_limit(limit=10, period=60)
    def register():
        if current_user.is_authenticated and request.method == "GET":
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            try:
                user = create_user(request.form, role_name="User")
                log_activity("auth.register", "user", user.id)
                db.session.commit()
            except ValidationError as error:
                flash(str(error), "danger")
                return render_template("register.html"), 400
            flash("Account created. You can now sign in.", "success")
            return redirect(url_for("login"))
        return render_template("register.html")

    @app.post("/logout")
    @login_required
    def logout():
        user_id = current_user.id
        logout_user()
        session.clear()
        log_activity("auth.logout", "user", user_id)
        db.session.commit()
        flash("You have been signed out.", "info")
        return redirect(url_for("login"))

    @app.get("/api/mfa/status")
    @login_required
    def mfa_status():
        return jsonify(enabled=bool(current_user.mfa_enabled))

    @app.post("/api/mfa/setup")
    @login_required
    def mfa_setup():
        secret = generate_totp_secret()
        session["pending_totp_secret"] = secret
        uri = get_totp_uri(secret, current_user.username)
        return jsonify(secret=secret, uri=uri)

    @app.post("/api/mfa/enable")
    @login_required
    def mfa_enable():
        secret = session.get("pending_totp_secret")
        if not secret:
            return api_error("No MFA setup in progress.")
        data = api_data()
        code = data.get("code", "")
        if not verify_totp_code(secret, code):
            return api_error("Invalid verification code. Please check your authenticator app.")
        current_user.totp_secret = secret
        current_user.mfa_enabled = True
        session.pop("pending_totp_secret", None)
        log_activity("auth.mfa.enabled", "user", current_user.id)
        db.session.commit()
        return jsonify(message="MFA enabled successfully.", enabled=True)

    @app.post("/api/mfa/disable")
    @login_required
    def mfa_disable():
        data = api_data()
        password = data.get("password", "")
        if not check_password_hash(current_user.password_hash, password):
            return api_error("Incorrect password.")
        current_user.mfa_enabled = False
        current_user.totp_secret = None
        log_activity("auth.mfa.disabled", "user", current_user.id)
        db.session.commit()
        return jsonify(message="MFA disabled successfully.", enabled=False)

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
            broadcast_event(
                "fleet.updated",
                {"action": "added", "device": serialize_device(device)},
            )
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
            broadcast_event(
                "fleet.updated",
                {"action": "updated", "device": serialize_device(device)},
            )
        except ValidationError as error:
            return api_error(error)
        return jsonify(serialize_device(device))

    @app.delete("/api/devices/<int:device_id>")
    @login_required
    def delete_device(device_id):
        device = db.get_or_404(Device, device_id)
        can_manage_device(device)
        archive_device(device)
        broadcast_event(
            "fleet.updated",
            {"action": "archived", "device_id": device_id},
        )
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
            checks=[
                {
                    "name": check.check_name,
                    "category": check.category,
                    "status": check.status,
                    "summary": check.result_summary,
                }
                for check in run.checks
            ],
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
                    "checks": [
                        {
                            "name": c.check_name,
                            "category": c.category,
                            "status": c.status,
                            "summary": c.result_summary,
                        }
                        for c in run.checks
                    ],
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
        )

    @app.get("/api/health")
    def health_check():
        db_status = "ok"
        try:
            db.session.execute(func.now())
        except Exception as exc:
            db_status = f"unhealthy: {exc}"
        return jsonify(
            status="healthy" if db_status == "ok" else "degraded",
            database=db_status,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Real-Time Telemetry & Endpoint Agent Endpoints
    # ------------------------------------------------------------------

    @app.post("/api/agent/register")
    def agent_register():
        data = api_data()
        username = data.get("username", "").strip()
        password = data.get("password", "")
        user = User.query.filter(func.lower(User.username) == username.lower()).first()
        if not user or not user.is_active or not check_password_hash(user.password_hash, password):
            return api_error("Invalid user credentials.", 401)

        name = _required_text(data, "name", limit=120)
        hostname = _text(data, "hostname", limit=255) or name
        device_type = _required_text(data, "type", limit=64)
        operating_system = _text(data, "os", limit=120) or "Unknown OS"

        token = secrets.token_hex(32)
        device = Device(
            asset_tag=f"DM-{secrets.token_hex(8).upper()}",
            api_token=token,
            device_name=name,
            hostname=hostname,
            device_type=device_type,
            operating_system=operating_system,
            operating_system_version=operating_system,
            status="online",
            owner=user,
            registered_by=user,
            last_seen_at=datetime.now(timezone.utc),
        )

        hw_payload = data.get("hardware")
        if isinstance(hw_payload, dict):
            spec_data = {
                "cpu_model": hw_payload.get("cpu_model"),
                "cpu_cores": hw_payload.get("cpu_cores"),
                "cpu_threads": hw_payload.get("cpu_threads"),
                "memory_bytes": hw_payload.get("memory_bytes"),
                "storage_bytes": hw_payload.get("storage_bytes"),
                "operating_system_version": hw_payload.get("operating_system_version"),
            }
        else:
            spec_data = collect_hardware()
        device.hardware_spec = DeviceSpecification(**spec_data)

        net_payload = data.get("network")
        if isinstance(net_payload, dict):
            net_data = {
                "ip_address": net_payload.get("ip_address"),
                "subnet_mask": net_payload.get("subnet_mask"),
                "default_gateway": net_payload.get("default_gateway"),
                "dns_server": net_payload.get("dns_server"),
                "connectivity_status": net_payload.get("connectivity_status", "connected"),
            }
        else:
            net_data = collect_network()
        device.network_records.append(NetworkRecord(**net_data))

        db.session.add(device)
        db.session.flush()
        log_activity("agent.device.registered", "device", device.id, {"hostname": hostname}, actor_id=user.id)
        db.session.commit()

        broadcast_event("fleet.updated", {"action": "added", "device": serialize_device(device)})

        return jsonify(
            message="Device registered successfully with agent.",
            device_id=device.id,
            token=token,
            asset_tag=device.asset_tag,
        ), 201

    @app.post("/api/agent/metrics")
    def agent_metrics():
        token = request.headers.get("X-Device-Token") or request.headers.get("X-Agent-Token")
        if not token:
            return api_error("Missing X-Device-Token header.", 401)
        device = Device.query.filter_by(api_token=token).first()
        if not device or device.status == "retired":
            return api_error("Invalid device token.", 401)

        data = api_data()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        device.status = "online"

        cpu_pct = data.get("cpu_percent")
        mem_pct = data.get("memory_percent")
        storage_pct = data.get("storage_percent")

        sample = DeviceMetric(
            device=device,
            cpu_percent=cpu_pct,
            memory_percent=mem_pct,
            storage_percent=storage_pct,
            memory_used_bytes=data.get("memory_used_bytes"),
            storage_used_bytes=data.get("storage_used_bytes"),
            network_rx_bytes=data.get("network_rx_bytes"),
            network_tx_bytes=data.get("network_tx_bytes"),
            collected_at=now,
        )
        db.session.add(sample)

        # Threshold evaluation
        if cpu_pct is not None and float(cpu_pct) >= 85.0:
            trigger_alert(
                device=device,
                severity="critical" if float(cpu_pct) >= 95.0 else "warning",
                title=f"High CPU utilization on {device.device_name}",
                message=f"CPU load reached {cpu_pct}% on {device.device_name}.",
            )
        if storage_pct is not None and float(storage_pct) >= 90.0:
            trigger_alert(
                device=device,
                severity="critical" if float(storage_pct) >= 95.0 else "warning",
                title=f"Low disk space on {device.device_name}",
                message=f"Storage utilization reached {storage_pct}% on {device.device_name}.",
            )

        db.session.commit()

        broadcast_event(
            "device.metrics",
            {
                "device_id": device.id,
                "device_name": device.device_name,
                "status": "Online",
                "cpu": cpu_pct,
                "ram": mem_pct,
                "storage": storage_pct,
                "lastUpdated": now.isoformat(),
            },
        )

        return jsonify(status="ok", recorded_at=now.isoformat())

    @app.post("/api/agent/diagnostics")
    def agent_diagnostics():
        token = request.headers.get("X-Device-Token") or request.headers.get("X-Agent-Token")
        if not token:
            return api_error("Missing X-Device-Token header.", 401)
        device = Device.query.filter_by(api_token=token).first()
        if not device or device.status == "retired":
            return api_error("Invalid device token.", 401)

        data = api_data()
        checks_data = data.get("checks", [])
        now = datetime.now(timezone.utc)

        has_failure = any(c.get("status") == "failed" for c in checks_data)
        has_warning = any(c.get("status") == "warning" for c in checks_data)

        run = DiagnosticRun(
            device=device,
            initiated_by=device.owner,
            status="completed",
            summary=f"Agent diagnostic reported {len(checks_data)} check(s).",
            detected_problem="Hardware anomaly detected." if has_failure else ("Warning thresholds reached." if has_warning else None),
            recommendation="Review system logs and inspect resources." if (has_failure or has_warning) else "System operating nominally.",
            started_at=now,
            finished_at=now,
        )

        for c in checks_data:
            run.checks.append(
                DiagnosticCheck(
                    check_name=c.get("check_name", "Diagnostic Check"),
                    category=c.get("category", "system"),
                    status=c.get("status", "passed"),
                    result_summary=c.get("result_summary"),
                    details=c.get("details"),
                    measured_at=now,
                )
            )

        db.session.add(run)
        log_activity("agent.diagnostic.recorded", "diagnostic_run", run.id, actor_id=device.owner_user_id)
        db.session.commit()

        return jsonify(run_id=run.id, status="recorded"), 201

    # ------------------------------------------------------------------
    # Server-Sent Events (SSE) Stream
    # ------------------------------------------------------------------

    @app.get("/api/events")
    @login_required
    def event_stream():
        def generate():
            q = queue.Queue(maxsize=100)
            _event_listeners.append(q)
            try:
                yield f"data: {json.dumps({'event': 'connected'})}\n\n"
                while True:
                    try:
                        msg = q.get(timeout=20.0)
                        yield f"data: {msg}\n\n"
                    except queue.Empty:
                        yield ": ping\n\n"
            except GeneratorExit:
                if q in _event_listeners:
                    _event_listeners.remove(q)

        return Response(generate(), mimetype="text/event-stream")

    # ------------------------------------------------------------------
    # Alerts & Notification Center Endpoints
    # ------------------------------------------------------------------

    @app.get("/api/alerts")
    @login_required
    def list_alerts():
        query = Alert.query
        if not current_user.is_admin:
            query = query.join(Device).filter(Device.owner_user_id == current_user.id)
        alerts = query.order_by(Alert.created_at.desc()).limit(50).all()
        return jsonify([
            {
                "id": a.id,
                "device_id": a.device_id,
                "device_name": a.device.device_name if a.device else "System",
                "severity": a.severity,
                "title": a.title,
                "message": a.message,
                "is_read": a.is_read,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ])

    @app.post("/api/alerts/<int:alert_id>/read")
    @login_required
    def mark_alert_read(alert_id):
        alert = db.get_or_404(Alert, alert_id)
        if not current_user.is_admin and alert.device and alert.device.owner_user_id != current_user.id:
            abort(403)
        alert.is_read = True
        db.session.commit()
        return jsonify(status="ok")

    @app.post("/api/alerts/clear-all")
    @login_required
    def clear_all_alerts():
        query = Alert.query
        if not current_user.is_admin:
            query = query.join(Device).filter(Device.owner_user_id == current_user.id)
        query.filter_by(is_read=False).update({Alert.is_read: True})
        db.session.commit()
        return jsonify(status="ok")

    # ------------------------------------------------------------------
    # Telemetry History & Exportable Reports
    # ------------------------------------------------------------------

    @app.get("/api/devices/<int:device_id>/metrics/history")
    @login_required
    def device_metrics_history(device_id):
        device = db.get_or_404(Device, device_id)
        can_manage_device(device)
        metrics = (
            DeviceMetric.query.filter_by(device_id=device_id)
            .order_by(DeviceMetric.collected_at.desc())
            .limit(30)
            .all()
        )
        return jsonify([
            {
                "time": m.collected_at.strftime("%H:%M:%S"),
                "timestamp": m.collected_at.isoformat(),
                "cpu": float(m.cpu_percent) if m.cpu_percent is not None else 0.0,
                "ram": float(m.memory_percent) if m.memory_percent is not None else 0.0,
                "storage": float(m.storage_percent) if m.storage_percent is not None else 0.0,
            }
            for m in reversed(metrics)
        ])

    @app.get("/api/reports/devices")
    @login_required
    def export_devices_csv():
        import csv
        import io
        from flask import make_response

        query = Device.query.filter(Device.status != "retired")
        if not current_user.is_admin:
            query = query.filter_by(owner_user_id=current_user.id)
        devices = query.order_by(Device.id.asc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Asset Tag",
            "Device Name",
            "Hostname",
            "Type",
            "OS",
            "Owner",
            "Status",
            "CPU Model",
            "RAM (GB)",
            "Storage (GB)",
            "Last Seen",
            "Registered At",
        ])
        for d in devices:
            spec = d.hardware_spec
            ram_gb = round(spec.memory_bytes / (1024**3), 1) if spec and spec.memory_bytes else "N/A"
            storage_gb = round(spec.storage_bytes / (1024**3), 1) if spec and spec.storage_bytes else "N/A"
            writer.writerow([
                d.asset_tag,
                d.device_name,
                d.hostname,
                d.device_type,
                d.operating_system,
                d.owner.full_name,
                d.status.capitalize(),
                spec.cpu_model if spec else "N/A",
                ram_gb,
                storage_gb,
                d.last_seen_at.isoformat() if d.last_seen_at else "Never",
                d.registered_at.isoformat(),
            ])

        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=devmonitor_fleet_report.csv"
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        return response

    @app.get("/api/reports/activity")
    @admin_required
    def export_activity_csv():
        import csv
        import io
        from flask import make_response

        logs = ActivityLog.query.order_by(ActivityLog.occurred_at.desc()).limit(1000).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Timestamp", "Actor", "Event Type", "Entity Type", "Entity ID", "Details"])
        for log in logs:
            writer.writerow([
                log.id,
                log.occurred_at.isoformat(),
                log.actor.username if log.actor else "System",
                log.event_type,
                log.entity_type or "",
                log.entity_id or "",
                json.dumps(log.details) if log.details else "",
            ])

        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=devmonitor_audit_logs.csv"
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        return response

    @app.get("/api/audit-logs")
    @admin_required
    def list_audit_logs():
        limit = min(int(request.args.get("limit", 100)), 500)
        logs = ActivityLog.query.order_by(ActivityLog.occurred_at.desc()).limit(limit).all()
        return jsonify([
            {
                "id": log.id,
                "timestamp": log.occurred_at.isoformat(),
                "actor": log.actor.username if log.actor else "System",
                "actor_id": log.actor_user_id,
                "event": log.event_type,
                "entity": log.entity_type or "—",
                "entity_id": log.entity_id or "—",
                "details": log.details or {},
            }
            for log in logs
        ])

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
        serialized_devs = [serialize_device(device) for device in devices]

        valid_cpus = [d["cpu_percent"] for d in serialized_devs if d.get("cpu_percent") is not None]
        valid_rams = [d["memory_percent"] for d in serialized_devs if d.get("memory_percent") is not None]
        valid_disks = [d["storage_percent"] for d in serialized_devs if d.get("storage_percent") is not None]

        if valid_cpus:
            fleet_cpu = round(sum(valid_cpus) / len(valid_cpus), 1)
        else:
            try:
                import psutil
                fleet_cpu = round(psutil.cpu_percent(interval=0.1), 1)
            except Exception:
                fleet_cpu = 0.0

        if valid_rams:
            fleet_ram = round(sum(valid_rams) / len(valid_rams), 1)
        else:
            try:
                import psutil
                fleet_ram = round(psutil.virtual_memory().percent, 1)
            except Exception:
                fleet_ram = 0.0

        if valid_disks:
            fleet_disk = round(sum(valid_disks) / len(valid_disks), 1)
        else:
            try:
                import shutil
                d_usage = shutil.disk_usage(os.path.expanduser("~"))
                fleet_disk = round((d_usage.used / d_usage.total) * 100, 1)
            except Exception:
                fleet_disk = 0.0

        return jsonify(
            devices=serialized_devs,
            total=len(devices),
            online=sum(device.status == "online" for device in devices),
            offline=sum(device.status == "offline" for device in devices),
            metrics={
                "cpu": fleet_cpu,
                "ram": fleet_ram,
                "storage": fleet_disk,
            },
        )

    @app.cli.command("init-db")
    def init_db_command():
        """Create missing tables and seed standard RBAC roles/permissions."""
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
        click.echo("Database tables and default RBAC roles are ready.")

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
                "Run `flask --app python.app init-db` from device_monitoring_prototype."
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

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "").lower() == "true", port=5000)
