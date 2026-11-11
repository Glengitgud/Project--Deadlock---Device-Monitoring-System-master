# Quality Assurance Report

**System:** Centralized End-User Device Monitoring and Diagnostic System (DevMonitor)  
**Review date:** 2026-11-11  
**Status:** Login, registration, dashboard, device, and admin flows are covered by application-level tests. The app now reports database setup failures as 503 responses. Live MySQL access and schema operations are not verified.

## Current incident

The login and registration GET pages render successfully. The form submissions query or write MySQL and failed because the local app was using its default `root` account without a password (`OperationalError 1045: Access denied`). The app previously surfaced that database failure as an Internal Server Error. It now loads the prototype-local `.env` when launched from the repository root and returns a setup-oriented 503 response for database errors or missing RBAC seed data. Valid MySQL credentials, schema, and seeded roles are still required for successful sign-in/registration.

## Scope

This report covers the Flask application, account and session flows, authorization, device management, inventory capture, diagnostic and network history, database schema, browser-facing pages, and the known production gaps listed in `FEATURES_AND_FUTURE_WORK.md`.

## Feature and database coverage

| Area | Implemented behavior | QA coverage / limitation |
|---|---|---|
| Application startup and pages | Package-based Flask app, login and registration pages, dashboard, devices, and admin pages | Tests cover login/register rendering, standard-user dashboard/device/API routes, admin view, and static CSS. Startup requires the documented package-based command. |
| Accounts and passwords | Registration persists users; Werkzeug hashes passwords; login verifies hashes | Tests verify registration, incorrect/correct password behavior, hash persistence, and clear handling when DB/schema/roles are unavailable. |
| Session and access control | Flask-Login sessions, CSRF checks, owner-scoped device operations, admin-only user management | Tests verify a standard user is denied the admin page and an administrator can manage users. |
| Device inventory | Owner-linked device records; validated create/update/archive; dashboard and device list read from the database | Device registration, ownership, persisted specification and network records, and history are exercised with SQLite. |
| Hardware and network snapshots | Best-effort system information saved on device registration | Test values are supplied in the integration test. Production collection currently sees the Flask host, not a remote endpoint. |
| Diagnostics and audit | Each scan request appends a diagnostic run/check; database writes record activity | Tests verify diagnostic and network history persistence. A scan is explicitly a placeholder; no hardware diagnostic runs. |
| MySQL schema | SQLAlchemy models and `schema.sql` define RBAC, accounts, devices, specifications, interfaces/observations, network records, diagnostics, metrics, and audit history | Models can be exercised using SQLite. The MySQL DDL must be applied and tested on the target MySQL server separately. |
| User interface | Responsive dark-themed login, registration, dashboard, device, and admin templates | Server-rendered login and registration pages are integration-tested; a browser/device compatibility matrix has not been run. |

### Database tables

The schema contains 14 tables: `users`, `roles`, `permissions`, `user_roles`, `role_permissions`, `devices`, `device_specifications`, `network_interfaces`, `network_observations`, `network_records`, `diagnostic_runs`, `diagnostic_checks`, `device_metrics`, and `activity_logs`.

Core relationships include users-to-roles and roles-to-permissions many-to-many links; users-to-owned/registered-devices; one device-to-one specification; one device-to-many network interfaces, network observations, network records, diagnostic runs, and metric samples; and one diagnostic run-to-many checks. Activity records optionally reference their actor.

## Verification

The application test suite uses isolated SQLite databases and verifies:

- login and registration templates render, along with authenticated standard-user/admin pages and standard APIs;
- registration stores a password hash and rejects an incorrect password;
- unavailable database/schema or missing role seed data returns a setup-oriented 503 instead of an unhandled 500;
- authenticated users can register devices and retain linked specification/network data;
- diagnostic and network history persists;
- standard users cannot access administrator views; and
- administrator user creation and role protections work.

Additional verification includes Python syntax compilation, JavaScript syntax checking, Flask route discovery, and compilation of SQLAlchemy table definitions with the MySQL dialect. A live connection attempt was rejected because MySQL's default `root` account has no configured password; no project `.env` file is present. The app now explicitly loads `device_monitoring_prototype\.env` when launched from the repository root. These checks do not replace running the migration or schema against the actual MySQL version and configured application credentials.

Run the integration suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s device_monitoring_prototype\tests -v
```

## Known gaps and release risks

- Live connectivity to MySQL, schema creation/migration, and persistence across a MySQL restart remain unverified until valid credentials are configured in `device_monitoring_prototype\.env`.
- An endpoint agent is needed for remote hardware/network inventory and live telemetry. The current collector sees the Flask host.
- Diagnostic records are placeholders; no real checks are executed.
- MFA, password recovery, rate limiting, production HTTPS/deployment, live alerts, and reporting remain future work as described in `FEATURES_AND_FUTURE_WORK.md`.
- Before deployment, configure a persistent secret key, secure cookies behind HTTPS, least-privilege database credentials, backups, and the production server configuration.
