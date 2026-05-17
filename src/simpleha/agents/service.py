"""Service Resource Agent for SimpleHA.

Manages system services (systemd on Linux, Windows Service, etc.).
On failover, the service is stopped on the failed node and started on the new active node.

Similar to Pacemaker's ocf:heartbeat:anything or systemd agents.
"""

import asyncio
import logging
import sys

from simpleha.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class ServiceAgent(BaseAgent):
    """Manages a system service for HA failover.

    Supports:
    - Linux: systemd services (systemctl)
    - Windows: Windows services (sc.exe)
    """

    name = "service"
    version = "1.0.0"
    description = "System service resource agent"

    async def start(self, params: dict) -> dict:
        """Start the service.

        Args:
            params: {
                "service_name": "nginx",
                "start_timeout": 30,   # optional
                "stop_timeout": 30,    # optional
            }
        """
        service_name = params.get("service_name")
        if not service_name:
            return self._fail("Missing required parameter: service_name")

        timeout = params.get("start_timeout", 30)

        try:
            if sys.platform.startswith("linux"):
                result = await self._run_cmd(
                    ["systemctl", "start", service_name], timeout=timeout
                )
                if result["returncode"] != 0:
                    return self._fail(
                        f"Failed to start service {service_name}: {result['stderr']}"
                    )
                # Wait for service to be active
                await asyncio.sleep(1)
                check = await self._run_cmd(
                    ["systemctl", "is-active", service_name]
                )
                if "active" not in check["stdout"]:
                    return self._fail(
                        f"Service {service_name} started but not active"
                    )

            elif sys.platform.startswith("win"):
                result = await self._run_cmd(
                    ["sc", "start", service_name], shell=True, timeout=timeout
                )
                if result["returncode"] != 0:
                    return self._fail(
                        f"Failed to start service {service_name}: {result['stderr']}"
                    )
            else:
                return self._fail(f"Unsupported platform: {sys.platform}")

            logger.info(f"Service {service_name} started")
            return self._success(f"Service {service_name} started")

        except asyncio.TimeoutError:
            return self._fail(f"Timeout starting service {service_name}")
        except Exception as e:
            return self._fail(f"Exception starting service: {e}")

    async def stop(self, params: dict) -> dict:
        """Stop the service."""
        service_name = params.get("service_name")
        if not service_name:
            return self._fail("Missing required parameter: service_name")

        timeout = params.get("stop_timeout", 30)

        try:
            if sys.platform.startswith("linux"):
                result = await self._run_cmd(
                    ["systemctl", "stop", service_name], timeout=timeout
                )
                # Don't fail on stop - service might already be stopped
                logger.info(f"Service {service_name} stopped")

            elif sys.platform.startswith("win"):
                result = await self._run_cmd(
                    ["sc", "stop", service_name], shell=True, timeout=timeout
                )
                logger.info(f"Service {service_name} stopped")
            else:
                return self._fail(f"Unsupported platform: {sys.platform}")

            return self._success(f"Service {service_name} stopped")

        except Exception as e:
            return self._fail(f"Exception stopping service: {e}")

    async def monitor(self, params: dict) -> dict:
        """Check if the service is running."""
        service_name = params.get("service_name")
        if not service_name:
            return self._fail("Missing required parameter: service_name")

        try:
            if sys.platform.startswith("linux"):
                result = await self._run_cmd(
                    ["systemctl", "is-active", service_name], timeout=5
                )
                running = result["returncode"] == 0 and "active" in result["stdout"]

            elif sys.platform.startswith("win"):
                result = await self._run_cmd(
                    ["sc", "query", service_name], shell=True, timeout=5
                )
                running = "RUNNING" in result["stdout"]
            else:
                return self._running(False, f"Unsupported platform: {sys.platform}")

            if running:
                return self._running(True, f"Service {service_name} is running")
            else:
                return self._running(False, f"Service {service_name} is not running")

        except Exception as e:
            return self._fail(f"Exception monitoring service: {e}")

    async def _run_cmd(self, cmd: list, shell: bool = False, timeout: float = 30) -> dict:
        """Run a shell command asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="ignore") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="ignore") if stderr else "",
            }
        except asyncio.TimeoutError:
            proc.kill()
            raise
