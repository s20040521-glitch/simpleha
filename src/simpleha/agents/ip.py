"""IP Address Resource Agent for SimpleHA.

Manages virtual/floating IP addresses in a HA cluster.
On failover, the IP is migrated (moved) to the new active node.

Similar to Pacemaker's ocf:heartbeat:IPaddr2 resource agent.
"""

import asyncio
import logging
import subprocess
import sys

from simpleha.agents.base import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class IPAgent(BaseAgent):
    """Manages a floating IP address for HA failover.

    On Linux: uses ip addr add/delete
    On Windows: uses netsh interface ip add/del
    """

    name = "ip"
    version = "1.0.0"
    description = "Floating IP address resource agent"

    async def start(self, params: dict) -> dict:
        """Add the IP address to the interface.

        Args:
            params: {
                "ip": "192.168.1.100",
                "netmask": "24",
                "interface": "eth0",  # optional, auto-detect if missing
            }
        """
        ip = params.get("ip")
        netmask = params.get("netmask", "24")
        interface = params.get("interface", "")

        if not ip:
            return self._fail("Missing required parameter: ip")

        interface = interface or self._detect_interface()
        if not interface:
            return self._fail("Could not detect network interface")

        try:
            if sys.platform.startswith("linux"):
                cmd = ["ip", "addr", "add", f"{ip}/{netmask}", "dev", interface]
                result = await self._run_cmd(cmd)
                if result["returncode"] != 0:
                    return self._fail(f"Failed to add IP: {result['stderr']}")
            elif sys.platform.startswith("win"):
                cmd = [
                    "netsh", "interface", "ip", "add", "address",
                    interface, ip, self._netmask_to_ip(netmask),
                ]
                result = await self._run_cmd(cmd, shell=True)
                if result["returncode"] != 0:
                    return self._fail(f"Failed to add IP: {result['stderr']}")
            else:
                return self._fail(f"Unsupported platform: {sys.platform}")

            logger.info(f"IP {ip}/{netmask} added to {interface}")
            return self._success(f"IP {ip} added to {interface}", interface=interface)

        except Exception as e:
            return self._fail(f"Exception starting IP resource: {e}")

    async def stop(self, params: dict) -> dict:
        """Remove the IP address from the interface."""
        ip = params.get("ip")
        netmask = params.get("netmask", "24")
        interface = params.get("interface", "")

        if not ip:
            return self._fail("Missing required parameter: ip")

        interface = interface or self._detect_interface()
        if not interface:
            return self._fail("Could not detect network interface")

        try:
            if sys.platform.startswith("linux"):
                cmd = ["ip", "addr", "del", f"{ip}/{netmask}", "dev", interface]
                result = await self._run_cmd(cmd)
                # Ignore errors (IP might not exist)
            elif sys.platform.startswith("win"):
                cmd = [
                    "netsh", "interface", "ip", "delete", "address",
                    interface, ip,
                ]
                result = await self._run_cmd(cmd, shell=True)

            logger.info(f"IP {ip}/{netmask} removed from {interface}")
            return self._success(f"IP {ip} removed from {interface}")

        except Exception as e:
            return self._fail(f"Exception stopping IP resource: {e}")

    async def monitor(self, params: dict) -> dict:
        """Check if the IP address is present on the interface."""
        ip = params.get("ip")
        interface = params.get("interface", "")

        if not ip:
            return self._fail("Missing required parameter: ip")

        interface = interface or self._detect_interface()

        try:
            if sys.platform.startswith("linux"):
                cmd = ["ip", "addr", "show", interface]
                result = await self._run_cmd(cmd)
                running = ip in result["stdout"]
            elif sys.platform.startswith("win"):
                cmd = ["netsh", "interface", "ip", "show", "address", interface]
                result = await self._run_cmd(cmd, shell=True)
                running = ip in result["stdout"]
            else:
                return self._running(False, f"Unsupported platform: {sys.platform}")

            if running:
                return self._running(True, f"IP {ip} is configured on {interface}")
            else:
                return self._running(False, f"IP {ip} not found on {interface}")

        except Exception as e:
            return self._fail(f"Exception monitoring IP resource: {e}")

    def _detect_interface(self) -> str:
        """Auto-detect the default network interface."""
        try:
            if sys.platform.startswith("linux"):
                result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if "dev" in line:
                        parts = line.split("dev")
                        if len(parts) > 1:
                            return parts[1].split()[0]
            elif sys.platform.startswith("win"):
                result = subprocess.run(
                    ["netsh", "interface", "ip", "show", "address"],
                    capture_output=True, text=True, timeout=5, shell=True,
                )
                # Return first non-loopback interface
                for line in result.stdout.splitlines():
                    if "Ethernet" in line or "Wi-Fi" in line:
                        return line.split('"')[1] if '"' in line else line.strip()
        except Exception:
            pass
        return ""

    def _netmask_to_ip(self, cidr: str) -> str:
        """Convert CIDR netmask to dotted format."""
        try:
            bits = int(cidr)
            mask = (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF
            return f"{mask >> 24}.{(mask >> 16) & 255}.{(mask >> 8) & 255}.{mask & 255}"
        except Exception:
            return "255.255.255.0"

    async def _run_cmd(self, cmd: list, shell: bool = False) -> dict:
        """Run a shell command asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="ignore") if stdout else "",
            "stderr": stderr.decode("utf-8", errors="ignore") if stderr else "",
        }
