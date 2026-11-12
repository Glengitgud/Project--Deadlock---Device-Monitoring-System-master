# Device Monitoring Prototype — Feature Summary

## Simulated Features vs. Future Development

This document explains which features of the prototype are **simulated**
(for visual demonstration only) and which would require **real
development** in a full production system.

---

## UI/UX Design

The prototype uses a **dark minimal theme** built on a custom colour
palette derived from three core hex values:

| Token | Hex | Usage |
|---|---|---|
| `--dm-darkest` | `#0d0221` | Page backgrounds, deepest surface |
| `--dm-dark` | `#0f084b` | Sidebar, top navbar, card headers |
| `--dm-accent` | `#26408b` | Primary buttons, active states, focus rings |

Design principles followed:

- **Dark-first, minimal UI** — reduces visual clutter and eye strain.
- **Consistent spacing & border radii** — 12 px card radius, 8 px input radius.
- **Accessible contrast** — light text on dark surfaces meets WCAG AA.
- **Responsive layout** — sidebar collapses to a mobile drawer at ≤ 992 px.
- **Clean login screen** — no extraneous information; a focused sign-in form.

---

## Implemented Database Features

The application now uses MySQL through Flask-SQLAlchemy. Public registration stores standard-user accounts with Werkzeug password hashes; Flask-Login manages sessions. `init-db` ensures the reserved `admin` account is active, has the Administrator role, and uses the hashed bootstrap password `admin123`. The account is excluded from user management and protected from public registration. Administrator-only user management/log access and owner-scoped device operations are enforced by Flask views, not by JavaScript alone.

| Feature | Current implementation |
|---|---|
| **User Registration and Login** | User records and hashed passwords are persisted in MySQL; invalid credentials are rejected and login attempts are recorded in activity logs. |
| **Role-Based Access** | Roles and permissions are stored in RBAC tables; `/admin`, user-management, and administrator log endpoints require an administrator. |
| **Device Registration** | Device and owner foreign key, specification row, and network record are persisted together. |
| **Device Editing and Removal** | Active devices can be updated; archive/restore uses a lifecycle state, while administrator deletion is a retained soft delete. No application route physically removes devices. |
| **Diagnostic History** | Each scan action creates a new, explicitly placeholder diagnostic record; no actual diagnostic test runs. |
| **User Management** | Administrators can create accounts, update roles/status, and deactivate users without deleting their history. |
| **Device Details and Logs** | Owners/registrants see only approved device fields and specifications; administrators see complete relationships and audit history. Administrators can search/filter activity and device event logs. These are application records, not operating-system or web-server logs. |
| **Dashboard** | Fleet counts and rows are queried from MySQL. |
| **Search, Sort and Pagination** | Browser-side presentation of records returned from the database-backed endpoints. |
| **Input and Session Security** | Server-side validation, CSRF token checks, HttpOnly/SameSite cookies, and configurable Secure cookies. |

---

## Remaining Work for Production Monitoring

To turn this prototype into a production-ready system, the following
areas would need to be designed and built with proper backend
technologies.

### 1. Account Hardening
- Add MFA, password reset, rate limiting, and operational account recovery.
- The reserved `admin` / `admin123` bootstrap credential is for local setup only; `init-db` restores this account and credential. Replace it before deployment.
- For multi-domain login, keep local username login separate from organization email login. Validate email syntax, normalize and check the domain against an administrator-managed allowed-domains table, verify credentials and account status (active, suspended, or disabled), record success/failure without logging credentials, then redirect by assigned role. Verify domain ownership before enabling it; an email suffix alone does not establish identity.

### 2. Endpoint Agent and Real Device Collection
- Install an authenticated agent on each end-user device to collect that endpoint's hardware and network information. The current collector sees only the machine running Flask.
- Collect real CPU, RAM, storage utilization, connectivity, and diagnostic results through the agent.

### 3. Real-Time Updates
- Use WebSockets or Server-Sent Events to push live status changes to the dashboard without refreshing the page.

### 4. Security Hardening and Deployment
- Protect against common web vulnerabilities (XSS, CSRF, SQL injection).
- Use HTTPS for all communications.
- Implement rate limiting and input sanitization.
- Secure API endpoints with authentication middleware.

### 5. Reporting & Analytics
- Generate exportable reports (PDF, CSV) on device health, inventory, and user activity.
- Add historical charts showing resource usage trends over time.

### 6. Notification & Alerting System
- Send email or SMS alerts when a device goes offline or a resource threshold is exceeded.
- Provide an in-app notification center for administrators.

### 7. Deployment & Scalability
- Containerize the application (e.g., Docker).
- Deploy behind a production web server (e.g., Nginx + Gunicorn).
- Add load balancing and horizontal scaling for larger organizations.

### 8. Audit Logging
- Continue expanding audit coverage to include any future administrative actions and operational events.

---

## Summary

This prototype successfully demonstrates the **user interface** and
**workflow** of a centralized device monitoring system. It is designed
to be presented as a college project to show how the system would look
and behave.

The UI follows a **dark minimal design language** using a cohesive
palette of deep purples and blues (`#0d0221`, `#0f084b`, `#26408b`),
providing an industry-standard look with clean typography, consistent
spacing, and responsive layouts.

Accounts, device inventory, host snapshots, and diagnostic placeholder history are persisted in MySQL. The application does not yet monitor remote endpoints or execute real diagnostic tests; that requires an authenticated endpoint agent and production security/deployment work as outlined above.
