"""Tests for QuorumManager - Arbitration Disk functionality."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from simpleha.core.quorum import (
    QuorumManager,
    QuorumState,
    QuorumVote,
    QuorumInfo,
    ArbitrationDisk,
    ArbitrationStatus,
)


class TestQuorumManager:
    """Test cases for QuorumManager."""

    @pytest.fixture
    def quorum_config(self):
        """Basic quorum configuration."""
        return {
            "expected_votes": 2,
            "votes_needed": 2,
            "two_node_optimistic": False,
        }

    @pytest.fixture
    def quorum_config_with_disk(self):
        """Quorum configuration with arbitration disk."""
        return {
            "expected_votes": 2,
            "votes_needed": 2,
            "two_node_optimistic": False,
            "arbitration_disk": {
                "name": "arb-disk",
                "device_path": "/dev/sdb",
                "device_type": "iscsi",
                "timeout": 5.0,
                "interval": 2.0,
                "heuristic_enabled": False,
                "heuristic_score": 100,
                "fence_delay": 0.0,
            },
        }

    @pytest.fixture
    def quorum_config_optimistic(self):
        """Quorum configuration for optimistic 2-node."""
        return {
            "expected_votes": 2,
            "votes_needed": 1,
            "two_node_optimistic": True,
        }

    def test_quorum_manager_init(self, quorum_config):
        """Test QuorumManager initialization."""
        manager = QuorumManager(quorum_config)

        assert manager.expected_votes == 2
        assert manager.votes_needed == 2
        assert manager.two_node_optimistic is False
        assert manager._state == QuorumState.UNKNOWN

    def test_quorum_manager_with_arbitration_disk(self, quorum_config_with_disk):
        """Test QuorumManager with arbitration disk configured."""
        manager = QuorumManager(quorum_config_with_disk)

        assert manager._arbitration_disk is not None
        assert manager._arbitration_disk.device_path == "/dev/sdb"
        assert manager._arbitration_disk.device_type == "iscsi"

    def test_register_node(self, quorum_config):
        """Test node registration with quorum."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")

        assert "node1" in manager._votes
        assert manager._votes["node1"].node_name == "node1"

    def test_unregister_node(self, quorum_config):
        """Test node unregistration from quorum."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")
        manager.unregister_node("node1")

        assert "node1" not in manager._votes

    @pytest.mark.asyncio
    async def test_record_vote(self, quorum_config):
        """Test recording a node vote."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")

        await manager.record_vote("node1", has_disk_access=True, heuristic_score=50)

        assert manager._votes["node1"].has_disk_access is True
        assert manager._votes["node1"].heuristic_score == 50

    @pytest.mark.asyncio
    async def test_check_quorum_basic(self, quorum_config):
        """Test basic quorum check without arbitration disk."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")
        manager.register_node("node2")

        # Both nodes vote
        await manager.record_vote("node1", has_disk_access=True)
        await manager.record_vote("node2", has_disk_access=True)

        # Check quorum with both nodes online
        state = await manager.check_quorum(["node1", "node2"])

        assert state == QuorumState.HAS_QUORUM

    @pytest.mark.asyncio
    async def test_check_quorum_with_one_node_offline(self, quorum_config):
        """Test quorum with one node offline."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")
        manager.register_node("node2")

        # Only one node votes
        await manager.record_vote("node1", has_disk_access=True)

        # Check quorum with only one node online
        state = await manager.check_quorum(["node1"])

        assert state == QuorumState.NO_QUORUM

    @pytest.mark.asyncio
    async def test_optimistic_two_node_quorum(self, quorum_config_optimistic):
        """Test optimistic 2-node quorum mode."""
        manager = QuorumManager(quorum_config_optimistic)
        manager.register_node("node1")
        manager.register_node("node2")

        # Only one node votes
        await manager.record_vote("node1", has_disk_access=True)

        # Check quorum with optimistic mode
        state = await manager.check_quorum(["node1"])

        # With optimistic mode, single node should have quorum
        assert state == QuorumState.HAS_QUORUM

    @pytest.mark.asyncio
    async def test_quorum_with_arbitration_disk(self, quorum_config_with_disk):
        """Test quorum check with arbitration disk."""
        manager = QuorumManager(quorum_config_with_disk)
        manager.register_node("node1")
        manager.register_node("node2")

        await manager.record_vote("node1", has_disk_access=True)
        await manager.record_vote("node2", has_disk_access=True)

        # Mock the disk check
        with patch.object(manager, '_check_arbitration_disk', return_value=True):
            state = await manager.check_quorum(["node1", "node2"])
            assert state == QuorumState.HAS_QUORUM

    @pytest.mark.asyncio
    async def test_quorum_lost_without_arbitration_disk(self, quorum_config_with_disk):
        """Test quorum lost when arbitration disk is offline."""
        manager = QuorumManager(quorum_config_with_disk)
        manager.register_node("node1")
        manager.register_node("node2")

        await manager.record_vote("node1", has_disk_access=True)
        await manager.record_vote("node2", has_disk_access=True)

        # Mock disk check to return False (disk offline)
        with patch.object(manager, '_check_arbitration_disk', return_value=False):
            state = await manager.check_quorum(["node1", "node2"])
            assert state == QuorumState.NO_QUORUM

    def test_should_stop_resources(self, quorum_config):
        """Test resource stop decision based on quorum."""
        manager = QuorumManager(quorum_config)

        # Initially unknown
        assert manager.should_stop_resources() is True

        # Set quorum state
        manager._state = QuorumState.HAS_QUORUM
        assert manager.should_stop_resources() is False

        manager._state = QuorumState.NO_QUORUM
        assert manager.should_stop_resources() is True

    def test_can_acquire_resources(self, quorum_config):
        """Test resource acquisition based on quorum."""
        manager = QuorumManager(quorum_config)

        # Initially unknown
        assert manager.can_acquire_resources() is False

        # Set quorum state
        manager._state = QuorumState.HAS_QUORUM
        assert manager.can_acquire_resources() is True

        manager._state = QuorumState.NO_QUORUM
        assert manager.can_acquire_resources() is False

    def test_get_quorum_info(self, quorum_config):
        """Test getting quorum information."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")
        manager._state = QuorumState.HAS_QUORUM
        manager.votes_present = 2

        info = manager.get_quorum_info()

        assert isinstance(info, QuorumInfo)
        assert info.state == QuorumState.HAS_QUORUM
        assert info.votes_expected == 2
        assert info.votes_needed == 2
        assert info.votes_present == 2

    def test_get_status(self, quorum_config):
        """Test getting quorum status."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")
        manager._state = QuorumState.HAS_QUORUM
        manager.votes_present = 1

        status = manager.get_status()

        assert status["state"] == "has_quorum"
        assert status["expected_votes"] == 2
        assert status["votes_needed"] == 2
        assert status["can_acquire_resources"] is True
        assert status["should_stop_resources"] is False

    def test_get_status_with_arbitration_disk(self, quorum_config_with_disk):
        """Test getting quorum status with arbitration disk."""
        manager = QuorumManager(quorum_config_with_disk)
        status = manager.get_status()

        assert "arbitration_disk" in status
        assert status["arbitration_disk"]["device_path"] == "/dev/sdb"
        assert status["arbitration_disk"]["device_type"] == "iscsi"

    @pytest.mark.asyncio
    async def test_fence_if_no_quorum(self, quorum_config):
        """Test fencing decision when quorum is lost."""
        manager = QuorumManager(quorum_config)
        manager.register_node("node1")
        manager._state = QuorumState.NO_QUORUM

        # Should trigger fencing
        result = await manager.fence_if_no_quorum("node1", ["node1"])
        assert result is True

    @pytest.mark.asyncio
    async def test_no_fence_with_quorum(self, quorum_config):
        """Test no fencing when quorum is present."""
        manager = QuorumManager(quorum_config)
        manager._state = QuorumState.HAS_QUORUM

        # Should not trigger fencing
        result = await manager.fence_if_no_quorum("node1", ["node1"])
        assert result is False


