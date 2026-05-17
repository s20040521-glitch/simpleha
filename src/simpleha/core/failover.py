"""Failover management for SimpleHA cluster.

Handles automatic failover when active node fails.
Inspired by Pacemaker's failover and fencing mechanisms.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FailoverReason(str, Enum):
    """Reasons for failover."""

    NODE_FAILURE = "node_failure"
    RESOURCE_FAILURE = "resource_failure"
    MANUAL = "manual"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    STONITH = "stonith"
    QUORUM_LOST = "quorum_lost"  # New: quorum lost trigger


class FailoverStatus(str, Enum):
    """Failover operation status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class FailoverEvent:
    """Record of a failover event."""

    id: str
    timestamp: datetime
    reason: FailoverReason
    source_node: str
    target_node: str
    resources: List[str]
    status: FailoverStatus = FailoverStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: str = ""


class FailoverManager:
    """Manages cluster failover operations.

    Inspired by Pacemaker's failover logic but simplified:
    - Active/Passive model like RoseHA
    - Automatic failover on node failure
    - Optional STONITH/fencing
    """

    def __init__(self, cluster_manager, resource_manager, config: Any):
        self.cluster = cluster_manager
        self.resources = resource_manager
        self.config = config
        self._failover_history: List[FailoverEvent] = []
        self._active_failover: Optional[str] = None
        logger.info("FailoverManager initialized")

    async def initiate_failover(
        self,
        reason: FailoverReason,
        source_node: str,
        target_node: Optional[str] = None,
        resources: Optional[List[str]] = None,
    ) -> Optional[FailoverEvent]:
        """Initiate a failover operation."""
        if self._active_failover:
            logger.warning("Failover already in progress")
            return None

        # Check quorum before failover
        if hasattr(self.cluster, 'quorum') and not self.cluster.has_quorum():
            logger.error("Cannot initiate failover: cluster has no quorum")
            return None

        # Determine target node
        if not target_node:
            active = self.cluster.elect_active_node()
            if not active:
                logger.error("No eligible node for failover")
                return None
            target_node = active.name

        # Get resources to failover
        if not resources:
            resources = list(self.resources._resources.keys())

        event = FailoverEvent(
            id=f"fo-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.now(),
            reason=reason,
            source_node=source_node,
            target_node=target_node,
            resources=resources,
        )
        self._failover_history.append(event)
        self._active_failover = event.id

        asyncio.create_task(self._execute_failover(event))
        logger.info(
            f"Initiated failover {event.id}: "
            f"{source_node} -> {target_node} (reason: {reason.value})"
        )
        return event

    async def _execute_failover(self, event: FailoverEvent) -> None:
        """Execute the failover operation."""
        event.status = FailoverStatus.IN_PROGRESS
        event.start_time = datetime.now()
        logger.info(f"Executing failover {event.id}")

        try:
            # Step 1: Stop resources on source node (if accessible)
            for resource_name in event.resources:
                if resource_name in self.resources._resources:
                    resource = self.resources._resources[resource_name]
                    if resource.node == event.source_node:
                        logger.info(f"Stopping resource {resource_name} on {event.source_node}")
                        await self.resources.stop_resource(resource_name)

            # Step 2: Start resources on target node
            for resource_name in event.resources:
                if resource_name in self.resources._resources:
                    logger.info(f"Starting resource {resource_name} on {event.target_node}")
                    result = await self.resources.start_resource(
                        resource_name, event.target_node
                    )
                    if result != OperationResult.SUCCESS:
                        logger.error(f"Failed to start resource {resource_name} on failover")

            # Step 3: Update cluster state
            if event.target_node in self.cluster.nodes:
                self.cluster.nodes[event.target_node].role = NodeRole.ACTIVE
            if event.source_node in self.cluster.nodes:
                self.cluster.nodes[event.source_node].role = NodeRole.PASSIVE

            event.status = FailoverStatus.COMPLETED
            event.end_time = datetime.now()
            logger.info(f"Failover {event.id} completed successfully")

        except Exception as e:
            event.status = FailoverStatus.FAILED
            event.error = str(e)
            event.end_time = datetime.now()
            logger.error(f"Failover {event.id} failed: {e}")

        finally:
            self._active_failover = None

    async def initiate_stonith(self, node_name: str) -> bool:
        """Initiate STONITH (fencing) for a node.

        STONITH = "Shoot The Other Node In The Head"
        Prevents split-brain by ensuring failed node is truly offline.
        """
        if not self.config.stonith_enabled:
            logger.info("STONITH is disabled, skipping fencing")
            return True

        logger.warning(f"Initiating STONITH for node: {node_name}")

        try:
            # In a real implementation, this would call:
            # - IPMI / iLO / BMC to power-cycle the node
            # - Or use watchdog-based fencing
            # - Or use cloud API to terminate the instance
            await asyncio.sleep(1)  # Simulate fencing operation

            if node_name in self.cluster.nodes:
                self.cluster.nodes[node_name].status = NodeStatus.FENCING

            logger.info(f"STONITH completed for node: {node_name}")
            return True

        except Exception as e:
            logger.error(f"STONITH failed for node {node_name}: {e}")
            return False

    def get_failover_history(self, limit: int = 20) -> List[Dict]:
        """Get recent failover history."""
        events = self._failover_history[-limit:]
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "reason": e.reason.value,
                "source_node": e.source_node,
                "target_node": e.target_node,
                "resources": e.resources,
                "status": e.status.value,
                "duration": (
                    (e.end_time - e.start_time).total_seconds()
                    if e.end_time and e.start_time
                    else None
                ),
                "error": e.error,
            }
            for e in events
        ]

    def get_status(self) -> Dict:
        """Get failover manager status."""
        return {
            "active_failover": self._active_failover,
            "total_failovers": len(self._failover_history),
            "recent_failovers": len(
                [e for e in self._failover_history if e.status == FailoverStatus.COMPLETED]
            ),
            "failed_failovers": len(
                [e for e in self._failover_history if e.status == FailoverStatus.FAILED]
            ),
        }
