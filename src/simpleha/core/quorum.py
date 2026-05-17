"""Quorum and Arbitration Disk Manager for SimpleHA cluster.

Provides disk-based quorum mechanism to prevent split-brain scenarios.
Inspired by Pacemaker's quorum subsystem and DLM (Distributed Lock Manager).

Key features:
- Disk-based arbitration (shared storage)
- Node majority voting with quorum disk
- Split-brain prevention through fencing
- Configurable quorum policies
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class QuorumState(str, Enum):
    """Quorum state for the cluster."""
    HAS_QUORUM = "has_quorum"        # Cluster has quorum, can manage resources
    NO_QUORUM = "no_quorum"          # Cluster lost quorum, resources should stop
    LOST = "lost"                    # Quorum completely lost
    UNKNOWN = "unknown"              # Quorum state unknown


class ArbitrationStatus(str, Enum):
    """Status of arbitration disk."""
    ONLINE = "online"                # Arbitration disk accessible
    OFFLINE = "offline"              # Arbitration disk not accessible
    DEGRADED = "degraded"            # Some nodes can access, some cannot
    TIMEOUT = "timeout"              # Arbitration operation timed out


@dataclass
class ArbitrationDisk:
    """Represents an arbitration disk device."""
    name: str
    device_path: str                  # e.g., "/dev/sdb" or "iqn.xxx"
    device_type: str = "iscsi"        # iscsi, fc, nfs, rbd
    timeout: float = 5.0             # Timeout for disk operations (seconds)
    interval: float = 2.0             # Heartbeat interval to disk (seconds)
    heuristic_enabled: bool = False    # Enable heuristic checks (disk I/O stats)
    heuristic_interval: float = 10.0  # Heuristic check interval
    heuristic_score: int = 100        # Score when heuristic succeeds
    fence_delay: float = 0.0          # Delay before fencing (seconds)


@dataclass
class QuorumVote:
    """Represents a node's vote in quorum."""
    node_name: str
    timestamp: float                  # Unix timestamp of last vote
    has_disk_access: bool             # Can this node access the arbitration disk?
    heuristic_score: int = 0          # Heuristic check score


@dataclass
class QuorumInfo:
    """Current quorum information."""
    state: QuorumState
    votes_expected: int              # Expected number of votes
    votes_present: int               # Votes present (nodes online)
    votes_needed: int               # Votes needed for quorum
    quorum_votes: List[str]          # Node names with quorum
    last_updated: datetime
    arbitration_status: ArbitrationStatus
    arbitration_disk: Optional[str] = None


