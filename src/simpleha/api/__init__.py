"""REST API for SimpleHA cluster management.

Provides HTTP API for cluster operations, monitoring, and management.
Similar to Pacemaker's PCMK API or modern cluster management APIs.
"""

from simpleha.api.server import HAAServer
from simpleha.api.models import *

__all__ = ["HAAServer", "ClusterStatus", "NodeStatus", "ResourceStatus"]
