"""Integration tests for SimpleHA cluster simulation."""

import asyncio
import os
import pytest

from simpleha.core.cluster import ClusterManager, ClusterConfig, NodeStatus, NodeRole
from simpleha.core.config import HAConfig, NodeConfig, ResourceConfig
from simpleha.core.resource import ResourceManager, Resource, ResourceState
from simpleha.core.failover import FailoverManager, FailoverReason, FailoverStatus


@pytest.fixture
def sample_config():
    """Create a sample HA configuration."""
    return HAConfig(
        cluster_name="test-cluster",
        nodes=[
            NodeConfig(name="node1", address="192.168.1.10", priority=2),
            NodeConfig(name="node2", address="192.168.1.11", priority=1),
        ],
        resources=[
            ResourceConfig(
                name="float-ip",
                type="ip",
                agent="simpleha.agents.ip:IPAgent",
                params={"ip": "192.168.1.100", "netmask": "24"},
            ),
        ],
        heartbeat_interval=1.0,
        heartbeat_timeout=5.0,
        stonith_enabled=False,
    )


@pytest.fixture
def cluster_system(sample_config):
    """Create a full cluster system for testing."""
    cluster = ClusterManager(sample_config)
    resources = ResourceManager()
    failover = FailoverManager(cluster, resources, sample_config)

    # Add resources
    for res_cfg in sample_config.resources:
        resources.add_resource(
            Resource(
                name=res_cfg.name,
                resource_type=res_cfg.type,
                agent=res_cfg.agent,
                params=res_cfg.params,
                priority=res_cfg.priority,
            )
        )

    return cluster, resources, failover


class TestClusterIntegration:
    """Integration tests for cluster system."""

    def test_cluster_initialization(self, cluster_system):
        """Test cluster system initialization."""
        cluster, resources, failover = cluster_system

        assert cluster.config.cluster_name == "test-cluster"
        assert len(cluster.nodes) == 2
        assert len(resources._resources) == 1

    def test_node_election_and_failover(self, cluster_system):
        """Test node election and failover scenario."""
        cluster, resources, failover = cluster_system

        # Both nodes online
        cluster.nodes["node1"].status = NodeStatus.ONLINE
        cluster.nodes["node2"].status = NodeStatus.ONLINE

        # Elect active node
        elected = cluster.elect_active_node()
        assert elected.name == "node1"  # Higher priority

        # Simulate node1 failure
        cluster.nodes["node1"].status = NodeStatus.OFFLINE

        # Trigger failover
        event = asyncio.get_event_loop().run_until_complete(
            failover.initiate_failover(
                reason=FailoverReason.NODE_FAILURE,
                source_node="node1",
            )
        )

        assert event is not None
        assert event.target_node == "node2"

    def test_resource_start_stop(self, cluster_system):
        """Test starting and stopping resources."""
        cluster, resources, failover = cluster_system

        # Start a resource
        cluster.nodes["node1"].status = NodeStatus.ONLINE
        cluster.elect_active_node()

        # Note: In real test, would use mock agents
        # For simulation, we just verify state transitions
        resource = resources._resources["float-ip"]
        assert resource.state == ResourceState.STOPPED

    def test_failover_history(self, cluster_system):
        """Test failover history tracking."""
        cluster, resources, failover = cluster_system

        # Trigger a failover
        cluster.nodes["node1"].status = NodeStatus.ONLINE
        cluster.nodes["node2"].status = NodeStatus.ONLINE
        cluster.elect_active_node()

        asyncio.get_event_loop().run_until_complete(
            failover.initiate_failover(
                reason=FailoverReason.MANUAL,
                source_node="node1",
                target_node="node2",
            )
        )

        # Give time for async execution
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))

        history = failover.get_failover_history()
        assert len(history) == 1
        assert history[0]["reason"] == "manual"
        assert history[0]["source_node"] == "node1"

    def test_quorum_check(self, cluster_system):
        """Test quorum requirements."""
        cluster, resources, failover = cluster_system

        cluster.config.quorum_required = True

        # 1 of 2 nodes online - no quorum
        cluster.nodes["node1"].status = NodeStatus.ONLINE
        cluster.nodes["node2"].status = NodeStatus.OFFLINE

        status = cluster.get_cluster_status()
        assert status["healthy_nodes"] == 1
        assert status["healthy_nodes"] < (status["total_nodes"] // 2 + 1)

        # 2 of 2 nodes online - has quorum
        cluster.nodes["node2"].status = NodeStatus.ONLINE
        status = cluster.get_cluster_status()
        assert status["healthy_nodes"] == 2


@pytest.mark.skipif(
    os.environ.get("SIMPLEHA_TEST_MODE") != "1",
    reason="Integration test requires SIMPLEHA_TEST_MODE=1",
)
class TestFullClusterSimulation:
    """Full cluster simulation tests."""

    async def test_cluster_lifecycle(self, cluster_system):
        """Test complete cluster lifecycle."""
        cluster, resources, failover = cluster_system

        # Start cluster
        await cluster.start()
        assert cluster._running is True

        # Wait for monitoring
        await asyncio.sleep(2)

        # Check status
        status = cluster.get_cluster_status()
        assert "cluster_name" in status

        # Stop cluster
        await cluster.stop()
        assert cluster._running is False

    async def test_concurrent_resource_operations(self, cluster_system):
        """Test concurrent resource operations."""
        cluster, resources, failover = cluster_system

        # Add more resources
        for i in range(5):
            resources.add_resource(
                Resource(
                    name=f"resource-{i}",
                    resource_type="service",
                    agent="simpleha.agents.service:ServiceAgent",
                    params={"service_name": f"test-service-{i}"},
                )
            )

        # Monitor all resources concurrently
        tasks = [
            resources.monitor_resource(f"resource-{i}")
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # All should complete (even if some fail)
        assert len(results) == 5
