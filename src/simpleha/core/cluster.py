"""Cluster Manager - Core orchestration for SimpleHA cluster.

Manages cluster state, coordinates nodes, and handles failover decisions.
Inspired by Pacemaker's crmd (Cluster Resource Management daemon).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field

from .quorum import QuorumManager, QuorumState

logger = logging.getLogger(__name__)


class NodeRole(str, Enum):
    """Cluster node roles."""

    ACTIVE = "active"
    PASSIVE = "passive"
    STANDBY = "standby"
    MAINTENANCE = "maintenance"


class NodeStatus(str, Enum):
    """Node health status."""

    ONLINE = "online"
    OFFLINE = "offline"
    FENCING = "fencing"
    UNKNOWN = "unknown"


@dataclass
class ClusterNode:
    """Represents a node in the HA cluster."""

    name: str
    address: str
    role: NodeRole = NodeRole.PASSIVE
    status: NodeStatus = NodeStatus.UNKNOWN
    priority: int = 1
    last_heartbeat: Optional[datetime] = None
    resources: Set[str] = field(default_factory=set)
    attributes: Dict[str, str] = field(default_factory=dict)


class ClusterConfig(BaseModel):
    """Cluster-level configuration."""

    name: str = Field(..., description="Cluster name")
    nodes: List[str] = Field(default_factory=list, description="Cluster node names")
    heartbeat_interval: float = Field(default=2.0, description="Heartbeat interval in seconds")
    heartbeat_timeout: float = Field(default=10.0, description="Heartbeat timeout in seconds")
    failover_timeout: float = Field(default=30.0, description="Failover timeout in seconds")
    stonith_enabled: bool = Field(default=True, description="Enable STONITH/fencing")
    quorum_required: bool = Field(default=True, description="Require quorum for operations")
    resource_stickiness: int = Field(default=100, description="Resource stickiness value")

    # Quorum settings
    expected_votes: int = Field(default=2, description="Expected votes (number of nodes)")
    votes_needed: int = Field(default=2, description="Votes needed for quorum")
    two_node_optimistic: bool = Field(default=False, description="Optimistic mode for 2-node clusters")
    arb_disk_enabled: bool = Field(default=False, description="Enable arbitration disk")
    arb_disk_device: str = Field(default="", description="Arbitration disk device path")
    arb_disk_type: str = Field(default="iscsi", description="Arbitration disk type (iscsi/fc/nfs)")
    arb_disk_timeout: float = Field(default=5.0, description="Disk operation timeout")
    arb_fence_delay: float = Field(default=0.0, description="Delay before fencing on quorum loss")


class ClusterManager:
    """Main cluster orchestrator.

    Coordinates all cluster operations including:
    - Node membership management
    - Resource allocation and failover
    - Health monitoring coordination
    - Fencing operations
    - Quorum and arbitration disk management
    """

    def __init__(self, config: ClusterConfig):
        self.config = config
        self.nodes: Dict[str, ClusterNode] = {}
        self._active_node: Optional[str] = None
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

        # Initialize quorum manager
        quorum_config = {
            "expected_votes": config.expected_votes,
            "votes_needed": config.votes_needed,
            "two_node_optimistic": config.two_node_optimistic,
            "arbitration_disk": {
                "enabled": config.arb_disk_enabled,
                "device_path": config.arb_disk_device,
                "device_type": config.arb_disk_type,
                "timeout": config.arb_disk_timeout,
                "fence_delay": config.arb_fence_delay,
            } if config.arb_disk_enabled else None,
        }
        self.quorum = QuorumManager(quorum_config)

        logger.info(f"Initialized ClusterManager for cluster: {config.name}")

    async def start(self) -> None:
        """Start the cluster manager."""
        self._running = True

        # Start quorum manager
        if self.config.quorum_required:
            await self.quorum.start()

        # Register all configured nodes with quorum
        for node_name in self.nodes:
            self.quorum.register_node(node_name)

        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Cluster {self.config.name} started")

    async def stop(self) -> None:
        """Stop the cluster manager."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Stop quorum manager
        if self.config.quorum_required:
            await self.quorum.stop()

        logger.info(f"Cluster {self.config.name} stopped")

    def add_node(self, name: str, address: str, priority: int = 1) -> None:
        """Add a node to the cluster."""
        if name in self.nodes:
            logger.warning(f"Node {name} already exists")
            return
        self.nodes[name] = ClusterNode(name=name, address=address, priority=priority)
        # Register node with quorum
        self.quorum.register_node(name)
        logger.info(f"Added node {name} at {address}")

    def remove_node(self, name: str) -> None:
        """Remove a node from the cluster."""
        if name in self.nodes:
            # Unregister node from quorum
            self.quorum.unregister_node(name)
            del self.nodes[name]
            logger.info(f"Removed node {name}")

    def get_active_node(self) -> Optional[ClusterNode]:
        """Get the currently active node."""
        if self._active_node:
            return self.nodes.get(self._active_node)
        return None

    def elect_active_node(self) -> Optional[ClusterNode]:
        """Elect the active node based on priority and status."""
        candidates = [
            n for n in self.nodes.values()
            if n.status == NodeStatus.ONLINE and n.role != NodeRole.STANDBY
        ]
        if not candidates:
            logger.warning("No eligible nodes for active role")
            self._active_node = None
            return None

        # Sort by priority (higher is better), then by name for stability
        candidates.sort(key=lambda n: (-n.priority, n.name))
        elected = candidates[0]
        self._active_node = elected.name
        elected.role = NodeRole.ACTIVE

        # Set others to passive
        for n in candidates[1:]:
            if n.role != NodeRole.STANDBY:
                n.role = NodeRole.PASSIVE

        logger.info(f"Elected active node: {elected.name}")
        return elected

    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                await self._check_cluster_health()
                await asyncio.sleep(self.config.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(self.config.heartbeat_interval)

    async def _check_cluster_health(self) -> None:
        """Check health of all cluster nodes."""
        # Update quorum with current node votes
        if self.config.quorum_required:
            online_nodes = [
                name for name, node in self.nodes.items()
                if node.status == NodeStatus.ONLINE
            ]
            for node_name in online_nodes:
                await self.quorum.record_vote(node_name, has_disk_access=True)

            # Check quorum state
            quorum_state = await self.quorum.check_quorum(online_nodes)

            # If quorum lost, trigger fencing for nodes without quorum
            if quorum_state == QuorumState.NO_QUORUM:
                logger.warning(f"Quorum lost! State: {quorum_state}")
                if self.config.stonith_enabled:
                    for node_name in self.nodes:
                        if node_name not in online_nodes:
                            await self.quorum.fence_if_no_quorum(node_name, online_nodes)

        active = self.get_active_node()
        if active and active.status != NodeStatus.ONLINE:
            logger.warning(f"Active node {active.name} is {active.status}, triggering failover")
            await self._trigger_failover()

    async def _trigger_failover(self) -> None:
        """Trigger failover to a healthy node."""
        # Check if we have quorum before allowing failover
        if self.config.quorum_required and not self.quorum.can_acquire_resources():
            logger.error("Cannot failover: no quorum")
            return

        new_active = self.elect_active_node()
        if new_active:
            logger.info(f"Failover complete: {new_active.name} is now active")
        else:
            logger.error("Failover failed: no healthy nodes available")

    def get_cluster_status(self) -> Dict:
        """Get current cluster status."""
        status = {
            "cluster_name": self.config.name,
            "active_node": self._active_node,
            "nodes": {
                name: {
                    "role": node.role.value,
                    "status": node.status.value,
                    "address": node.address,
                    "priority": node.priority,
                }
                for name, node in self.nodes.items()
            },
            "healthy_nodes": sum(
                1 for n in self.nodes.values() if n.status == NodeStatus.ONLINE
            ),
            "total_nodes": len(self.nodes),
        }

        # Add quorum status if enabled
        if self.config.quorum_required:
            quorum_status = self.quorum.get_status()
            status["quorum"] = {
                "enabled": True,
                "state": quorum_status["state"],
                "votes_present": quorum_status["votes_present"],
                "votes_needed": quorum_status["votes_needed"],
                "has_quorum": quorum_status["can_acquire_resources"],
                "arbitration_disk": quorum_status.get("arbitration_disk"),
            }

        return status

    def has_quorum(self) -> bool:
        """Check if cluster currently has quorum.

        Returns:
            True if cluster has quorum, False otherwise
        """
        if not self.config.quorum_required:
            return True
        return self.quorum.can_acquire_resources()
