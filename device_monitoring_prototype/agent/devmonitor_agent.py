"""DevMonitor Endpoint Telemetry & Diagnostic Agent.

Lightweight, multi-platform agent for Windows, Linux, and macOS.
Collects real hardware telemetry, resource metrics (CPU, RAM, storage, network),
and diagnostic health checks, streaming them to the DevMonitor central server.

Usage:
    # 1. Register endpoint machine:
    python devmonitor_agent.py --server http://127.0.0.1:5000 --register --username admin --password adminpassword123 --name "Workstation-Alpha"

    # 2. Run telemetry loop (daemon):
    python devmonitor_agent.py --server http://127.0.0.1:5000 --token YOUR_DEVICE_TOKEN --interval 5

    # 3. Run real diagnostic scan and upload:
    python devmonitor_agent.py --server http://127.0.0.1:5000 --token YOUR_DEVICE_TOKEN --diagnose
"""

import argparse
import json
import logging
import os
import platform
import shutil
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import psutil
except ImportError:
    psutil = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("DevMonitorAgent")


class DevMonitorAgent:
    def __init__(self, server_url, token=None):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self._last_net_bytes = None

    def _http_post(self, path, payload, token=None):
        url = f"{self.server_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "DevMonitor-Agent/1.0",
        }
        active_token = token or self.token
        if active_token:
            headers["X-Device-Token"] = active_token
            headers["X-Agent-Token"] = active_token

        req = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=15) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            logger.error("HTTP %s on %s: %s", exc.code, path, err_body)
            raise RuntimeError(f"Server error ({exc.code}): {err_body}") from exc
        except URLError as exc:
            logger.error("Failed to connect to %s: %s", url, exc.reason)
            raise RuntimeError(f"Connection failed: {exc.reason}") from exc

    def collect_system_specs(self, custom_name=None, device_type=None):
        """Gather real host hardware specification and network details."""
        if not psutil:
            raise RuntimeError("psutil is required to run the DevMonitor agent.")

        hostname = socket.gethostname()
        mem = psutil.virtual_memory()
        disk = shutil.disk_usage(os.path.expanduser("~"))

        # Detect primary network interface
        net_info = {
            "ip_address": "127.0.0.1",
            "subnet_mask": "255.255.255.0",
            "default_gateway": None,
            "dns_server": None,
            "connectivity_status": "connected",
        }
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    net_info["ip_address"] = addr.address
                    net_info["subnet_mask"] = addr.netmask
                    break
            if net_info["ip_address"] != "127.0.0.1":
                break

        return {
            "name": custom_name or hostname,
            "hostname": hostname,
            "type": device_type or ("Laptop" if psutil.sensors_battery() else "Desktop"),
            "os": f"{platform.system()} {platform.release()}",
            "hardware": {
                "cpu_model": platform.processor() or platform.machine(),
                "cpu_cores": psutil.cpu_count(logical=False) or os.cpu_count(),
                "cpu_threads": psutil.cpu_count(logical=True) or os.cpu_count(),
                "memory_bytes": mem.total,
                "storage_bytes": disk.total,
                "operating_system_version": platform.platform(),
            },
            "network": net_info,
        }

    def register(self, username, password, custom_name=None, device_type=None):
        """Enroll this machine with the DevMonitor central server."""
        specs = self.collect_system_specs(custom_name, device_type)
        payload = {
            **specs,
            "username": username,
            "password": password,
        }
        logger.info("Registering endpoint '%s' with server %s...", specs["name"], self.server_url)
        res = self._http_post("/api/agent/register", payload)
        self.token = res.get("token")
        logger.info("Successfully registered! Assigned Device ID: %s", res.get("device_id"))
        logger.info("Device API Token: %s", self.token)
        return res

    def collect_live_metrics(self):
        """Collect instantaneous CPU, memory, storage, and network utilization."""
        if not psutil:
            raise RuntimeError("psutil is required.")

        cpu_pct = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = shutil.disk_usage(os.path.expanduser("~"))
        net = psutil.net_io_counters()

        # Compute delta rate if previous sample exists
        storage_pct = round((disk.used / disk.total) * 100, 2) if disk.total else 0.0

        return {
            "cpu_percent": round(cpu_pct, 2),
            "memory_percent": round(mem.percent, 2),
            "storage_percent": storage_pct,
            "memory_used_bytes": mem.used,
            "storage_used_bytes": disk.used,
            "network_rx_bytes": net.bytes_recv,
            "network_tx_bytes": net.bytes_sent,
        }

    def send_metrics(self):
        """Send a single telemetry heartbeat to the central server."""
        metrics = self.collect_live_metrics()
        self._http_post("/api/agent/metrics", metrics)
        logger.info(
            "Telemetry reported -> CPU: %.1f%% | RAM: %.1f%% | Disk: %.1f%%",
            metrics["cpu_percent"],
            metrics["memory_percent"],
            metrics["storage_percent"],
        )

    def run_diagnostics(self):
        """Execute real system health inspection checks."""
        logger.info("Running real hardware & network diagnostic checks...")
        checks = []

        # 1. CPU Load & Stress Check
        cpu_load = psutil.cpu_percent(interval=1.0)
        cpu_status = "passed" if cpu_load < 80 else ("warning" if cpu_load < 92 else "failed")
        checks.append({
            "check_name": "Processor Utilization & Capacity",
            "category": "processor",
            "status": cpu_status,
            "result_summary": f"Current system CPU load is {cpu_load}%.",
            "details": {"load_percent": cpu_load, "cores": psutil.cpu_count()},
        })

        # 2. Physical Memory Health Check
        mem = psutil.virtual_memory()
        mem_status = "passed" if mem.percent < 85 else ("warning" if mem.percent < 95 else "failed")
        checks.append({
            "check_name": "Physical RAM Allocation & Pressure",
            "category": "memory",
            "status": mem_status,
            "result_summary": f"RAM usage is {mem.percent}% ({mem.used // (1024**3)} GB used of {mem.total // (1024**3)} GB).",
            "details": {"percent": mem.percent, "total_gb": mem.total // (1024**3)},
        })

        # 3. Disk Storage Capacity Check
        disk = shutil.disk_usage(os.path.expanduser("~"))
        disk_pct = round((disk.used / disk.total) * 100, 1)
        disk_status = "passed" if disk_pct < 85 else ("warning" if disk_pct < 95 else "failed")
        checks.append({
            "check_name": "Primary Storage Available Capacity",
            "category": "storage",
            "status": disk_status,
            "result_summary": f"Primary drive is at {disk_pct}% capacity ({disk.free // (1024**3)} GB free).",
            "details": {"percent": disk_pct, "free_gb": disk.free // (1024**3)},
        })

        # 4. Network Socket Connectivity Check
        net_status = "passed"
        ping_latency_ms = None
        try:
            start_t = time.time()
            sock = socket.create_connection(("1.1.1.1", 53), timeout=3.0)
            ping_latency_ms = round((time.time() - start_t) * 1000, 1)
            sock.close()
        except OSError:
            net_status = "warning"

        checks.append({
            "check_name": "External Gateway Connectivity",
            "category": "network",
            "status": net_status,
            "result_summary": f"Gateway reachable (DNS ping: {ping_latency_ms} ms)." if ping_latency_ms else "External gateway unreachable.",
            "details": {"ping_latency_ms": ping_latency_ms},
        })

        res = self._http_post("/api/agent/diagnostics", {"checks": checks})
        logger.info("Diagnostic completed and uploaded to server: Run #%s", res.get("run_id"))
        return checks

    def run_loop(self, interval_seconds=5):
        """Continuously stream live telemetry at the designated interval."""
        logger.info("Starting telemetry loop (interval: %ss). Press Ctrl+C to terminate.", interval_seconds)
        while True:
            try:
                self.send_metrics()
            except Exception as exc:
                logger.warning("Telemetry transmission error: %s", exc)
            time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="DevMonitor Endpoint Agent")
    parser.add_argument("--server", default="http://127.0.0.1:5000", help="DevMonitor server base URL")
    parser.add_argument("--token", help="Registered device API token")
    parser.add_argument("--register", action="store_true", help="Register this endpoint with the server")
    parser.add_argument("--username", help="User credentials for registration")
    parser.add_argument("--password", help="Password credentials for registration")
    parser.add_argument("--name", help="Custom device name for registration")
    parser.add_argument("--type", choices=["Desktop", "Laptop", "Server", "Workstation", "Other"], help="Device form factor")
    parser.add_argument("--interval", type=int, default=5, help="Telemetry reporting interval in seconds")
    parser.add_argument("--once", action="store_true", help="Send a single telemetry heartbeat and exit")
    parser.add_argument("--diagnose", action="store_true", help="Run full diagnostic scan and upload")

    args = parser.parse_args()

    agent = DevMonitorAgent(args.server, token=args.token)

    if args.register:
        if not args.username or not args.password:
            logger.error("Registration requires --username and --password.")
            sys.exit(1)
        agent.register(args.username, args.password, custom_name=args.name, device_type=args.type)
        if not args.diagnose and not args.once:
            sys.exit(0)

    if not agent.token:
        logger.error("A device token is required. Pass --token <TOKEN> or register with --register.")
        sys.exit(1)

    if args.diagnose:
        agent.run_diagnostics()

    if args.once:
        agent.send_metrics()
    elif not args.diagnose or args.interval:
        agent.run_loop(args.interval)


if __name__ == "__main__":
    main()
