# Quality Assurance Report

**System:** Centralized End-User Device Monitoring and Diagnostic System (DevMonitor)
**Review date:** 2026-11-12
**Result:** Application-level tests pass against isolated SQLite databases. Live MySQL operation is blocked by local configuration; the database service is running, but no `device_monitoring_prototype\.env` file is present.

## Scope and feature status

This review covers the implemented application and the production roadmap in `FEATURES_AND_FUTURE_WORK.md`. Roadmap items are not treated as delivered features.

| Feature area | Current behavior | Verification and limitations |
|---|---|---|
| Startup and authentication pages | Flask serves sign-in and registration; package-based commands initialize the app. | Login and registration pages render in integration tests. |
| Accounts and passwords | Registration creates standard-user accounts; Werkzeug hashes passwords; login checks the hash; accounts can be disabled. | Tests verify registration, hash storage, correct/incorrect passwords, and disabled/admin restrictions. Password reset and MFA are not implemented. |
| Sessions and request security | Flask-Login sessions, CSRF validation for writes, HttpOnly/SameSite cookies, configurable Secure cookies, and server-side authorization. | Tests exercise authenticated routes and role restrictions. Rate limiting and production HTTPS are not implemented. |
| Roles and administration | `init-db` seeds Administrator/User roles and permissions; admins can create, edit, and deactivate users; the last active admin cannot be removed or demoted. | Tests cover admin access, user creation, and role protections. |
| Device inventory | Signed-in users register, edit, view, and archive their own devices; admins can manage all devices; archived records retain history. | Tests verify owner linkage and persisted specification/network data. |
| Dashboard and device UI | Dashboard reads authorized fleet records; device page provides search, sort, pagination, device actions, and toast feedback. | Routes and APIs are tested; the browser interactions and responsive layout have not had automated browser or device-matrix testing. |
| Host inventory | Registration stores best-effort hardware and network information from the machine running Flask. | Tests use deterministic collector values. This is not remote endpoint collection; GPU and motherboard values are currently unavailable. |
| Diagnostics and history | A scan appends a diagnostic run/check and history APIs return diagnostic and network records. | Persistence is tested. The scan is explicitly a placeholder and does not execute hardware checks. |
| UI/UX | Dark minimal theme, responsive sidebar, Bootstrap components, login/register, dashboard, device, and admin pages. | Templates and static assets are served by the app; visual accessibility/contrast and cross-browser behavior have not been independently measured. |
| Roadmap features | Live telemetry/alerts, reporting, endpoint agents, recovery/MFA, real diagnostics, and production deployment are listed as future work. | Not implemented or claimed as passing; see `FEATURES_AND_FUTURE_WORK.md`. |

## Database scope

The SQLAlchemy models and `schema.sql` define 14 tables:

| Table(s) | Responsibility |
|---|---|
| `users` | Account identity, password hash, status, and timestamps. |
| `roles`, `permissions` | RBAC role and permission definitions. |
| `user_roles`, `role_permissions` | Many-to-many account-role and role-permission associations. |
| `devices` | Device inventory, status, owner, registering user, and timestamps. |
| `device_specifications` | One-to-one CPU, memory, storage, GPU, BIOS, motherboard, and OS snapshot. |
| `network_interfaces`, `network_observations` | Interface inventory and timestamped address/connection observations. |
| `network_records` | Timestamped device IP, subnet, gateway, DNS, and connectivity snapshots. |
| `diagnostic_runs`, `diagnostic_checks` | Diagnostic history and per-run check results. |
| `device_metrics` | Historical CPU, memory, storage, and network metrics; collection is not enabled. |
| `activity_logs` | Timestamped actions with an optional actor and entity reference. |

Relationships, unique constraints, status checks, and lookup indexes are represented in the models/schema. Devices belong to a user; a device has one specification and can have many network snapshots, interfaces, diagnostic runs, and metrics; each run can have multiple checks. User/role and role/permission links use association tables. Account deactivation and device retirement preserve historical records.

**Database verification boundary:** the integration suite uses SQLite and does not prove MySQL connectivity, MySQL DDL/migration compatibility, permissions, or persistence after a MySQL restart. A new database can be initialized with `flask --app device_monitoring_prototype.app init-db`; an earlier project schema must be backed up and upgraded using `migrations\001_database_integration.sql` first. See `README.md` and `DATABASE_DESIGN.md`.

## Current database incident

The local `MySQL80` service is running, but `device_monitoring_prototype\.env` is absent. The app therefore falls back to `root` with an empty password and targets `devmonitor` on `127.0.0.1`; a direct `SELECT 1` fails with MySQL error **1045 (access denied)**. This is a local credential/configuration issue, not a failing application test. Valid credentials and an initialized database cannot be supplied or verified from this checkout.

The unavailable page now gives the setup steps: copy `.env.example` to `.env`, set the actual MySQL user/password and persistent secret, confirm the database exists, run `init-db`, then restart the app. Keep `.env` private. For existing legacy data, back up and apply the documented migration before initialization.

## Test results

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s device_monitoring_prototype\tests -v
```

The eight integration tests pass. They cover page rendering, environment-file selection, registration/login and password hashes, database/seed-data error responses, standard-user pages/APIs, device ownership and persisted snapshots/history, standard-user admin denial, and administrator account/role protections. Test databases are isolated SQLite instances; no live MySQL or browser automation was run.

## Release risks and acceptance follow-up

- Configure a private `.env` with valid least-privilege MySQL credentials, then verify `init-db`, account creation, and persistence on the target MySQL 8 instance.
- Apply and verify the legacy migration only where an earlier schema exists; back up first.
- Add browser/accessibility and responsive-device checks before relying on the UI for deployment.
- Real endpoint monitoring, live metrics, diagnostics, alerts, exports, MFA/recovery, rate limiting, production HTTPS/server setup, and backup/restore remain future work.
- Before deployment, set a persistent random `SECRET_KEY`, enable Secure cookies over HTTPS, and configure database backups and production serving as described in the project documentation.
