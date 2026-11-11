# DevMonitor

DevMonitor is a Flask application for centralized end-user device inventory and diagnostics. It uses Flask-Login, Werkzeug password hashes, Flask-SQLAlchemy, and MySQL 8. The responsive UI supports registration and sign-in, device inventory, history, and administrator user management.

## Windows setup

Run these commands from the repository root. Create a MySQL 8 database and application user first, then configure the private environment file:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r device_monitoring_prototype\requirements.txt
Copy-Item device_monitoring_prototype\.env.example device_monitoring_prototype\.env
```

Set the MySQL credentials and a persistent random `SECRET_KEY` in `device_monitoring_prototype\.env`. For a new database, execute `device_monitoring_prototype\schema.sql` in MySQL Workbench. To upgrade the earlier schema, back it up and run `device_monitoring_prototype\migrations\001_database_integration.sql` once.

Initialize role and permission records, create an administrator, then start the app:

```powershell
python -m flask --app device_monitoring_prototype.app init-db
python -m flask --app device_monitoring_prototype.app create-admin
python -m flask --app device_monitoring_prototype.app run
```

Open **http://127.0.0.1:5000**. Do not run `device_monitoring_prototype\app.py` as a standalone script; use the package-based Flask command above so Python resolves the application imports correctly.

## Current scope

- Accounts, hashed passwords, sessions, role checks, device ownership, hardware/network snapshots, diagnostics history, and activity logs are database-backed.
- API writes use CSRF validation; administrator and device-owner access checks run on the server.
- Collection currently describes the machine running Flask. Remote device monitoring and real diagnostic execution require an authenticated endpoint agent and are not implemented.

See [`device_monitoring_prototype/README.md`](device_monitoring_prototype/README.md) for additional setup notes, [`device_monitoring_prototype/DATABASE_DESIGN.md`](device_monitoring_prototype/DATABASE_DESIGN.md) for schema details, and [`device_monitoring_prototype/QUALITY_ASSURANCE_REPORT.md`](device_monitoring_prototype/QUALITY_ASSURANCE_REPORT.md) for the QA scope and verification status.
