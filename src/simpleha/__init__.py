"""SimpleHA - Simplified High Availability Cluster Manager.

A lightweight HA cluster solution inspired by Pacemaker/RoseHA patterns,
designed for ease of use and modern Python deployment.
"""

__version__ = "1.0.0"
__author__ = "DevOps Automation Team"

from simpleha.core.cluster import ClusterManager
from simpleha.core.config import HAConfig

__all__ = ["ClusterManager", "HAConfig", "__version__"]
