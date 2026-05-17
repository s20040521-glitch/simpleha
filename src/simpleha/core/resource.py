"""Resource management for SimpleHA cluster.

Manages lifecycle of cluster resources (IP, filesystem, services).
Inspired by Pacemaker's resource agents and LRM (Local Resource Manager).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResourceState(str, Enum):
    """Possible states of a cluster resource."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class OperationResult(str, Enum):
    """Result of a resource operation."""

    SUCCESS = "success"
    FAIL = "fail"
    TIMEOUT = "timeout"
    NOT_SUPPORTED = "not_supported"


@dataclass
class ResourceOperation:
    """Record of a resource operation."""

    operation: str  # start, stop, monitor, migrate
    timestamp: datetime
    result: OperationResult
    message: str = ""
    duration: float = 0.0


@dataclass
class Resource:
    """A cluster-managed resource.

    Similar to a Pacemaker resource, but with simplified state machine.
    """

    name: str
    resource_type: str  # ip, filesystem, service
    agent: str  # Python import path to agent class
    params: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    state: ResourceState = ResourceState.STOPPED
    node: Optional[str] = None
    priority: int = 100
    operations: List[ResourceOperation] = field(default_factory=list)
    monitor_interval: int = 10  # seconds
    start_timeout: int = 20  # seconds
    stop_timeout: int = 20  # seconds
    monitor_timeout: int = 10  # seconds
    failure_count: int = 0
    last_failure: Optional[datetime] = None

    def record_operation(
        self,
        operation: str,
        result: OperationResult,
        message: str = "",
        duration: float = 0.0,
    ) -> None:
        """Record an operation result."""
        self.operations.append(
            ResourceOperation(
                operation=operation,
                timestamp=datetime.now(),
                result=result,
                message=message,
                duration=duration,
            )
        )
        # Keep only last 50 operations
        self.operations = self.operations[-50:]

        if result == OperationResult.FAIL:
            self.failure_count += 1
            self.last_failure = datetime.now()
        elif result == OperationResult.SUCCESS:
            self.failure_count = 0
            self.last_failure = None

    def should_fence(self, failure_threshold: int = 3) -> bool:
        """Check if resource failures should trigger fencing."""
        return self.failure_count >= failure_threshold

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "type": self.resource_type,
            "agent": self.agent,
            "params": self.params,
            "state": self.state.value,
            "node": self.node,
            "priority": self.priority,
            "failure_count": self.failure_count,
            "monitor_interval": self.monitor_interval,
        }


@dataclass
class ResourceGroup:
    """A group of resources that should be colocated and ordered."""

    name: str
    resources: List[str]  # Ordered list of resource names
    ordered: bool = True  # Start/stop in order
    colocated: bool = True  # Keep on same node
    priority: int = 100

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "resources": self.resources,
            "ordered": self.ordered,
            "colocated": self.colocated,
            "priority": self.priority,
        }


