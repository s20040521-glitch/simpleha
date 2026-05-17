"""Unit tests for SimpleHA resource module."""

import pytest

from simpleha.core.resource import (
    Resource,
    ResourceGroup,
    ResourceManager,
    ResourceState,
    OperationResult,
)


class TestResource:
    """Tests for Resource class."""

    def test_create_resource(self):
        """Test creating a resource."""
        resource = Resource(
            name="web-ip",
            resource_type="ip",
            agent="simpleha.agents.ip:IPAgent",
            params={"ip": "192.168.1.100", "netmask": "24"},
        )
        assert resource.name == "web-ip"
        assert resource.resource_type == "ip"
        assert resource.state == ResourceState.STOPPED
        assert resource.failure_count == 0

    def test_record_operation(self):
        """Test recording resource operations."""
        resource = Resource(
            name="test",
            resource_type="service",
            agent="simpleha.agents.service:ServiceAgent",
        )

        resource.record_operation("start", OperationResult.SUCCESS, duration=1.5)
        assert len(resource.operations) == 1
        assert resource.operations[0].result == OperationResult.SUCCESS
        assert resource.failure_count == 0

        resource.record_operation("start", OperationResult.FAIL, "Error")
        assert resource.failure_count == 1
        assert resource.last_failure is not None

    def test_should_fence(self):
        """Test fencing threshold check."""
        resource = Resource(
            name="test",
            resource_type="service",
            agent="simpleha.agents.service:ServiceAgent",
        )

        assert resource.should_fence(3) is False
        resource.failure_count = 2
        assert resource.should_fence(3) is False
        resource.failure_count = 3
        assert resource.should_fence(3) is True

    def test_to_dict(self):
        """Test resource serialization."""
        resource = Resource(
            name="test",
            resource_type="ip",
            agent="simpleha.agents.ip:IPAgent",
            params={"ip": "192.168.1.100"},
        )
        data = resource.to_dict()
        assert data["name"] == "test"
        assert data["type"] == "ip"
        assert data["state"] == "stopped"


class TestResourceGroup:
    """Tests for ResourceGroup class."""

    def test_create_group(self):
        """Test creating a resource group."""
        group = ResourceGroup(
            name="app-group",
            resources=["ip", "service", "fs"],
            ordered=True,
            colocated=True,
        )
        assert group.name == "app-group"
        assert len(group.resources) == 3
        assert group.ordered is True
        assert group.colocated is True

    def test_to_dict(self):
        """Test resource group serialization."""
        group = ResourceGroup(
            name="test-group",
            resources=["res1", "res2"],
        )
        data = group.to_dict()
        assert data["name"] == "test-group"
        assert data["resources"] == ["res1", "res2"]


class TestResourceManager:
    """Tests for ResourceManager class."""

    @pytest.fixture
    def resource_manager(self):
        """Create a test resource manager."""
        return ResourceManager()

    def test_init(self, resource_manager):
        """Test resource manager initialization."""
        assert len(resource_manager._resources) == 0
        assert len(resource_manager._groups) == 0

    def test_add_resource(self, resource_manager):
        """Test adding a resource."""
        resource = Resource(
            name="test-ip",
            resource_type="ip",
            agent="simpleha.agents.ip:IPAgent",
        )
        resource_manager.add_resource(resource)
        assert "test-ip" in resource_manager._resources

    def test_remove_resource(self, resource_manager):
        """Test removing a resource."""
        resource = Resource(
            name="test-ip",
            resource_type="ip",
            agent="simpleha.agents.ip:IPAgent",
        )
        resource_manager.add_resource(resource)
        resource_manager.remove_resource("test-ip")
        assert "test-ip" not in resource_manager._resources

    def test_add_group(self, resource_manager):
        """Test adding a resource group."""
        group = ResourceGroup(
            name="test-group",
            resources=["res1", "res2"],
        )
        resource_manager.add_group(group)
        assert "test-group" in resource_manager._groups

    def test_get_resource_status(self, resource_manager):
        """Test getting resource status."""
        resource = Resource(
            name="test-ip",
            resource_type="ip",
            agent="simpleha.agents.ip:IPAgent",
        )
        resource_manager.add_resource(resource)

        status = resource_manager.get_resource_status("test-ip")
        assert status is not None
        assert status["name"] == "test-ip"

        not_found = resource_manager.get_resource_status("nonexistent")
        assert not_found is None

    def test_get_all_status(self, resource_manager):
        """Test getting all resources status."""
        resource_manager.add_resource(
            Resource(
                name="ip1",
                resource_type="ip",
                agent="simpleha.agents.ip:IPAgent",
            )
        )
        resource_manager.add_resource(
            Resource(
                name="svc1",
                resource_type="service",
                agent="simpleha.agents.service:ServiceAgent",
            )
        )

        status = resource_manager.get_all_status()
        assert status["summary"]["total"] == 2
        assert status["summary"]["stopped"] == 2
