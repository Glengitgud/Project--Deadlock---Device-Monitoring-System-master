# Database and backend design

## ERD and relationships

- `users` own zero or more `devices`; each device created by the application has exactly one owner.
- `devices` have one `device_specifications` row and many `network_records` and `diagnostic_runs`.
- Each `diagnostic_run` can have multiple detailed `diagnostic_checks`.
- `users` ↔ `roles` use `user_roles`; `roles` ↔ `permissions` use `role_permissions`.
- `activity_logs` retain the acting user when available and record account/device/diagnostic events.
- Account removal is a status change and device removal archives the device, preserving the owner and all device history.

## Tables

| Table | Contents |
|---|---|
| `users` | Full name, unique username/email, Werkzeug password hash, status, timestamps |
| `roles`, `permissions` | RBAC roles and permission codes |
| `user_roles`, `role_permissions` | RBAC many-to-many associations |
| `devices` | Device name, hostname, type, OS, status, owner and registration times |
| `device_specifications` | CPU, core/thread count, RAM/storage capacity, optional GPU/motherboard, OS version |
| `network_records` | Timestamped IP, subnet mask, gateway, DNS server, connectivity status |
| `network_interfaces`, `network_observations` | Optional lower-level interface/observation inventory retained from the initial design |
| `diagnostic_runs` | Per-scan result, problem, recommendation, initiator, and timestamp |
| `diagnostic_checks` | Individual result records for checks within a diagnostic run |
| `device_metrics` | Historical CPU, memory, storage, and network metrics (not currently collected) |
| `activity_logs` | Auditable user actions for administrator oversight |

`schema.sql` creates the full MySQL 8 schema from scratch. Existing databases created from the earlier project design must first be backed up and upgraded with `migrations/001_database_integration.sql`. Run `flask --app python.app init-db` afterward to create missing tables and seed the `Administrator` and `User` roles with their permissions.

## Authentication and authorization

Public registration always creates a `User` role; it cannot grant administrator access. Passwords are hashed using `werkzeug.security.generate_password_hash` and checked using `check_password_hash`. Flask-Login manages sessions. Admin-only account management is checked server-side, device data is owner-scoped, write operations require the session CSRF token, and disabled users are rejected on subsequent requests.

Create the initial administrator interactively (password input is hidden):

```powershell
flask --app python.app create-admin
```

Database credentials are read from `.env`/environment variables or `DATABASE_URL`. Set a persistent random `SECRET_KEY`; set `COOKIE_SECURE=true` when HTTPS is enabled.

## Database CRUD and backend operations

`python/services.py` implements validated account creation/update/deactivation, device creation/update/archive, and diagnostic history insertion. Flask views in `python/app.py` expose:

| Method and path | Access | Operation |
|---|---|---|
| `POST /register` | Public | Create a standard account |
| `POST /login`, `POST /logout` | Public / signed-in | Verify password hash; start/end a Flask-Login session |
| `GET/POST /api/devices` | Signed-in | List visible devices / register an owned device |
| `PATCH/DELETE /api/devices/<id>` | Owner or admin | Update or archive; history is retained |
| `POST /api/devices/<id>/diagnostics` | Owner or admin | Append a diagnostic history record |
| `GET /api/devices/<id>/history` | Owner or admin | Read diagnostic and network history |
| `GET/POST /api/users` | Admin | List or create accounts |
| `PATCH/DELETE /api/users/<id>` | Admin | Update role/status or deactivate an account |
| `GET /api/dashboard` | Signed-in | Return the authorized device summary |

## Example MySQL queries

```sql
-- Devices visible in the fleet with their assigned account.
SELECT d.id, d.device_name, d.hostname, d.operating_system, d.status,
       u.username, d.registered_at
FROM devices AS d
JOIN users AS u ON u.id = d.owner_user_id
WHERE d.status <> 'retired'
ORDER BY d.registered_at DESC;

-- Hardware specifications for one device.
SELECT d.device_name, s.cpu_model, s.cpu_cores, s.memory_bytes,
       s.storage_bytes, s.gpu_model, s.motherboard_model,
       s.operating_system_version
FROM devices AS d
JOIN device_specifications AS s ON s.device_id = d.id
WHERE d.id = 1;

-- Complete diagnostic history, newest first.
SELECT device_id, status, summary, detected_problem, recommendation, started_at
FROM diagnostic_runs
WHERE device_id = 1
ORDER BY started_at DESC;

-- Historical network information for one device.
SELECT ip_address, subnet_mask, default_gateway, dns_server,
       connectivity_status, recorded_at
FROM network_records
WHERE device_id = 1
ORDER BY recorded_at DESC;

-- Users and their RBAC roles.
SELECT u.username, u.email, r.name AS role_name
FROM users AS u
JOIN user_roles AS ur ON ur.user_id = u.id
JOIN roles AS r ON r.id = ur.role_id;
```

## Collection scope

The current best-effort collector saves hardware and network details from the computer running Flask when a device is registered. A browser form cannot inspect the registered remote endpoint’s CPU, motherboard, GPU, gateway, or DNS. Real endpoint inventory and diagnostics require an authenticated agent installed on each device. The diagnostic action currently persists a clearly labelled placeholder record; it does not run hardware tests. Live metric collection is not enabled.
