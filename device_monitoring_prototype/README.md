# DevMonitor — Centralized Device Monitoring & Diagnostic System

DevMonitor is a production-ready application for centralized end-user device inventory, real-time telemetry streaming, diagnostic inspections, and fleet administration. Built with Flask, SQLAlchemy, MySQL, Bootstrap 5, and vanilla JavaScript.

## Quick Start on Windows

1. Copy `.env.example` to `.env` and set MySQL credentials or leave blank to use the SQLite development database.
2. Create and activate a Python 3.12+ environment and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Initialize the database and launch the application:
   ```powershell
   flask --app python.app init-db
   flask --app python.app create-admin
   python app.py
   ```
4. Open **http://127.0.0.1:5000** in your web browser.

---

## Production Deployment with Docker

Run the multi-container stack (Flask + Gunicorn, MySQL 8, and Nginx reverse proxy):

```bash
docker compose up -d --build
```

Access the system at **http://localhost**.

---

## Endpoint Telemetry Agent

To monitor remote client endpoints (Windows, Linux, macOS), run the lightweight agent:

```bash
# 1. Register the device with central server
python agent/devmonitor_agent.py --server http://127.0.0.1:5000 --register --username YOUR_USERNAME --password YOUR_PASSWORD --name "Office-PC-01"

# 2. Start streaming real-time telemetry
python agent/devmonitor_agent.py --server http://127.0.0.1:5000 --token YOUR_DEVICE_TOKEN --interval 5

# 3. Execute real diagnostic inspection
python agent/devmonitor_agent.py --server http://127.0.0.1:5000 --token YOUR_DEVICE_TOKEN --diagnose
```

---

## Core System Capabilities

- **Account Security & MFA:** RFC 6238 TOTP two-factor authentication, timed self-service password reset, 5-attempt brute-force lockout, and rate limiting.
- **Real-Time Telemetry (SSE):** Server-Sent Events push live CPU, RAM, disk, and network metrics to dashboard gauges and time-series charts without page reloads.
- **Automated Alerts:** Threshold-based triggers (CPU > 85%, Storage > 90%) dispatch notifications to the in-app navbar notification center.
- **Exportable Reporting:** One-click CSV exports for device fleet inventories and compliance audit trails.
- **Audit Logging:** Full audit coverage for all authentication (login, logout, lockout, reset) and administrative changes with an interactive Admin Panel viewer.
