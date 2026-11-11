"""Flask application with database-backed accounts and device inventory."""

import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit

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
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from .models import (
    Alert,
    Device,
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
    archive_device,
    create_device,
    create_user,
    deactivate_user,
    log_activity,
    record_diagnostic,
    update_device,
    update_user,
)


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
