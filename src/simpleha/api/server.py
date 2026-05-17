"""REST API Server for SimpleHA cluster management.

FastAPI-based HTTP API similar to modern cluster management APIs.
Provides endpoints for cluster status, resource management, and failover control.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from fastapi import BackgroundTasks, FastAPI, HTTPException, status
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)


def create_app(cluster_manager: Any, resource_manager: Any, failover_manager: Any):
    """Create and configure the FastAPI application.

    Args:
        cluster_manager: The ClusterManager instance
        resource_manager: The ResourceManager instance
        failover_manager: The FailoverManager instance

    Returns:
        Configured FastAPI application
    """
    if not FASTAPI_AVAILABLE:
        logger.error(
            "FastAPI not installed. Install with: pip install fastapi uvicorn"
        )
        return None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan events."""
        logger.info("SimpleHA API starting up")
        yield
        logger.info("SimpleHA API shutting down")

    app = FastAPI(
        title="SimpleHA API",
        description="Simplified High Availability Cluster Management API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # --- Health check ---

    @app.get("/health", tags=["Health"])
    async def health_check():
        """API health check."""
        return {"status": "ok", "service": "simpleha-api", "version": "1.0.0"}

    # --- Cluster endpoints ---

    @app.get("/api/v1/cluster/status", tags=["Cluster"])
    async def get_cluster_status():
        """Get cluster status."""
        return cluster_manager.get_cluster_status()

    @app.get("/api/v1/cluster/nodes", tags=["Cluster"])
    async def list_nodes():
        """List all cluster nodes."""
        status = cluster_manager.get_cluster_status()
        return status.get("nodes", {})

    @app.post("/api/v1/cluster/nodes", tags=["Cluster"], status_code=status.HTTP_201_CREATED)
    async def add_node(name: str, address: str, priority: int = 1):
        """Add a node to the cluster."""
        cluster_manager.add_node(name, address, priority)
        return {"message": f"Node {name} added", "name": name}

    @app.delete("/api/v1/cluster/nodes/{name}", tags=["Cluster"])
    async def remove_node(name: str):
        """Remove a node from the cluster."""
        cluster_manager.remove_node(name)
        return {"message": f"Node {name} removed"}

    # --- Quorum endpoints ---

    @app.get("/api/v1/quorum/status", tags=["Quorum"])
    async def get_quorum_status():
        """Get quorum and arbitration disk status."""
        if hasattr(cluster_manager, 'quorum'):
            return cluster_manager.quorum.get_status()
        return {"error": "Quorum not enabled"}

    @app.get("/api/v1/quorum/info", tags=["Quorum"])
    async def get_quorum_info():
        """Get detailed quorum information."""
        if hasattr(cluster_manager, 'quorum'):
            info = cluster_manager.quorum.get_quorum_info()
            return {
                "state": info.state.value,
                "votes_expected": info.votes_expected,
                "votes_present": info.votes_present,
                "votes_needed": info.votes_needed,
                "quorum_votes": info.quorum_votes,
                "last_updated": info.last_updated.isoformat(),
                "arbitration_status": info.arbitration_status.value,
                "arbitration_disk": info.arbitration_disk,
            }
        return {"error": "Quorum not enabled"}

    @app.get("/api/v1/quorum/has_quorum", tags=["Quorum"])
    async def check_has_quorum():
        """Check if cluster currently has quorum."""
        if hasattr(cluster_manager, 'has_quorum'):
            return {"has_quorum": cluster_manager.has_quorum()}
        return {"has_quorum": True, "note": "Quorum not enabled"}

    # --- Resource endpoints ---

    @app.get("/api/v1/resources", tags=["Resources"])
    async def list_resources():
        """List all resources."""
        return resource_manager.get_all_status()

    @app.get("/api/v1/resources/{name}", tags=["Resources"])
    async def get_resource(name: str):
        """Get resource details."""
        status = resource_manager.get_resource_status(name)
        if not status:
            raise HTTPException(status_code=404, detail=f"Resource {name} not found")
        return status

    @app.post("/api/v1/resources/{name}/start", tags=["Resources"])
    async def start_resource(name: str, background_tasks: BackgroundTasks):
        """Start a resource (async, runs in background)."""
        if name not in resource_manager._resources:
            raise HTTPException(status_code=404, detail=f"Resource {name} not found")

        active = cluster_manager.get_active_node()
        if not active:
            raise HTTPException(status_code=400, detail="No active node available")

        background_tasks.add_task(resource_manager.start_resource, name, active.name)
        return {"message": f"Starting resource {name} in background"}

    @app.post("/api/v1/resources/{name}/stop", tags=["Resources"])
    async def stop_resource(name: str, background_tasks: BackgroundTasks):
        """Stop a resource (async, runs in background)."""
        if name not in resource_manager._resources:
            raise HTTPException(status_code=404, detail=f"Resource {name} not found")

        background_tasks.add_task(resource_manager.stop_resource, name)
        return {"message": f"Stopping resource {name} in background"}

    @app.post("/api/v1/resources/{name}/monitor", tags=["Resources"])
    async def monitor_resource(name: str):
        """Monitor a resource's health."""
        if name not in resource_manager._resources:
            raise HTTPException(status_code=404, detail=f"Resource {name} not found")

        result = await resource_manager.monitor_resource(name)
        return {"resource": name, "result": result.value}

    # --- Failover endpoints ---

    @app.post("/api/v1/failover/trigger", tags=["Failover"])
    async def trigger_failover(
        reason: str = "manual",
        target_node: Optional[str] = None,
    ):
        """Trigger a manual failover."""
        from simpleha.core.failover import FailoverReason

        reason_enum = FailoverReason.MANUAL
        if reason == "node_failure":
            reason_enum = FailoverReason.NODE_FAILURE

        active = cluster_manager.get_active_node()
        source = active.name if active else "unknown"

        event = await failover_manager.initiate_failover(
            reason=reason_enum,
            source_node=source,
            target_node=target_node,
        )

        if not event:
            raise HTTPException(status_code=400, detail="Failover already in progress")

        return {
            "message": "Failover initiated",
            "event_id": event.id,
            "source": source,
            "target": event.target_node,
        }

    @app.get("/api/v1/failover/history", tags=["Failover"])
    async def get_failover_history(limit: int = 20):
        """Get failover history."""
        return failover_manager.get_failover_history(limit=limit)

    # --- Monitor endpoints ---

    @app.get("/api/v1/monitor/dashboard", tags=["Monitor"])
    async def get_dashboard():
        """Get dashboard data (cluster + resources + failover)."""
        if hasattr(failover_manager, "cluster") and hasattr(
            failover_manager.cluster, "heartbeat"
        ):
            from datetime import timezone

            hb = failover_manager.cluster.heartbeat
            now = datetime.now(timezone.utc)
            nodes = {}
            for name, records in hb._records.items():
                last = records[-1] if records else None
                age = (now - last.timestamp).total_seconds() if last else None
                nodes[name] = {
                    "last_heartbeat": last.timestamp.isoformat() if last else None,
                    "age_seconds": round(age, 1) if age else None,
                    "missed_count": hb._missed_counts.get(name, 0),
                }
            return {"timestamp": now.isoformat(), "nodes": nodes}
        return {"message": "Heartbeat monitor not available"}

    return app


class HAAServer:
    """Manages the SimpleHA API server lifecycle."""

    def __init__(
        self,
        cluster_manager: Any,
        resource_manager: Any,
        failover_manager: Any,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        self.cluster = cluster_manager
        self.resources = resource_manager
        self.failover = failover_manager
        self.host = host
        self.port = port
        self._app = None
        self._server_task = None
        logger.info(f"HAAServer initialized: {host}:{port}")

    def start(self) -> None:
        """Start the API server."""
        if not FASTAPI_AVAILABLE:
            logger.error("Cannot start API server: FastAPI not installed")
            return

        self._app = create_app(self.cluster, self.resources, self.failover)
        if not self._app:
            return

        import uvicorn

        logger.info(f"Starting SimpleHA API at {self.host}:{self.port}")
        uvicorn.run(self._app, host=self.host, port=self.port, log_level="info")

    async def start_async(self) -> None:
        """Start the API server asynchronously (for use within asyncio)."""
        if not FASTAPI_AVAILABLE:
            logger.error("Cannot start API server: FastAPI not installed")
            return

        self._app = create_app(self.cluster, self.resources, self.failover)
        if not self._app:
            return

        import uvicorn

        config = uvicorn.Config(
            self._app, host=self.host, port=self.port, log_level="info"
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        logger.info(f"SimpleHA API started at {self.host}:{self.port}")

    def main(self) -> None:
        """Entry point for simpleha-api command."""
        import sys

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

        if not FASTAPI_AVAILABLE:
            logger.error(
                "FastAPI not installed. Install with: pip install 'simpleha[api]'"
            )
            sys.exit(1)

        # Load config and create managers (simplified for CLI entry point)
        logger.info("Starting SimpleHA API server...")
        self.start()


if __name__ == "__main__":
    server = HAAServer(None, None, None)
    server.main()