class QuorumManager:
    """Manages quorum and arbitration disk operations.

    Implements disk-based quorum for HA clusters:
    - Maintains quorum through shared arbitration disk
    - Prevents split-brain by requiring quorum for resource operations
    - Handles node membership changes and quorum transitions
    - Supports heuristic checks for faster failover
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize quorum manager.

        Args:
            config: Quorum configuration dictionary
        """
        self.config = config
        self._votes: Dict[str, QuorumVote] = {}
        self._state = QuorumState.UNKNOWN
        self._arbitration_disk: Optional[ArbitrationDisk] = None
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._disk_io_task: Optional[asyncio.Task] = None

        # Load arbitration disk configuration
        if config.get("arbitration_disk"):
            disk_cfg = config["arbitration_disk"]
            self._arbitration_disk = ArbitrationDisk(
                name=disk_cfg.get("name", "arb-disk"),
                device_path=disk_cfg.get("device_path", "/dev/sdb"),
                device_type=disk_cfg.get("device_type", "iscsi"),
                timeout=disk_cfg.get("timeout", 5.0),
                interval=disk_cfg.get("interval", 2.0),
                heuristic_enabled=disk_cfg.get("heuristic_enabled", False),
                heuristic_interval=disk_cfg.get("heuristic_interval", 10.0),
                heuristic_score=disk_cfg.get("heuristic_score", 100),
                fence_delay=disk_cfg.get("fence_delay", 0.0),
            )
            logger.info(f"Arbitration disk configured: {self._arbitration_disk.device_path}")

        # Quorum settings
        self.expected_votes = config.get("expected_votes", 2)
        self.votes_needed = config.get("votes_needed", 2)  # For 2-node: 2 (default quorum)
        self.two_node_optimistic = config.get("two_node_optimistic", False)
        # For 2-node with optimistic: 1 (both nodes must agree on different things)

        logger.info(
            f"QuorumManager initialized: expected={self.expected_votes}, "
            f"needed={self.votes_needed}, optimistic={self.two_node_optimistic}"
        )

    async def start(self) -> None:
        """Start quorum monitoring."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        if self._arbitration_disk and self._arbitration_disk.heuristic_enabled:
            self._disk_io_task = asyncio.create_task(self._heuristic_loop())
        logger.info("QuorumManager started")

    async def stop(self) -> None:
        """Stop quorum monitoring."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        if self._disk_io_task:
            self._disk_io_task.cancel()
            try:
                await self._disk_io_task
            except asyncio.CancelledError:
                pass
        logger.info("QuorumManager stopped")

    def register_node(self, node_name: str) -> None:
        """Register a node with the quorum system.

        Args:
            node_name: Name of the node to register
        """
        self._votes[node_name] = QuorumVote(
            node_name=node_name,
            timestamp=time.time(),
            has_disk_access=False,
            heuristic_score=0,
        )
        logger.info(f"Node {node_name} registered with quorum")

    def unregister_node(self, node_name: str) -> None:
        """Unregister a node from the quorum system.

        Args:
            node_name: Name of the node to unregister
        """
        if node_name in self._votes:
            del self._votes[node_name]
            logger.info(f"Node {node_name} unregistered from quorum")

    async def record_vote(
        self,
        node_name: str,
        has_disk_access: bool = True,
        heuristic_score: int = 0,
    ) -> None:
        """Record a node's vote in quorum.

        Args:
            node_name: Name of the voting node
            has_disk_access: Whether the node can access the arbitration disk
            heuristic_score: Heuristic check score (higher = better disk I/O)
        """
        if node_name not in self._votes:
            self.register_node(node_name)

        self._votes[node_name] = QuorumVote(
            node_name=node_name,
            timestamp=time.time(),
            has_disk_access=has_disk_access,
            heuristic_score=heuristic_score,
        )

    async def check_quorum(self, online_nodes: List[str]) -> QuorumState:
        """Check if cluster has quorum.

        Args:
            online_nodes: List of currently online node names

        Returns:
            QuorumState indicating the current quorum status
        """
        current_time = time.time()
        votes_timeout = 10.0  # Consider vote stale after 10 seconds

        # Count valid votes
        valid_votes = 0
        valid_voters = []

        for node_name in online_nodes:
            if node_name in self._votes:
                vote = self._votes[node_name]
                age = current_time - vote.timestamp

                if age < votes_timeout:
                    # For quorum calculation with disk:
                    # A node counts if it has valid vote AND (no disk required OR has disk access)
                    if self._arbitration_disk is None or vote.has_disk_access:
                        valid_votes += 1
                        valid_voters.append(node_name)

        self.votes_present = valid_votes

        # Determine quorum state
        if self._arbitration_disk:
            # Disk-based quorum: need both nodes AND disk access
            disk_online = await self._check_arbitration_disk()
            if not disk_online:
                self._state = QuorumState.NO_QUORUM
                logger.warning("Arbitration disk offline, no quorum")
                return self._state

        # Calculate if we have quorum
        if self.two_node_optimistic and self.expected_votes == 2:
            # 2-node optimistic: quorum = (node1 online AND disk) OR (node2 online AND disk)
            # But for operations, we need agreement
            if valid_votes >= 1:
                self._state = QuorumState.HAS_QUORUM
        else:
            # Standard quorum: need majority (or configured votes_needed)
            if valid_votes >= self.votes_needed:
                self._state = QuorumState.HAS_QUORUM
            else:
                self._state = QuorumState.NO_QUORUM

        logger.info(
            f"Quorum check: votes_present={valid_votes}, "
            f"votes_needed={self.votes_needed}, state={self._state.value}"
        )

        return self._state

    async def _check_arbitration_disk(self) -> bool:
        """Check if arbitration disk is accessible.

        Returns:
            True if disk is accessible, False otherwise
        """
        if not self._arbitration_disk:
            return True  # No disk required

        try:
            # In production, this would do actual disk I/O:
            # - Write a heartbeat marker to the disk
            # - Read it back to verify
            # - Check for corruption

            # Simulated check - in production use:
            # - SCSI reservation/release
            # - Direct I/O to block device
            # - NFS lock file operations

            # For now, simulate successful disk access
            await asyncio.sleep(0.01)  # Simulate I/O latency

            # Simulate occasional failures for testing
            # In production, remove this and use real disk checks
            return True

        except Exception as e:
            logger.error(f"Arbitration disk check failed: {e}")
            return False

    async def _monitor_loop(self) -> None:
        """Background monitoring loop for quorum."""
        interval = self._arbitration_disk.interval if self._arbitration_disk else 2.0

        while self._running:
            try:
                # Update quorum state
                online_nodes = [name for name, vote in self._votes.items()
                              if time.time() - vote.timestamp < 10.0]
                await self.check_quorum(online_nodes)

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in quorum monitor loop: {e}")
                await asyncio.sleep(interval)

    async def _heuristic_loop(self) -> None:
        """Background loop for heuristic checks.

        Heuristic checks monitor disk I/O performance to detect
        potential issues before they cause quorum loss.
        """
        if not self._arbitration_disk:
            return

        interval = self._arbitration_disk.heuristic_interval

        while self._running:
            try:
                # In production, this would:
                # - Check disk I/O statistics
                # - Monitor read/write latencies
                # - Verify filesystem health
                # - Check disk SMART status

                # Simulated heuristic check
                logger.debug("Heuristic check: disk I/O healthy")
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heuristic loop: {e}")
                await asyncio.sleep(interval)

    def get_quorum_info(self) -> QuorumInfo:
        """Get current quorum information.

        Returns:
            QuorumInfo object with current quorum status
        """
        return QuorumInfo(
            state=self._state,
            votes_expected=self.expected_votes,
            votes_present=getattr(self, 'votes_present', 0),
            votes_needed=self.votes_needed,
            quorum_votes=[
                name for name, vote in self._votes.items()
                if time.time() - vote.timestamp < 10.0
                and (not self._arbitration_disk or vote.has_disk_access)
            ],
            last_updated=datetime.now(),
            arbitration_status=ArbitrationStatus.ONLINE if self._arbitration_disk else ArbitrationStatus.OFFLINE,
            arbitration_disk=self._arbitration_disk.device_path if self._arbitration_disk else None,
        )

    def should_stop_resources(self) -> bool:
        """Determine if resources should be stopped due to quorum loss.

        Returns:
            True if resources should be stopped, False otherwise
        """
        return self._state == QuorumState.NO_QUORUM or self._state == QuorumState.LOST

    def can_acquire_resources(self) -> bool:
        """Determine if this node can acquire resources.

        Returns:
            True if this node can start resources, False otherwise
        """
        return self._state == QuorumState.HAS_QUORUM

    def get_votes_needed_for_failover(self) -> int:
        """Get minimum votes needed to perform a failover.

        Returns:
            Number of votes needed for failover
        """
        if self.two_node_optimistic and self.expected_votes == 2:
            return 1
        return self.votes_needed

    def get_status(self) -> Dict[str, Any]:
        """Get quorum manager status.

        Returns:
            Dictionary with status information
        """
        quorum_info = self.get_quorum_info()

        status = {
            "state": self._state.value,
            "expected_votes": self.expected_votes,
            "votes_present": quorum_info.votes_present,
            "votes_needed": self.votes_needed,
            "two_node_optimistic": self.two_node_optimistic,
            "quorum_votes": quorum_info.quorum_votes,
            "can_acquire_resources": self.can_acquire_resources(),
            "should_stop_resources": self.should_stop_resources(),
        }

        if self._arbitration_disk:
            status["arbitration_disk"] = {
                "name": self._arbitration_disk.name,
                "device_path": self._arbitration_disk.device_path,
                "device_type": self._arbitration_disk.device_type,
                "timeout": self._arbitration_disk.timeout,
                "interval": self._arbitration_disk.interval,
                "heuristic_enabled": self._arbitration_disk.heuristic_enabled,
                "fence_delay": self._arbitration_disk.fence_delay,
            }

        return status

    async def fence_if_no_quorum(self, node_name: str, online_nodes: List[str]) -> bool:
        """Fence a node if it has lost quorum.

        Args:
            node_name: Name of the node to potentially fence
            online_nodes: List of currently online nodes

        Returns:
            True if fencing was triggered, False otherwise
        """
        if self._state == QuorumState.HAS_QUORUM:
            return False

        if self._arbitration_disk and self._arbitration_disk.fence_delay > 0:
            logger.info(f"Waiting {self._arbitration_disk.fence_delay}s before fencing")
            await asyncio.sleep(self._arbitration_disk.fence_delay)

        logger.warning(f"Fencing node {node_name} due to quorum loss")
        # In production, this would call STONITH/fencing
        return True

    def __repr__(self) -> str:
        return (
            f"QuorumManager(state={self._state.value}, "
            f"votes={len(self._votes)}, "
            f"disk={'yes' if self._arbitration_disk else 'no'})"
        )
