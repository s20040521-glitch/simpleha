"""Unit tests for SimpleHA cluster module."""

import asyncio
import pytest
from datetime import datetime

from simpleha.core.cluster import (
    ClusterManager,
    ClusterConfig,
    ClusterNode,
    NodeRole,
    NodeStatus,
)


@pytest.fixture
def cluster_config():
    """Create a test cluster configuration."""
    return ClusterConfig(
        name="test-cluster",
        heartbeat_interval=1.0,
        heartbeat_timeout=5.0,
        failover_timeout=10.0,
    )


@pytest.fixture
def cluster_manager(cluster_config):
    """Create a test cluster manager."""
    return ClusterManager(cluster_config)


class TestClusterNode:
    """Tests for ClusterNode class."""

    def test_create_node(self):
        """Test creating a cluster node."""
        node = ClusterNode(name="node1", address="192.168.1.10")
        assert node.name == "node1"
        assert node.address == "192.168.1.10"
        assert node.role == NodeRole.PASSIVE
        assert node.status == NodeStatus.UNKNOWN

    def test_node_attributes(self):
        """Test node attributes."""
        node = ClusterNode(
            name="node1",
            address="192.168.1.10",
            priority=2,
            attributes={"site": "primary"},
        )
        assert node.priority == 2
        assert node.attributes["site"] == "primary"


class TestClusterManager:
    """Tests for ClusterManager class."""

    def test_init(self, cluster_manager, cluster_config):
        """Test cluster manager initialization."""
        assert cluster_manager.config.name == "test-cluster"
        assert len(cluster_manager.nodes) == 0

    def test_add_node(self, cluster_manager):
        """Test adding a node to cluster."""
        cluster_manager.add_node("node1", "192.168.1.10", priority=2)
        assert "node1" in cluster_manager.nodes
        assert cluster_manager.nodes["node1"].address == "192.168.1.10"
        assert cluster_manager.nodes["node1"].priority == 2

    def test_remove_node(self, cluster_manager):
        """Test removing a node from cluster."""
        cluster_manager.add_node("node1", "192.168.1.10")
        cluster_manager.remove_node("node1")
        assert "node1" not in cluster_manager.nodes

    def test_elect_active_node(self, cluster_manager):
        """Test active node election."""
        cluster_manager.add_node("node1", "192.168.1.10", priority=2)
        cluster_manager.add_node("node2", "192.168.1.11", priority=1)
        cluster_manager.nodes["node1"].status = NodeStatus.ONLINE
        cluster_manager.nodes["node2"].status = NodeStatus.ONLINE

        elected = cluster_manager.elect_active_node()
        assert elected is not None
        assert elected.name == "node1"
        assert elected.role == NodeRole.ACTIVE

    def test_get_cluster_status(self, cluster_manager):
        """Test getting cluster status."""
        cluster_manager.add_node("node1", "192.168.1.10", priority=2)
        cluster_manager.add_node("node2", "192.168.1.11", priority=1)
        cluster_manager.nodes["node1"].status = NodeStatus.ONLINE
        cluster_manager.elect_active_node()

        status = cluster_manager.get_cluster_status()
        assert status["cluster_name"] == "test-cluster"
        assert status["active_node"] == "node1"
        assert status["total_nodes"] == 2


@pytest.mark.asyncio
class TestClusterManagerAsync:
    """Async tests for ClusterManager."""

    async def test_start_stop(self, cluster_manager):
        """Test starting and stopping cluster manager."""
        await cluster_manager.start()
        assert cluster_manager._running is True
        await cluster_manager.stop()
        assert cluster_manager._running is False

    async def test_monitor_loop(self, cluster_manager):
        """Test the monitoring loop."""
        cluster_manager.add_node("node1", "192.168.1.10")
        cluster_manager.nodes["node1"].status = NodeStatus.ONLINE

        monitor_task = asyncio.create_task(cluster_manager._monitor_loop())
        await asyncio.sleep(0.5)
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        assert True
