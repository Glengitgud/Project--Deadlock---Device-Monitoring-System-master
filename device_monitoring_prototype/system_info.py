"""Best-effort inventory of the host running Flask, not remote client devices."""

import os
import platform
import logging
import shutil
import socket
import struct
from typing import Any

import psutil

logger = logging.getLogger(__name__)


def collect_hardware():
    memory_bytes = psutil.virtual_memory().total
    try:
        storage_bytes = shutil.disk_usage(os.path.expanduser("~")).total
    except OSError:
        storage_bytes = None

    return {
        "cpu_model": platform.processor() or platform.machine() or None,
        "cpu_cores": os.cpu_count(),
        "cpu_threads": os.cpu_count(),
        "memory_bytes": memory_bytes,
        "storage_bytes": storage_bytes,
        "gpu_model": None,
        "motherboard_model": None,
        "operating_system_version": platform.platform(),
    }


def collect_network():
    interfaces = psutil.net_if_addrs()
    interface_stats = psutil.net_if_stats()
    addresses: list[tuple[str, Any]] = []
    for interface_name, interface_addresses in interfaces.items():
        stats = interface_stats.get(interface_name)
        for address in interface_addresses:
            if (
                address.family == socket.AF_INET
                and not address.address.startswith("127.")
                and stats
                and stats.isup
            ):
                addresses.append((interface_name, address))
    selected: tuple[str, Any] | None = addresses[0] if addresses else None

    dns_server = None
    gateway = None
    if os.name == "nt" and selected:
        dns_server, gateway = _windows_network_settings(selected[1].address)
    elif os.path.exists("/etc/resolv.conf"):
        try:
            with open("/etc/resolv.conf", encoding="utf-8") as resolver_config:
                for line in resolver_config:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == "nameserver":
                        dns_server = parts[1]
                        break
        except OSError:
            logger.warning("Could not read the host DNS resolver configuration.")
        gateway = _linux_default_gateway()

    return {
        "ip_address": selected[1].address if selected else None,
        "subnet_mask": selected[1].netmask if selected else None,
        "default_gateway": gateway,
        "dns_server": dns_server,
        "connectivity_status": "connected" if selected else "disconnected",
    }


def _windows_network_settings(ip_address):
    import winreg

    registry_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
    except OSError:
        logger.warning("Could not read host network settings from the Windows registry.")
        return None, None

    with root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            try:
                interface_name = winreg.EnumKey(root, index)
                interface_key = winreg.OpenKey(root, interface_name)
            except OSError:
                continue
            with interface_key:
                ip_values = []
                for key in ("IPAddress", "DhcpIPAddress"):
                    try:
                        value = winreg.QueryValueEx(interface_key, key)[0]
                        ip_values.extend(value if isinstance(value, list) else [value])
                    except OSError:
                        continue
                if ip_address not in ip_values:
                    continue
                return (
                    _registry_first_value(
                        winreg, interface_key, ("NameServer", "DhcpNameServer")
                    ),
                    _registry_first_value(
                        winreg, interface_key, ("DefaultGateway", "DhcpDefaultGateway")
                    ),
                )
    logger.warning("No Windows adapter settings matched host IP %s.", ip_address)
    return None, None


def _registry_first_value(winreg, key, value_names):
    for value_name in value_names:
        try:
            value = winreg.QueryValueEx(key, value_name)[0]
        except OSError:
            continue
        if isinstance(value, (list, tuple)):
            value = next((item for item in value if item), None)
        if isinstance(value, str) and value.strip():
            return value.split()[0].split(",")[0]
    return None


def _linux_default_gateway():
    route_path = "/proc/net/route"
    try:
        with open(route_path, encoding="ascii") as routes:
            next(routes, None)
            for line in routes:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    return socket.inet_ntoa(struct.pack("<I", int(fields[2], 16)))
    except OSError:
        logger.warning("Could not read the host default gateway from %s.", route_path)
    return None