class TestArbitrationDisk:
    """Test cases for ArbitrationDisk."""

    def test_arbitration_disk_creation(self):
        """Test creating an arbitration disk."""
        disk = ArbitrationDisk(
            name="test-disk",
            device_path="/dev/sdb",
            device_type="iscsi",
            timeout=5.0,
            interval=2.0,
        )

        assert disk.name == "test-disk"
        assert disk.device_path == "/dev/sdb"
        assert disk.device_type == "iscsi"
        assert disk.timeout == 5.0
        assert disk.interval == 2.0

    def test_arbitration_disk_with_heuristic(self):
        """Test arbitration disk with heuristic enabled."""
        disk = ArbitrationDisk(
            name="test-disk",
            device_path="/dev/sdb",
            heuristic_enabled=True,
            heuristic_interval=10.0,
            heuristic_score=200,
        )

        assert disk.heuristic_enabled is True
        assert disk.heuristic_interval == 10.0
        assert disk.heuristic_score == 200


class TestQuorumState:
    """Test cases for QuorumState enum."""

    def test_quorum_states(self):
        """Test all quorum states exist."""
        assert QuorumState.HAS_QUORUM.value == "has_quorum"
        assert QuorumState.NO_QUORUM.value == "no_quorum"
        assert QuorumState.LOST.value == "lost"
        assert QuorumState.UNKNOWN.value == "unknown"


class TestQuorumIntegration:
    """Integration tests for quorum with cluster scenarios."""

    @pytest.mark.asyncio
    async def test_split_brain_scenario(self):
        """Test split-brain prevention through quorum."""
        config = {
            "expected_votes": 2,
            "votes_needed": 2,
            "two_node_optimistic": False,
        }
        manager = QuorumManager(config)

        # Simulate network partition
        manager.register_node("node1")
        manager.register_node("node2")

        # Both nodes think they're online
        await manager.record_vote("node1", has_disk_access=True)
        await manager.record_vote("node2", has_disk_access=True)

        # Without arbitration disk, both nodes have quorum independently
        # This is the split-brain problem - need arbitration disk to resolve
        state = await manager.check_quorum(["node1"])
        assert state == QuorumState.NO_QUORUM  # Single node not enough

        state = await manager.check_quorum(["node2"])
        assert state == QuorumState.NO_QUORUM  # Single node not enough

    @pytest.mark.asyncio
    async def test_failover_requires_quorum(self):
        """Test that failover requires quorum."""
        config = {
            "expected_votes": 2,
            "votes_needed": 2,
            "two_node_optimistic": False,
        }
        manager = QuorumManager(config)
        manager.register_node("node1")
        manager._state = QuorumState.NO_QUORUM

        # Cannot acquire resources without quorum
        assert manager.can_acquire_resources() is False

        # Set quorum
        manager._state = QuorumState.HAS_QUORUM
        assert manager.can_acquire_resources() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
