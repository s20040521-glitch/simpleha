"""Monitor Service for SimpleHA cluster.

Provides continuous health monitoring and alerting.
Similar to Pacemaker's crm_mon tool but as a running service.
"""

import asyncio
import json
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class MonitorService:
    """Main monitor service for SimpleHA cluster.

    Continuously checks cluster health and triggers alerts on failures.
    """

    def __init__(
        self,
        cluster_manager: Any,
        resource_manager: Any,
        failover_manager: Any,
        config: Any,
    ):
        self.cluster = cluster_manager
        self.resources = resource_manager
        self.failover = failover_manager
        self.config = config
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._alert_manager = AlertManager(config)
        logger.info("MonitorService initialized")

    async def start(self) -> None:
        """Start the monitor service."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("MonitorService started")

    async def stop(self) -> None:
        """Stop the monitor service."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MonitorService stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        interval = getattr(self.config, "monitor_interval", 60)
        while self._running:
            try:
                await self._check_cluster_health()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(interval)

    async def _check_cluster_health(self) -> None:
        """Check overall cluster health."""
        status = self.cluster.get_cluster_status()
        resource_status = self.resources.get_all_status()

        # Check for failed nodes
        failed_nodes = [
            name for name, info in status["nodes"].items()
            if info["status"] == "offline"
        ]
        if failed_nodes:
            msg = f"Nodes offline: {', '.join(failed_nodes)}"
            logger.warning(msg)
            await self._alert_manager.send_alert("node_failure", msg, failed_nodes)

        # Check for failed resources
        failed_resources = [
            name for name, info in resource_status["resources"].items()
            if info["state"] == "failed"
        ]
        if failed_resources:
            msg = f"Resources failed: {', '.join(failed_resources)}"
            logger.warning(msg)
            await self._alert_manager.send_alert(
                "resource_failure", msg, failed_resources
            )

        # Check quorum if required
        if self.config.quorum_required:
            healthy = status["healthy_nodes"]
            total = status["total_nodes"]
            if healthy < (total // 2 + 1):
                msg = f"Quorum lost: {healthy}/{total} nodes healthy"
                logger.error(msg)
                await self._alert_manager.send_alert("quorum_lost", msg)

    async def get_dashboard_data(self) -> Dict:
        """Get data for monitoring dashboard."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cluster": self.cluster.get_cluster_status(),
            "resources": self.resources.get_all_status(),
            "failover": self.failover.get_status(),
            "heartbeat": (
                self.cluster.heartbeat.get_status()
                if hasattr(self.cluster, "heartbeat")
                else {}
            ),
        }

    def main(self) -> None:
        """Entry point for monitor service."""
        import signal

        logging.basicConfig(
            level=getattr(logging, self.config.log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.start())

        def shutdown(sig):
            logger.info(f"Received signal {sig}")
            asyncio.ensure_future(self.stop())

        for s in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(s, lambda s=s: shutdown(s))

        loop.run_forever()


class AlertManager:
    """Manages alert delivery via multiple channels."""

    def __init__(self, config: Any):
        self.config = config
        self._webhooks: List[str] = getattr(config, "alert_webhooks", [])
        self._email_config = getattr(config, "email_alerts", None)
        logger.info("AlertManager initialized")

    async def send_alert(
        self, alert_type: str, message: str, details: Any = None
    ) -> None:
        """Send an alert via configured channels."""
        alert = {
            "type": alert_type,
            "message": message,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
            "cluster": getattr(self.config, "cluster_name", "unknown"),
        }

        # Log the alert
        logger.warning(f"ALERT [{alert_type}]: {message}")

        # Send to webhooks
        for webhook_url in self._webhooks:
            asyncio.create_task(self._send_webhook(webhook_url, alert))

        # Send email if configured
        if self._email_config:
            asyncio.create_task(self._send_email(alert))

    async def _send_webhook(self, url: str, alert: Dict) -> None:
        """Send alert to a webhook URL (e.g., Slack, PagerDuty)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=alert, timeout=10) as resp:
                    if resp.status >= 400:
                        logger.error(f"Webhook {url} returned {resp.status}")
        except Exception as e:
            logger.error(f"Failed to send webhook {url}: {e}")

    async def _send_email(self, alert: Dict) -> None:
        """Send alert via email."""
        if not self._email_config:
            return
        try:
            msg = MIMEText(alert["message"])
            msg["Subject"] = f"[SimpleHA] {alert['type']} - {alert['cluster']}"
            msg["From"] = self._email_config["from"]
            msg["To"] = self._email_config["to"]

            with smtplib.SMTP(
                self._email_config["smtp_host"],
                self._email_config.get("smtp_port", 587),
            ) as server:
                if self._email_config.get("use_tls"):
                    server.starttls()
                if self._email_config.get("password"):
                    server.login(
                        self._email_config["username"],
                        self._email_config["password"],
                    )
                server.send_message(msg)
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
