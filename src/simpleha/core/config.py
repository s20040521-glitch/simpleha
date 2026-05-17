"""Configuration management for SimpleHA.

Handles loading, validation, and hot-reloading of cluster configuration.
Supports YAML and JSON formats with schema validation.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


class ResourceConfig(BaseModel):
    """Configuration for a cluster resource."""

    name: str = Field(..., description="Unique resource name")
    type: str = Field(..., description="Resource type (ip, filesystem, service)")
    agent: str = Field(..., description="Resource agent to use")
    params: Dict[str, Any] = Field(default_factory=dict, description="Resource parameters")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Resource meta-attributes")
    operations: Dict[str, int] = Field(
        default_factory=lambda: {"start": 20, "stop": 20, "monitor": 10},
        description="Operation timeouts in seconds",
    )
    priority: int = Field(default=100, description="Resource priority for ordering")


class ResourceGroupConfig(BaseModel):
    """Configuration for a resource group."""

    name: str = Field(..., description="Resource group name")
    resources: List[str] = Field(..., description="Ordered list of resource names")
    ordered: bool = Field(default=True, description="Start/stop resources in order")
    collocated: bool = Field(default=True, description="Keep resources on same node")


class NodeConfig(BaseModel):
    """Configuration for a cluster node."""

    name: str = Field(..., description="Node hostname")
    address: str = Field(..., description="Node IP address or FQDN")
    priority: int = Field(default=1, description="Node priority (higher = preferred)")
    attributes: Dict[str, str] = Field(default_factory=dict, description="Node attributes")


class HAConfig(BaseModel):
    """Main SimpleHA configuration with full validation."""

    cluster_name: str = Field(..., description="Unique cluster name")
    cluster_id: str = Field(default_factory=lambda: "ha-" + os.urandom(4).hex())
    nodes: List[NodeConfig] = Field(default_factory=list)
    resources: List[ResourceConfig] = Field(default_factory=list)
    resource_groups: List[ResourceGroupConfig] = Field(default_factory=list)

    # Cluster behavior
    heartbeat_interval: float = Field(default=2.0, ge=0.5, le=60.0)
    heartbeat_timeout: float = Field(default=10.0, ge=2.0, le=300.0)
    failover_timeout: float = Field(default=30.0, ge=5.0, le=600.0)
    stonith_enabled: bool = Field(default=True)
    quorum_required: bool = Field(default=True)
    resource_stickiness: int = Field(default=100, ge=0)

    # Quorum settings
    expected_votes: int = Field(default=2, ge=1, le=256)
    votes_needed: int = Field(default=2, ge=1, le=256)
    two_node_optimistic: bool = Field(default=False)

    # Arbitration disk settings
    arb_disk_enabled: bool = Field(default=False)
    arb_disk_device: str = Field(default="", description="e.g., /dev/sdb or iqn.xxx")
    arb_disk_type: str = Field(default="iscsi", description="iscsi, fc, nfs, rbd")
    arb_disk_timeout: float = Field(default=5.0, ge=1.0, le=60.0)
    arb_disk_interval: float = Field(default=2.0, ge=0.5, le=30.0)
    arb_heuristic_enabled: bool = Field(default=False)
    arb_heuristic_score: int = Field(default=100, ge=0, le=1000)
    arb_fence_delay: float = Field(default=0.0, ge=0.0, le=300.0)

    # Monitoring
    monitor_enabled: bool = Field(default=True)
    monitor_interval: int = Field(default=60, ge=10, le=3600)
    log_level: str = Field(default="INFO")

    # API
    api_enabled: bool = Field(default=True)
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080, ge=1024, le=65535)

    @validator("log_level")
    def validate_log_level(cls, v):
        valid = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid:
            raise ValueError(f"Invalid log level: {v}, must be one of {valid}")
        return v.upper()

    class Config:
        use_enum_values = True
        validate_assignment = True


class ConfigManager:
    """Manages SimpleHA configuration with hot-reload support."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else None
        self.config: Optional[HAConfig] = None
        self._watchers: list = []

    def load(self, path: Optional[str] = None) -> HAConfig:
        """Load configuration from file."""
        target = Path(path) if path else self.config_path
        if not target:
            raise ValueError("No config path specified")
        if not target.exists():
            raise FileNotFoundError(f"Config file not found: {target}")

        content = target.read_text(encoding="utf-8")
        if target.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        elif target.suffix == ".json":
            data = json.loads(content)
        else:
            raise ValueError(f"Unsupported config format: {target.suffix}")

        self.config = HAConfig(**data)
        logger.info(f"Loaded config from {target}: cluster={self.config.cluster_name}")
        return self.config

    def save(self, path: Optional[str] = None) -> None:
        """Save configuration to file."""
        if not self.config:
            raise ValueError("No config to save")
        target = Path(path) if path else self.config_path
        if not target:
            raise ValueError("No config path specified")

        target.parent.mkdir(parents=True, exist_ok=True)
        data = self.config.model_dump()

        if target.suffix in (".yaml", ".yml"):
            target.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
        elif target.suffix == ".json":
            target.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            raise ValueError(f"Unsupported config format: {target.suffix}")

        logger.info(f"Saved config to {target}")

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = []
        if not self.config:
            return ["No configuration loaded"]

        # Check node names are unique
        node_names = [n.name for n in self.config.nodes]
        if len(node_names) != len(set(node_names)):
            errors.append("Duplicate node names detected")

        # Check resource names are unique
        resource_names = [r.name for r in self.config.resources]
        if len(resource_names) != len(set(resource_names)):
            errors.append("Duplicate resource names detected")

        # Check resource group references
        all_resources = set(resource_names)
        for rg in self.config.resource_groups:
            for r in rg.resources:
                if r not in all_resources:
                    errors.append(f"Resource group '{rg.name}' references unknown resource: {r}")

        return errors

    @classmethod
    def generate_sample(cls, path: str) -> None:
        """Generate a sample configuration file."""
        sample = {
            "cluster_name": "simpleha-demo",
            "nodes": [
                {"name": "node1", "address": "192.168.1.10", "priority": 2},
                {"name": "node2", "address": "192.168.1.11", "priority": 1},
            ],
            "resources": [
                {
                    "name": "float-ip",
                    "type": "ip",
                    "agent": "simpleha.agents.ip:IPAgent",
                    "params": {"ip": "192.168.1.100", "netmask": "24"},
                },
                {
                    "name": "web-service",
                    "type": "service",
                    "agent": "simpleha.agents.service:ServiceAgent",
                    "params": {"service_name": "nginx"},
                },
            ],
            "heartbeat_interval": 2.0,
            "stonith_enabled": True,
            "api_enabled": True,
            "api_port": 8080,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(yaml.dump(sample, default_flow_style=False, allow_unicode=True))
        logger.info(f"Generated sample config at {path}")
