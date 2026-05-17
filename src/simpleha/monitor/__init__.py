"""Monitor service for SimpleHA cluster.

Provides health monitoring, alerting, and status reporting
similar to Pacemaker's crm_mon tool.
"""

from simpleha.monitor.service import MonitorService
from simpleha.monitor.alerter import AlertManager

__all__ = ["MonitorService", "AlertManager"]
