"""Filesystem Resource Agent for SimpleHA.

Manages mount/unmount of filesystems in a HA cluster.
On failover, the filesystem is unmounted from the failed node
and mounted on the new active node.

Similar to Pacemaker's ocf:heartbeat:Filesystem resource agent.
"""

import asyncio
import logging
import sys
from pathlib import Path

from simpleha.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class FilesystemAgent(BaseAgent):
    """Manages a filesystem mount for HA failover.

    Supports:
    - Linux: mount/umount with various filesystem types
    - Windows: mountvol/diskshadow for volume mount
    """

    name = "filesystem"
    version = "1.0.0"
    description = "Filesystem mount resource agent"

    async def start(self, params: dict) -> dict:
        """Mount the filesystem.

        Args:
            params: {
                "device": "/dev/sdb1",
                "directory": "/mnt/data",
                "fstype": "ext4",       # optional, auto-detect
                "options": "defaults",    # optional mount options
            }
        """
        device = params.get("device")
        directory = params.get("directory")
        fstype = params.get("fstype", "")
        options = params.get("options", "")

        if not device or not directory:
            return self._fail("Missing required parameters: device and directory")

        # Ensure mount point exists
        Path(directory).mkdir(parents=True, exist_ok=True)

        try:
            if sys.platform.startswith("linux"):
                cmd = ["mount"]
                if fstype:
                    cmd.extend(["-t", fstype])
                if options:
                    cmd.extend(["-o", options])
                cmd.extend([device, directory])

                result = await self._run_cmd(cmd, timeout=30)
                if result["returncode"] != 0:
                    return self._fail(
                        f"Failed to mount {device}: {result['stderr']}"
                    )

            elif sys.platform.startswith("win"):
                # Windows: use mountvol to assign drive letter
                drive_letter = params.get("drive_letter", directory[:2])
                cmd = ["mountvol", drive_letter, device]
                result = await self._run_cmd(cmd, shell=True, timeout=30)
                if result["returncode"] != 0:
                    return self._fail(
                        f"Failed to mount {device}: {result['stderr']}"
                    )
            else:
                return self._fail(f"Unsupported platform: {sys.platform}")

            logger.info(f"Filesystem {device} mounted at {directory}")
            return self._success(
                f"Filesystem {device} mounted at {directory}",
                device=device,
                directory=directory,
            )

        except asyncio.TimeoutError:
            return self._fail(f"Timeout mounting filesystem {device}")
        except Exception as e:
            return self._fail(f"Exception mounting filesystem: {e}")

    async def stop(self, params: dict) -> dict:
        """Unmount the filesystem."""
        directory = params.get("directory")
        device = params.get("device", "")

        if not directory:
            return self._fail("Missing required parameter: directory")

        try:
            if sys.platform.startswith("linux"):
                cmd = ["umount", directory]
                result = await self._run_cmd(cmd, timeout=30)
                # Force unmount if normal unmount fails
                if result["returncode"] != 0:
                    logger.warning(f"Normal unmount failed, trying lazy unmount")
                    result = await self._run_cmd(
                        ["umount", "-l", directory], timeout=30
                    )
                logger.info(f"Filesystem at {directory} unmounted")

            elif sys.platform.startswith("win"):
                drive_letter = params.get("drive_letter", directory[:2])
                cmd = ["mountvol", drive_letter, "/d"]
                result = await self._run_cmd(cmd, shell=True, timeout=30)
                logger.info(f"Filesystem {drive_letter} unmounted")

            else:
                return self._fail(f"Unsupported platform: {sys.platform}")

            return self._success(f"Filesystem at {directory} unmounted")

        except Exception as e:
            return self._fail(f"Exception unmounting filesystem: {e}")

    async def monitor(self, params: dict) -> dict:
        """Check if the filesystem is mounted."""
        directory = params.get("directory")
        device = params.get("device", "")

        if not directory:
            return self._fail("Missing required parameter: directory")

        try:
            if sys.platform.startswith("linux"):
                result = await self._run_cmd(["mount"], timeout=5)
                mounted = directory in result["stdout"]
                # Also check if device is mounted at directory
                if device:
                    mounted = f"{device} on {directory}" in result["stdout"]

            elif sys.platform.startswith("win"):
                drive_letter = params.get("drive_letter", directory[:2])
                result = await self._run_cmd(
                    ["mountvol", drive_letter], shell=True, timeout=5
                )
                mounted = "is mounted" in result["stdout"].lower()
            else:
                return self._running(False, f"Unsupported platform: {sys.platform}")

            if mounted:
                return self._running(
                    True, f"Filesystem at {directory} is mounted"
                )
            else:
                return self._running(
                    False, f"Filesystem at {directory} is not mounted"
                )

        except Exception as e:
            return self._fail(f"Exception monitoring filesystem: {e}")

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
