"""Main CLI entry point for SimpleHA.

Provides a command-line interface similar to:
- `crm` (Pacemaker CLI)
- `hbcli` (RoseHA CLI)

Usage:
    simpleha status
    simpleha node list
    simpleha resource start <name>
    simpleha failover trigger [--target <node>]
"""

import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional

from simpleha.core.cluster import ClusterManager, ClusterConfig
from simpleha.core.config import ConfigManager
from simpleha.core.resource import ResourceManager, Resource, ResourceConfig
from simpleha.core.failover import FailoverManager, FailoverReason

logger = logging.getLogger(__name__)


def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point for CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    exit_code = args.func(args)
    sys.exit(exit_code or 0)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="simpleha",
        description="SimpleHA - Simplified High Availability Cluster Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", "-c", default="config/ha.yaml", help="Config file path"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(title="commands", dest="command")

    # Status command
    sp = subparsers.add_parser("status", help="Show cluster status")
    sp.set_defaults(func=cmd_status)

    # Node commands
    sp = subparsers.add_parser("node", help="Node management")
    node_sub = sp.add_subparsers(dest="node_cmd")
    sp_list = node_sub.add_parser("list", help="List nodes")
    sp_list.set_defaults(func=cmd_node_list)
    sp_add = node_sub.add_parser("add", help="Add a node")
    sp_add.add_argument("name")
    sp_add.add_argument("address")
    sp_add.set_defaults(func=cmd_node_add)
    sp_remove = node_sub.add_parser("remove", help="Remove a node")
    sp_remove.add_argument("name")
    sp_remove.set_defaults(func=cmd_node_remove)
    sp_standby = node_sub.add_parser("standby", help="Put node in standby")
    sp_standby.add_argument("name")
    sp_standby.set_defaults(func=cmd_node_standby)

    # Resource commands
    sp = subparsers.add_parser("resource", help="Resource management")
    res_sub = sp.add_subparsers(dest="res_cmd")
    sp_list = res_sub.add_parser("list", help="List resources")
    sp_list.set_defaults(func=cmd_resource_list)
    sp_start = res_sub.add_parser("start", help="Start a resource")
    sp_start.add_argument("name")
    sp_start.set_defaults(func=cmd_resource_start)
    sp_stop = res_sub.add_parser("stop", help="Stop a resource")
    sp_stop.add_argument("name")
    sp_stop.set_defaults(func=cmd_resource_stop)
    sp_monitor = res_sub.add_parser("monitor", help="Monitor a resource")
    sp_monitor.add_argument("name")
    sp_monitor.set_defaults(func=cmd_resource_monitor)

    # Failover commands
    sp = subparsers.add_parser("failover", help="Failover management")
    fo_sub = sp.add_subparsers(dest="fo_cmd")
    sp_trigger = fo_sub.add_parser("trigger", help="Trigger failover")
    sp_trigger.add_argument("--target", help="Target node for failover")
    sp_trigger.set_defaults(func=cmd_failover_trigger)
    sp_history = fo_sub.add_parser("history", help="Show failover history")
    sp_history.set_defaults(func=cmd_failover_history)

    # Config commands
    sp = subparsers.add_parser("config", help="Configuration management")
    cfg_sub = sp.add_subparsers(dest="cfg_cmd")
    sp_show = cfg_sub.add_parser("show", help="Show current config")
    sp_show.set_defaults(func=cmd_config_show)
    sp_validate = cfg_sub.add_parser("validate", help="Validate config")
    sp_validate.set_defaults(func=cmd_config_validate)
    sp_generate = cfg_sub.add_parser("generate", help="Generate sample config")
    sp_generate.add_argument("path", nargs="?", default="config/ha.yaml")
    sp_generate.set_defaults(func=cmd_config_generate)

    return parser


# --- Command handlers ---

def _load_cluster(args) -> tuple:
    """Load cluster from config file."""
    cfg_mgr = ConfigManager(args.config)
    try:
        config = cfg_mgr.load(args.config)
    except FileNotFoundError:
        logger.error(f"Config file not found: {args.config}")
        logger.error("Run: simpleha config generate")
        sys.exit(1)

    cluster = ClusterManager(config)
    for node_cfg in config.nodes:
        cluster.add_node(node_cfg.name, node_cfg.address, node_cfg.priority)

    resources = ResourceManager()
    failover = FailoverManager(cluster, resources, config)

    return cluster, resources, failover, config


def cmd_status(args) -> int:
    """Show cluster status."""
    cluster, resources, failover, config = _load_cluster(args)

    status = {
        "cluster": cluster.get_cluster_status(),
        "resources": resources.get_all_status(),
        "failover": failover.get_status(),
    }

    if args.json:
        print(json.dumps(status, indent=2, default=str))
    else:
        _print_status(cluster, resources, failover)

    return 0


def _print_status(cluster, resources, failover) -> None:
    """Print formatted cluster status."""
    cs = cluster.get_cluster_status()

    print(f"\n=== SimpleHA Cluster: {cs['cluster_name']} ===")
    print(f"Active Node: {cs['active_node'] or '(none)'}")
    print(f"Healthy Nodes: {cs['healthy_nodes']}/{cs['total_nodes']}")
    print()

    print("--- Nodes ---")
    for name, info in cs["nodes"].items():
        marker = "*" if name == cs["active_node"] else " "
        print(f"  {marker} {name:15s} {info['role']:10s} {info['status']:10s}")
    print()

    rs = resources.get_all_status()
    print("--- Resources ---")
    for name, info in rs["resources"].items():
        state_icon = {
            "running": "+",
            "stopped": "-",
            "failed": "!",
        }.get(info["state"], "?")
        print(
            f"  {state_icon} {name:15s} {info['state']:10s} @ {info['node'] or '-'}"
        )
    print()

    fs = failover.get_status()
    print(f"--- Failover History: {fs['total_failovers']} total ---")
    for event in failover.get_failover_history(5):
        print(
            f"  {event['timestamp'][:19]}  {event['reason']:20s}  "
            f"{event['source_node']} -> {event['target_node']}  [{event['status']}]"
        )
    print()


