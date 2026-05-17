"""Core HA cluster logic modules."""

from simpleha.core.cluster import ClusterManager
from simpleha.core.resource import Resource, ResourceGroup
from simpleha.core.failover import FailoverManager
from simpleha.core.heartbeat import HeartbeatMonitor
from simpleha.core.quorum import QuorumManager, QuorumState, QuorumInfo

__all__ = [
    "ClusterManager",
    "Resource",
    "ResourceGroup",
    "FailoverManager",
    "HeartbeatMonitor",
    "QuorumManager",
    "QuorumState",
    "QuorumInfo",
]
