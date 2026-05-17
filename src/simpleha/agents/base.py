"""Base class for all SimpleHA resource agents.

Inspired by OCF (Open Cluster Framework) resource agent standard
used by Pacemaker, but implemented in Python with async support.
"""

import abc
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result from a resource agent operation."""

    success: bool
    running: Optional[bool] = None
    message: str = ""
    data: Dict[str, Any] = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


class BaseAgent(abc.ABC):
    """Abstract base class for all resource agents.

    Similar to an OCF resource agent, each agent must implement:
    - start(): Start the resource
    - stop(): Stop the resource
    - monitor(): Check if resource is running correctly

    Inspired by Pacemaker's OCF agent interface.
    """

    # Agent metadata
    name: str = "base"
    version: str = "1.0.0"
    description: str = "Base resource agent"

    def __init__(self):
        self.logger = logging.getLogger(f"simpleha.agents.{self.name}")

    @abc.abstractmethod
    async def start(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Start the resource.

        Args:
            params: Resource parameters from configuration.

        Returns:
            AgentResult-compatible dict with 'success', 'message', 'data' keys.
        """
        pass

    @abc.abstractmethod
    async def stop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Stop the resource.

        Args:
            params: Resource parameters from configuration.

        Returns:
            AgentResult-compatible dict.
        """
        pass

    @abc.abstractmethod
    async def monitor(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Monitor resource health.

        Args:
            params: Resource parameters from configuration.

        Returns:
            Dict with 'success', 'running' (bool), 'message' keys.
        """
        pass

    async def validate(self, params: Dict[str, Any]) -> AgentResult:
        """Validate resource parameters before start.

        Override in subclasses for agent-specific validation.
        """
        return AgentResult(success=True, message="Validation passed")

    async def metadata(self) -> Dict[str, Any]:
        """Return agent metadata (similar to OCF meta-data)."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "provider": "simpleha",
            "capabilities": ["start", "stop", "monitor"],
        }

    def _success(self, message: str = "", **data) -> Dict[str, Any]:
        """Helper to return a success result."""
        return {
            "success": True,
            "message": message,
            "data": data,
        }

    def _fail(self, message: str = "", **data) -> Dict[str, Any]:
        """Helper to return a failure result."""
        return {
            "success": False,
            "message": message,
            "data": data,
        }

    def _running(self, is_running: bool, message: str = "", **data) -> Dict[str, Any]:
        """Helper for monitor results."""
        return {
            "success": True,
            "running": is_running,
            "message": message,
            "data": data,
        }