class ResourceManager:
    """Manages all cluster resources.

    Inspired by Pacemaker's LRM (Local Resource Manager)
    and CRM resource management.
    """

    def __init__(self):
        self._resources: Dict[str, Resource] = {}
        self._groups: Dict[str, ResourceGroup] = {}
        self._agent_instances: Dict[str, Any] = {}
        logger.info("ResourceManager initialized")

    def add_resource(self, resource: Resource) -> None:
        """Register a resource."""
        self._resources[resource.name] = resource
        logger.info(f"Added resource: {resource.name} (type={resource.resource_type})")

    def remove_resource(self, name: str) -> None:
        """Remove a resource."""
        if name in self._resources:
            del self._resources[name]
            logger.info(f"Removed resource: {name}")

    def add_group(self, group: ResourceGroup) -> None:
        """Add a resource group."""
        self._groups[group.name] = group
        logger.info(f"Added resource group: {group.name}")

    async def start_resource(self, name: str, node: str) -> OperationResult:
        """Start a resource on a node."""
        if name not in self._resources:
            logger.error(f"Resource not found: {name}")
            return OperationResult.FAIL

        resource = self._resources[name]
        resource.state = ResourceState.STARTING

        try:
            agent = await self._get_agent(resource.agent)
            start_time = asyncio.get_event_loop().time()

            try:
                result = await asyncio.wait_for(
                    agent.start(resource.params),
                    timeout=resource.start_timeout,
                )
                duration = asyncio.get_event_loop().time() - start_time

                if result.get("success"):
                    resource.state = ResourceState.RUNNING
                    resource.node = node
                    resource.record_operation("start", OperationResult.SUCCESS, duration=duration)
                    logger.info(f"Resource {name} started on {node}")
                    return OperationResult.SUCCESS
                else:
                    resource.state = ResourceState.FAILED
                    msg = result.get("message", "Unknown error")
                    resource.record_operation("start", OperationResult.FAIL, msg, duration)
                    logger.error(f"Failed to start resource {name}: {msg}")
                    return OperationResult.FAIL

            except asyncio.TimeoutError:
                resource.state = ResourceState.FAILED
                resource.record_operation("start", OperationResult.TIMEOUT, "Start timeout")
                logger.error(f"Timeout starting resource {name}")
                return OperationResult.TIMEOUT

        except Exception as e:
            resource.state = ResourceState.FAILED
            resource.record_operation("start", OperationResult.FAIL, str(e))
            logger.error(f"Error starting resource {name}: {e}")
            return OperationResult.FAIL

    async def stop_resource(self, name: str) -> OperationResult:
        """Stop a resource."""
        if name not in self._resources:
            return OperationResult.FAIL

        resource = self._resources[name]
        resource.state = ResourceState.STOPPING

        try:
            agent = await self._get_agent(resource.agent)
            start_time = asyncio.get_event_loop().time()

            try:
                result = await asyncio.wait_for(
                    agent.stop(resource.params),
                    timeout=resource.stop_timeout,
                )
                duration = asyncio.get_event_loop().time() - start_time

                if result.get("success"):
                    resource.state = ResourceState.STOPPED
                    resource.node = None
                    resource.record_operation("stop", OperationResult.SUCCESS, duration=duration)
                    logger.info(f"Resource {name} stopped")
                    return OperationResult.SUCCESS
                else:
                    msg = result.get("message", "Unknown error")
                    resource.record_operation("stop", OperationResult.FAIL, msg, duration)
                    logger.error(f"Failed to stop resource {name}: {msg}")
                    return OperationResult.FAIL

            except asyncio.TimeoutError:
                resource.record_operation("stop", OperationResult.TIMEOUT, "Stop timeout")
                logger.error(f"Timeout stopping resource {name}")
                return OperationResult.TIMEOUT

        except Exception as e:
            resource.record_operation("stop", OperationResult.FAIL, str(e))
            logger.error(f"Error stopping resource {name}: {e}")
            return OperationResult.FAIL

    async def monitor_resource(self, name: str) -> OperationResult:
        """Monitor a resource's health."""
        if name not in self._resources:
            return OperationResult.FAIL

        resource = self._resources[name]

        try:
            agent = await self._get_agent(resource.agent)
            result = await asyncio.wait_for(
                agent.monitor(resource.params),
                timeout=resource.monitor_timeout,
            )

            if result.get("running"):
                if resource.state != ResourceState.RUNNING:
                    resource.state = ResourceState.RUNNING
                resource.record_operation("monitor", OperationResult.SUCCESS)
                return OperationResult.SUCCESS
            else:
                resource.state = ResourceState.FAILED
                msg = result.get("message", "Monitor detected failure")
                resource.record_operation("monitor", OperationResult.FAIL, msg)
                return OperationResult.FAIL

        except asyncio.TimeoutError:
            resource.record_operation("monitor", OperationResult.TIMEOUT, "Monitor timeout")
            return OperationResult.TIMEOUT

        except Exception as e:
            resource.record_operation("monitor", OperationResult.FAIL, str(e))
            return OperationResult.FAIL

    async def _get_agent(self, agent_path: str) -> Any:
        """Load a resource agent by import path."""
        if agent_path in self._agent_instances:
            return self._agent_instances[agent_path]

        # Dynamic import: "simpleha.agents.ip:IPAgent"
        module_path, class_name = agent_path.split(":")
        import importlib

        module = importlib.import_module(module_path)
        agent_class = getattr(module, class_name)
        instance = agent_class()
        self._agent_instances[agent_path] = instance
        return instance

    def get_resource_status(self, name: str) -> Optional[Dict]:
        """Get status of a specific resource."""
        if name not in self._resources:
            return None
        return self._resources[name].to_dict()

    def get_all_status(self) -> Dict:
        """Get status of all resources."""
        return {
            "resources": {name: r.to_dict() for name, r in self._resources.items()},
            "groups": {name: g.to_dict() for name, g in self._groups.items()},
            "summary": {
                "total": len(self._resources),
                "running": sum(1 for r in self._resources.values() if r.state == ResourceState.RUNNING),
                "stopped": sum(1 for r in self._resources.values() if r.state == ResourceState.STOPPED),
                "failed": sum(1 for r in self._resources.values() if r.state == ResourceState.FAILED),
            },
        }
