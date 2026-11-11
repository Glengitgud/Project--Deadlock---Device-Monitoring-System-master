# DevMonitor — Device Monitoring Prototype

A dark minimal, responsive web prototype for a **Centralized End-User Device Monitoring & Diagnostic System**. Built with Flask, Bootstrap 5, and vanilla JavaScript for fleet visibility, telemetry simulation, and device administration.

---

## UI/UX Design System

The prototype implements a **dark minimal aesthetic** tailored for operations dashboards and system diagnostics:

| Swatch | Hex Code | Role in Design System |
|---|---|---|
| 🟣 Darkest | `#0d0221` | Canvas background, input surfaces, deep base |
| 🔵 Dark | `#0f084b` | Fixed sidebar navigation, sticky header, card headers |
| 🔷 Accent | `#26408b` | Primary buttons, active navigation, interactive glow |
| 🪟 Surface | `#120636` | Elevated cards, modal dialogs, data containers |
| ⚪ Text | `#f1f5f9` | High-contrast readable typography (WCAG AAA) |
| 🔘 Muted | `#94a3b8` | Subdued labels, metadata, captions |

### Design Highlights
- **Clean Authentication**: Removed simulated prototype notices and demo badges from the login page for an authentic, distraction-free interface.
- **Visual Ergonomics**: Deep purples and midnight blues reduce eye fatigue while maintaining clear component boundaries with subtle borders (`rgba(255, 255, 255, 0.08)`).
- **Responsive Navigation**: Collapsible sidebar with backdrop overlay on mobile and tablet displays ($\le 992\text{px}$).
- **Accessible Interactions**: High-contrast close buttons, smooth state transitions, and custom-styled form controls.

---

## Quick Start (Windows)

```bash
# 1. Navigate to the project folder
cd device_monitoring_prototype

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Command Prompt
# .venv\Scripts\Activate.ps1  # PowerShell

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize database and run the application
flask --app python.app init-db
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

> **Note:** If PowerShell restricts script execution, run:  
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

---

## Demo Accounts

| Role | Username | Password |
|---|---|---|
| Administrator | `admin` | `admin123` |
| Standard User | `user` | `user123` |

---

## Project Structure

```
device_monitoring_prototype/
│
├── app.py                      ← Flask application entry point
├── requirements.txt            ← Python dependencies (Flask)
├── features.md                 ← Features specification & UI/UX documentation
├── FEATURES_AND_FUTURE_WORK.md ← Simulated vs. production comparison
├── README.md                   ← Setup guide & system overview
│
├── templates/
│   ├── base.html               ← Master layout (sidebar, topbar, toast container)
│   ├── login.html              ← Clean minimal sign-in screen
│   ├── dashboard.html          ← Fleet overview & simulated telemetry
│   ├── devices.html            ← Device management, modal forms & scanner
│   └── admin.html              ← User management & access control
│
└── static/
    ├── css/
    │   └── style.css           ← Dark minimal design system stylesheet
    └── js/
        └── script.js           ← Client-side simulated data & event handlers
```

---

## Application Pages

| # | Page | Route | Description & Access |
|---|---|---|---|
| 1 | **Login** | `/` | Distraction-free authentication screen with password toggle |
| 2 | **Dashboard** | `/dashboard` | Metric counters, fleet table, dynamic resource utilization gauges |
| 3 | **My Devices** | `/devices` | CRUD interface, hardware diagnostic simulation, search & sort |
| 4 | **Admin Panel** | `/admin` | User management directory (Administrator role only) |

---

## Tech Stack

- **Backend**: Python 3, Flask
- **Frontend**: HTML5, CSS3 Custom Properties, Bootstrap 5.3
- **Icons**: Bootstrap Icons
- **State & Simulation**: Vanilla ES6 JavaScript, HTML5 `localStorage`

---

## Stopping the Server

Press `Ctrl + C` in your terminal window, then deactivate the environment:

```bash
deactivate
```
