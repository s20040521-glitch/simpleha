"""Resource agents for SimpleHA.

Resource agents are plugins that manage specific resource types
(IP addresses, filesystems, systemd services, etc.).

Inspired by Pacemaker's OCF resource agents but in Python.
"""

from simpleha.agents.base import BaseAgent, AgentResult
from simpleha.agents.ip import IPAgent
from simpleha.agents.service import ServiceAgent
from simpleha.agents.filesystem import FilesystemAgent

__all__ = [
    "BaseAgent",
    "AgentResult",
    "IPAgent",
    "ServiceAgent",
    "FilesystemAgent",
]
