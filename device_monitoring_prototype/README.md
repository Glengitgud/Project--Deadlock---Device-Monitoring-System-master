# DevMonitor

DevMonitor is a Flask application for centralized end-user device inventory and diagnostics. It uses Flask-Login sessions, Werkzeug password hashes, Flask-SQLAlchemy, and MySQL 8 for persistent account, device, hardware, network, diagnostic, and audit records.

## Setup on Windows

1. From the repository root, create a MySQL 8 database and application user. Copy `device_monitoring_prototype\.env.example` to `device_monitoring_prototype\.env`, then set the MySQL credentials and a long random `SECRET_KEY`. Keep `.env` private.
2. From the repository root, create and activate a Python 3.12 environment and install the dependencies:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r device_monitoring_prototype\requirements.txt
   ```
3. If you already created the earlier DevMonitor schema, back up the database, assign an owner to any existing ownerless devices, and run `device_monitoring_prototype\migrations\001_database_integration.sql` once. For a new empty database, execute `device_monitoring_prototype\schema.sql` in MySQL Workbench.
4. Initialize RBAC roles, create the first administrator, and launch Flask:
   ```powershell
   python -m flask --app device_monitoring_prototype.app init-db
   python -m flask --app device_monitoring_prototype.app create-admin
   python -m flask --app device_monitoring_prototype.app run
   ```
5. Open **http://127.0.0.1:5000**. Public registration creates standard-user accounts only.

The app also accepts a `DATABASE_URL`, for example:
`mysql+pymysql://devmonitor_app:password@127.0.0.1:3306/devmonitor?charset=utf8mb4`.
Set `COOKIE_SECURE=true` when using HTTPS. The generated fallback session key is only suitable for local development; set a persistent `SECRET_KEY` for normal use.
The app loads `device_monitoring_prototype\.env` explicitly when started from the repository root. Login and registration require valid MySQL credentials, an initialized schema, and seeded roles. If the database is unavailable, the app displays a setup message instead of returning a generic 500 page.

## Features

- Account registration/login stores only Werkzeug password hashes and uses Flask-Login.
- RBAC roles are seeded by `init-db`; creating an administrator requires the CLI or another administrator.
- Device list and CRUD are owner-scoped; administrators can view/manage all accounts and devices.
- Device registration saves a hardware specification and network snapshot; diagnostic actions save history entries. Deactivation and device removal are soft operations so historical records remain.
- API write requests use a session CSRF token.

**Collection limitation:** the current collector records information about the computer running Flask, not an arbitrary remote device entered in the form. Remote hardware, network, and real diagnostic collection requires an installed, authenticated endpoint agent; those monitoring checks are not implemented here.

## Files

- `app.py` — Flask application, authentication, views, JSON CRUD endpoints, and CLI commands.
- `models.py` — SQLAlchemy tables and relationships.
- `services.py` — validated CRUD functions and history persistence.
- `system_info.py` — best-effort local host inventory.
- `schema.sql` — complete MySQL schema for new installations.
- `migrations\001_database_integration.sql` — one-time schema upgrade from the earlier design.
- `DATABASE_DESIGN.md` — ERD summary, tables, relationships, and example SQL queries.
