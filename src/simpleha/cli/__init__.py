"""Command Line Interface for SimpleHA.

Provides cluster management commands similar to:
- Pacemaker's crm, crm_mon, crm_resource
- RoseHA's CLI tools

Supports both interactive and scripted usage.
"""

from simpleha.cli.main import main
from simpleha.cli.commands import (
    ClusterCommands,
    ResourceCommands,
    MonitorCommands,
)

__all__ = ["main", "ClusterCommands", "ResourceCommands", "MonitorCommands"]
