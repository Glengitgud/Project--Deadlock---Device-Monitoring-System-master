# Device Monitoring Prototype — Features & Documentation

## Overview

The **DevMonitor** system is a centralized end-user device monitoring and diagnostic prototype. It demonstrates core device fleet management, resource monitoring, and administrative user controls through a clean, modern, dark minimal web interface.

---

## UI/UX Design System

The visual design follows industry-standard UI/UX principles, emphasizing focus, readability, and a streamlined user journey. The interface is styled using a cohesive dark minimal palette:

### Color Palette

| Token | Hex Value | Role & Applied Elements |
|---|---|---|
| `--dm-darkest` | `#0d0221` | Deep obsidian purple — Canvas background, inputs, base surfaces |
| `--dm-dark` | `#0f084b` | Midnight navy — Fixed sidebar navigation, top header, card headers |
| `--dm-accent` | `#26408b` | Sapphire blue — Primary call-to-actions, active nav indicators, interactive hover glow |
| `--dm-surface` | `#120636` | Card background, modal dialogs, elevated containers |
| `--dm-text` | `#f1f5f9` | Primary text (WCAG AAA contrast against dark background) |
| `--dm-text-muted` | `#94a3b8` | Secondary labels, captions, metadata |

### Industry Standard UI/UX Practices Followed
1. **Minimalist, Distraction-Free Authentication**: Extraneous prototype watermarks and sample credentials have been completely removed from the login screen, producing a production-like sign-in experience.
2. **Visual Hierarchy & Contrast**: Strong typographic scales with distinct weights, subtle translucent borders (`rgba(255, 255, 255, 0.08)`), and colored status pills for quick scanning.
3. **Accessibility**: Form controls feature clear focus indicators (`box-shadow` glow), accessible modal close icons (inverted SVG), and WCAG-compliant color contrasts.
4. **Responsive Layout**: Fluid flex and grid layouts with a collapsible mobile drawer for viewport widths $\le 992\text{px}$.
5. **Concise Codebase**: Eliminates unnecessary wrappers and redundant styles in favor of CSS custom properties and structured components.

---

## Prototype Features

### 1. Authentication & Role-Based Access
- **Account Registration and Login**: Accounts are stored in MySQL; passwords are stored as Werkzeug hashes and verified on sign-in.
- **Role Enforcement**: Flask-Login sessions and server-side administrator checks control access to user management.

### 2. Monitoring Dashboard
- **Metric Cards**: Database-backed total, online, and offline device counts.
- **Fleet Overview**: Database-backed view of authorized devices and their saved hardware specifications.
- **Resource Monitor**: Live CPU/RAM/storage metrics are not currently collected.

### 3. Device Management (CRUD)
- **Device Registration**: Devices are persisted with their owner, a best-effort application-host hardware specification, and a network record.
- **Device Inspection & Editing**: View saved specifications and update device details.
- **Diagnostic History**: Each scan action appends a clearly labelled placeholder record; no hardware tests run yet.
- **Device Removal**: Devices are archived so their diagnostic and network history is retained.
- **Search, Sorting & Pagination**: Real-time filtering by device name, multi-attribute sorting, and paginated table navigation.

### 4. Admin Panel (User Management)
- **User Directory**: View database accounts, assigned roles, and statuses.
- **User Management**: Administrators can create accounts, update roles/status, and deactivate users.
- **Search & Sort**: Filter by name or username with instant pagination.

---

## Simulated vs. Future Production Roadmap

| Feature Area | Current Implementation | Future Development |
|---|---|---|
| **Authentication** | Werkzeug password hashes, Flask-Login sessions, server-side RBAC | MFA and account recovery |
| **Data Persistence** | MySQL with Flask-SQLAlchemy and relational models | Backups, migrations, retention policy |
| **Telemetry & Metrics** | Device inventory and best-effort application-host snapshot | Authenticated endpoint agent and real-time metrics |
| **Diagnostics** | Placeholder scan entries saved as history | Actual OS/hardware tests and SMART diagnostics |
| **Security** | CSRF protection, secure cookie options, owner/admin checks | HTTPS deployment, rate limiting, security monitoring |
| **Alerting** | In-app Bootstrap toasts | Webhook alerts, PagerDuty/Slack/Email notification pipelines |
