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

### 1. Authentication & Role-Based Access (Client-Simulated)
- **Login Experience**: Streamlined username and password interface with a password visibility toggle (`bi-eye` / `bi-eye-slash`) and inline error alerts.
- **Role Awareness**: Differentiates between Administrator and Standard User accounts, adapting navigation items accordingly (e.g., Administrator panel is exclusively exposed to admin roles).

### 2. Monitoring Dashboard
- **Metric Cards**: Real-time summary cards displaying Total Devices, Online count, Offline count, and Latest Update timestamp.
- **Fleet Overview**: Tabular view of registered machines with assigned users, operating systems, hardware specifications, and live status badges.
- **Resource Monitor**: Animated CPU, RAM, and Storage utilization gauges with dynamic threshold-based color coding (green $< 50\%$, yellow $50\text{--}79\%$, red $\ge 80\%$).

### 3. Device Management (CRUD)
- **Device Registration**: Modal dialog to add devices with name, machine type, OS, CPU, RAM, storage configuration, and user assignment.
- **Device Inspection & Editing**: View detailed hardware specifications in read-only mode or modify properties in edit mode.
- **Simulated Diagnostic Scan**: Interactive diagnostic process with an animated multi-step progress bar reporting simulated BIOS versions, MAC addresses, and hardware serial numbers.
- **Device Deletion**: Confirmation dialog preventing accidental removal of device records.
- **Search, Sorting & Pagination**: Real-time filtering by device name, multi-attribute sorting, and paginated table navigation.

### 4. Admin Panel (User Management)
- **User Directory**: View simulated organizational accounts with usernames, email addresses, assigned roles, and activity statuses.
- **User CRUD Operations**: Register new accounts, update profiles, toggle active/inactive statuses, or delete users with full validation.
- **Search & Sort**: Filter by name or username with instant pagination.

---

## Simulated vs. Future Production Roadmap

| Feature Area | Current Prototype (Simulated) | Production Target (Future Development) |
|---|---|---|
| **Authentication** | Client-side credential verification in `localStorage` | Server-side JWT/OAuth2 authentication, bcrypt hashing, session cookies, MFA |
| **Data Persistence** | Browser `localStorage` | PostgreSQL / MySQL with SQLAlchemy ORM and relational models |
| **Telemetry & Metrics** | Client-side timer with randomized percentage fluctuations | Lightweight OS daemon/agent (WMI, SNMP, eBPF) streaming over WebSockets |
| **Diagnostics** | Simulated hardware scan steps with preset outputs | Low-level OS hardware inspection and SMART disk diagnostic tools |
| **Security** | Frontend role gating | Role-Based Access Control (RBAC) enforced on REST API endpoints |
| **Alerting** | In-app Bootstrap toasts | Webhook alerts, PagerDuty/Slack/Email notification pipelines |