def cmd_node_list(args) -> int:
    """List cluster nodes."""
    cluster, _, _, _ = _load_cluster(args)
    status = cluster.get_cluster_status()

    if args.json:
        print(json.dumps(status["nodes"], indent=2))
    else:
        for name, info in status["nodes"].items():
            print(f"{name:15s} {info['role']:10s} {info['status']:10s} {info['address']}")

    return 0


def cmd_node_add(args) -> int:
    """Add a node to the cluster."""
    cfg_mgr = ConfigManager(args.config)
    config = cfg_mgr.load(args.config)

    config.nodes.append(
        NodeConfig(name=args.name, address=args.address, priority=1)
    )

    errors = cfg_mgr.validate()
    if errors:
        for e in errors:
            logger.error(e)
        return 1

    cfg_mgr.save(args.config)
    logger.info(f"Added node {args.name} at {args.address}")
    return 0


def cmd_node_remove(args) -> int:
    """Remove a node from the cluster."""
    cfg_mgr = ConfigManager(args.config)
    config = cfg_mgr.load(args.config)

    config.nodes = [n for n in config.nodes if n.name != args.name]

    cfg_mgr.save(args.config)
    logger.info(f"Removed node: {args.name}")
    return 0


def cmd_node_standby(args) -> int:
    """Put a node into standby mode."""
    print(f"(Simulated) Node {args.name} put into standby mode")
    print("In a real cluster, this would use the running cluster API.")
    return 0


def cmd_resource_list(args) -> int:
    """List resources."""
    _, resources, _, _ = _load_cluster(args)
    status = resources.get_all_status()

    if args.json:
        print(json.dumps(status, indent=2, default=str))
    else:
        for name, info in status["resources"].items():
            print(f"{name:15s} {info['type']:12s} {info['state']:10s}")

    return 0


def cmd_resource_start(args) -> int:
    """Start a resource."""
    print(f"(Simulated) Starting resource: {args.name}")
    print("In a real cluster, this would call the resource agent.")
    return 0


def cmd_resource_stop(args) -> int:
    """Stop a resource."""
    print(f"(Simulated) Stopping resource: {args.name}")
    return 0


def cmd_resource_monitor(args) -> int:
    """Monitor a resource."""
    _, resources, _, _ = _load_cluster(args)
    status = resources.get_resource_status(args.name)

    if not status:
        logger.error(f"Resource not found: {args.name}")
        return 1

    if args.json:
        print(json.dumps(status, indent=2, default=str))
    else:
        print(f"Resource: {status['name']}")
        print(f"Type:     {status['type']}")
        print(f"State:    {status['state']}")
        print(f"Node:     {status['node'] or '-'}")

    return 0


def cmd_failover_trigger(args) -> int:
    """Trigger a failover."""
    _, _, failover, _ = _load_cluster(args)

    cluster = failover.cluster
    active = cluster.get_active_node()
    source = active.name if active else "(none)"

    print(f"Triggering failover: {source} -> {args.target or '(auto)'}")
    print("(Simulated) In a real cluster, this would execute failover.")

    return 0


def cmd_failover_history(args) -> int:
    """Show failover history."""
    _, _, failover, _ = _load_cluster(args)
    history = failover.get_failover_history()

    if args.json:
        print(json.dumps(history, indent=2, default=str))
    else:
        for event in history:
            print(
                f"{event['id']}  {event['timestamp'][:19]}  "
                f"{event['reason']:20s}  {event['status']}"
            )

    return 0


def cmd_config_show(args) -> int:
    """Show current configuration."""
    cfg_mgr = ConfigManager(args.config)
    config = cfg_mgr.load(args.config)

    if args.json:
        print(json.dumps(config.model_dump(), indent=2, default=str))
    else:
        print(f"Cluster: {config.cluster_name}")
        print(f"Heartbeat: {config.heartbeat_interval}s / {config.heartbeat_timeout}s")
        print(f"STONITH: {'enabled' if config.stonith_enabled else 'disabled'}")
        print(f"Nodes: {len(config.nodes)}")
        for n in config.nodes:
            print(f"  - {n.name} ({n.address}) priority={n.priority}")
        print(f"Resources: {len(config.resources)}")
        for r in config.resources:
            print(f"  - {r.name} ({r.type})")

    return 0


def cmd_config_validate(args) -> int:
    """Validate configuration."""
    cfg_mgr = ConfigManager(args.config)
    config = cfg_mgr.load(args.config)

    errors = cfg_mgr.validate()
    if errors:
        logger.error("Configuration validation FAILED:")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1
    else:
        print("Configuration is valid.")
        return 0


def cmd_config_generate(args) -> int:
    """Generate a sample configuration file."""
    ConfigManager.generate_sample(args.path)
    print(f"Sample configuration generated at: {args.path}")
    return 0


if __name__ == "__main__":
    main()
