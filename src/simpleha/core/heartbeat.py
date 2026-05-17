"""Heartbeat monitoring for SimpleHA cluster.

Implements heartbeat mechanism to detect node failures.
Similar to Pacemaker's membership and heartbeat layers.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatRecord:
    """Record of a heartbeat from a node."""

    node: str
    timestamp: datetime
    latency: float  # milliseconds
    sequence: int


class HeartbeatMonitor:
    """Monitors cluster node heartbeats.

    Each node sends periodic heartbeats. If a node misses too many
    heartbeats, it's considered failed and failover is triggered.

    Inspired by Pacemaker's membership layer and RoseHA's heartbeat model.
    """

    def __init__(
        self,
        nodes: Dict[str, Any],
        interval: float = 2.0,
        timeout: float = 10.0,
        max_missed: int = 3,
    ):
        self.nodes = nodes  # Reference to cluster nodes dict
        self.interval = interval
        self.timeout = timeout
        self.max_missed = max_missed

        self._records: Dict[str, List[HeartbeatRecord]] = {}
        self._missed_counts: Dict[str, int] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._on_failure_callbacks: List[Callable] = []
        self._sequence: Dict[str, int] = {}

        logger.info(
            f"HeartbeatMonitor initialized: "
            f"interval={interval}s, timeout={timeout}s, max_missed={max_missed}"
        )

    def on_node_failure(self, callback: Callable[[str], None]) -> None:
        """Register a callback for node failure detection."""
        self._on_failure_callbacks.append(callback)

    async def start_all(self) -> None:
        """Start heartbeat monitoring for all nodes."""
        self._running = True
        for node_name in self.nodes:
            task = asyncio.create_task(self._monitor_node(node_name))
            self._tasks.append(task)
            # Start sender for this node (if we're that node)
            sender_task = asyncio.create_task(self._send_heartbeats(node_name))
            self._tasks.append(sender_task)
        logger.info(f"Started heartbeat monitoring for {len(self.nodes)} nodes")

    async def start_node(self, node_name: str) -> None:
        """Start monitoring a specific node."""
        if node_name not in self.nodes:
            logger.warning(f"Node {node_name} not found")
            return
        task = asyncio.create_task(self._monitor_node(node_name))
        self._tasks.append(task)
        logger.info(f"Started monitoring node: {node_name}")

    async def stop(self) -> None:
        """Stop all heartbeat monitoring."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Stopped heartbeat monitoring")

    async def _monitor_node(self, node_name: str) -> None:
        """Monitor heartbeats from a specific node."""
        while self._running:
            try:
                last_beat = self._get_last_heartbeat(node_name)
                if last_beat:
                    age = (datetime.now(timezone.utc) - last_beat.timestamp).total_seconds()
                    if age > self.timeout:
                        self._missed_counts[node_name] = (
                            self._missed_counts.get(node_name, 0) + 1
                        )
                        logger.warning(
                            f"Node {node_name} heartbeat age: {age:.1f}s "
                            f"(missed: {self._missed_counts.get(node_name, 0)})"
                        )

                        if self._missed_counts[node_name] >= self.max_missed:
                            logger.error(
                                f"Node {node_name} considered failed "
                                f"(missed {self.max_missed} heartbeats)"
                            )
                            await self._handle_node_failure(node_name)
                    else:
                        # Reset missed count on successful heartbeat
                        self._missed_counts[node_name] = 0
                else:
                    # No heartbeat yet, increment missed
                    self._missed_counts[node_name] = (
                        self._missed_counts.get(node_name, 0) + 1
                    )

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring node {node_name}: {e}")
                await asyncio.sleep(self.interval)

    async def _send_heartbeats(self, node_name: str) -> None:
        """Send periodic heartbeats (for the local node).

        In a real implementation, this would send HTTP requests
        or UDP packets to other nodes.
        """
        while self._running:
            try:
                seq = self._sequence.get(node_name, 0) + 1
                self._sequence[node_name] = seq

                record = HeartbeatRecord(
                    node=node_name,
                    timestamp=datetime.now(timezone.utc),
                    latency=0.0,
                    sequence=seq,
                )
                self._add_record(node_name, record)

                # In real implementation: send to other nodes
                # await self._broadcast_heartbeat(node_name, seq)

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error sending heartbeat for {node_name}: {e}")
                await asyncio.sleep(self.interval)

    async def _handle_node_failure(self, node_name: str) -> None:
        """Handle detected node failure."""
        logger.error(f"Node failure detected: {node_name}")
        if node_name in self.nodes:
            self.nodes[node_name].status = NodeStatus.OFFLINE

        for callback in self._on_failure_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(node_name)
                else:
                    callback(node_name)
            except Exception as e:
                logger.error(f"Error in failure callback: {e}")

    def _add_record(self, node_name: str, record: HeartbeatRecord) -> None:
        """Add a heartbeat record."""
        if node_name not in self._records:
            self._records[node_name] = []
        self._records[node_name].append(record)
        # Keep only last 100 records per node
        self._records[node_name] = self._records[node_name][-100:]

        # Update node's last heartbeat
        if node_name in self.nodes:
            self.nodes[node_name].last_heartbeat = record.timestamp
            self.nodes[node_name].status = NodeStatus.ONLINE

    def _get_last_heartbeat(self, node_name: str) -> Optional[HeartbeatRecord]:
        """Get the last heartbeat record for a node."""
        records = self._records.get(node_name, [])
        return records[-1] if records else None

    def receive_heartbeat(self, node_name: str, sequence: int, latency: float = 0.0) -> None:
        """Receive a heartbeat from a remote node (API endpoint)."""
        record = HeartbeatRecord(
            node=node_name,
            timestamp=datetime.now(timezone.utc),
            latency=latency,
            sequence=sequence,
        )
        self._add_record(node_name, record)
        logger.debug(f"Received heartbeat from {node_name} (seq={sequence})")

    def get_status(self) -> Dict:
        """Get heartbeat monitor status."""
        now = datetime.now(timezone.utc)
        return {
            "running": self._running,
            "interval": self.interval,
            "timeout": self.timeout,
            "max_missed": self.max_missed,
            "nodes": {
                node_name: {
                    "last_heartbeat": (
                        self._records.get(node_name, [])[-1].timestamp.isoformat()
                        if self._records.get(node_name)
                        else None
                    ),
                    "missed_count": self._missed_counts.get(node_name, 0),
                    "status": (
                        self.nodes[node_name].status.value
                        if node_name in self.nodes
                        else "unknown"
                    ),
                }
                for node_name in self.nodes
            },
        }
