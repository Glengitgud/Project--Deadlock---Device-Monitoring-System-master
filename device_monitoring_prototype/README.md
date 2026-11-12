# DevMonitor

DevMonitor is a Flask application for centralized end-user device inventory and diagnostics. It uses Flask-Login sessions, Werkzeug password hashes, Flask-SQLAlchemy, and the MySQL/MariaDB server included with XAMPP.

## Setup with XAMPP on Windows

1. Open the XAMPP Control Panel and start **Apache** and **MySQL**.
2. Open **http://localhost/phpmyadmin**, choose **New**, enter `devmonitor` as the database name, select `utf8mb4_unicode_ci`, and click **Create**. The app expects the database on `localhost:3306`.
3. From the repository root, copy `device_monitoring_prototype\.env.example` to `device_monitoring_prototype\.env`. The example uses XAMPP's common local default (`root` with no password); if your MySQL account differs, enter its credentials in `.env`. Set a long random `SECRET_KEY` and keep `.env` private.
4. From the repository root, create and activate a Python environment, then install the dependencies. The requirements file installs Flask, Flask-SQLAlchemy, PyMySQL, and the supporting packages:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r device_monitoring_prototype\requirements.txt
   ```
   To install the core database packages directly instead:
   ```powershell
   pip install Flask Flask-SQLAlchemy PyMySQL Flask-Login Werkzeug python-dotenv psutil cryptography
   ```
5. Create the tables and default RBAC roles/administrator, then start the app:
   ```powershell
   python -m flask --app device_monitoring_prototype.app init-db
   python -m flask --app device_monitoring_prototype.app run
   ```
6. Open **http://127.0.0.1:5000**. Public registration creates standard-user accounts only.

`init-db` calls `db.create_all()` for every SQLAlchemy model and is safe to rerun to create missing tables, but it does not alter existing tables. The app also accepts a `DATABASE_URL`. For an earlier DevMonitor schema, back up first and apply `migrations\001_database_integration.sql`. For the original XAMPP prototype schema, back up the database and apply `migrations\003_upgrade_xampp_prototype.sql` in phpMyAdmin before running `init-db`; that migration requires the legacy `users`, `devices`, and `logs` tables to be empty. The current schema has a separate `activity_logs` table for broader account/system auditing.

On first initialization, `init-db` creates the `admin` Administrator account with password `admin123` if that username is unused. Change this development bootstrap password immediately; set `ADMIN_INITIAL_PASSWORD` before initialization to choose a different initial password. Re-running initialization does not reset an existing account. Use `create-admin` only when adding another administrator.

Set `COOKIE_SECURE=true` when using HTTPS. The generated fallback session key is only suitable for local development; set a persistent `SECRET_KEY` for normal use. The app loads `device_monitoring_prototype\.env` when started from the repository root. Login and registration require a running MySQL server, valid credentials, an initialized schema, and seeded roles. If the database is unavailable, the app displays setup guidance instead of a generic 500 page.

## Test sample data

After running `init-db`, add a sample user, device, network record, and linked device log. The command prompts for a password and stores only its hash:

```powershell
python -m flask --app device_monitoring_prototype.app seed-sample-data
```

For code-based setup, the database initialization call is:

```python
from device_monitoring_prototype.app import app
from device_monitoring_prototype.models import db

with app.app_context():
    db.create_all()
```

## Features

- Account registration/login stores only Werkzeug password hashes and uses Flask-Login.
- RBAC roles are seeded by `init-db`; creating an administrator requires the CLI or another administrator.
- Device list and CRUD are owner-scoped; administrators can view/manage all accounts and devices.
- Device registration saves a hardware specification and network snapshot; diagnostic actions save history entries. Deactivation and device removal are soft operations so historical records remain.
- Device changes and diagnostic requests create linked rows in `logs`; broader audit events are kept in `activity_logs`.
- API write requests use a session CSRF token.

**Collection limitation:** the current collector records information about the computer running Flask, not an arbitrary remote device entered in the form. Remote hardware, network, and real diagnostic collection requires an installed, authenticated endpoint agent; those monitoring checks are not implemented here.

## Database unavailable

If sign-in or registration reports that the database is unavailable, confirm MySQL is running, the `devmonitor` database and application user exist, and `device_monitoring_prototype\.env` contains valid credentials. MySQL error 1045 means the server rejected the configured user/password or its database access. Then run `python -m flask --app device_monitoring_prototype.app init-db` from the repository root and restart Flask. Back up and apply the documented migration first if upgrading an existing schema.

## Files

- `app.py` — Flask application, authentication, views, JSON CRUD endpoints, and CLI commands.
- `models.py` — SQLAlchemy tables and relationships.
- `services.py` — validated CRUD functions and history persistence.
- `system_info.py` — best-effort local host inventory.
- `schema.sql` — complete MySQL/MariaDB schema for new installations.
- `migrations\001_database_integration.sql` — one-time schema upgrade from the earlier design.
- `migrations\002_device_event_logs.sql` — device event log table for manual upgrades.
- `migrations\003_upgrade_xampp_prototype.sql` — upgrade the original empty XAMPP prototype tables.
- `DATABASE_DESIGN.md` — ERD summary, tables, relationships, and example SQL queries.
