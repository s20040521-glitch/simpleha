# SimpleHA - Simplified High Availability Cluster Manager

<p align="center">
  <img src="docs/images/simpleha-logo.png" alt="SimpleHA" width="200"/>
</p>

<p align="center">
  <strong>Inspired by Pacemaker / RoseHA patterns</strong>
  <br>
  Modern Python implementation for active/passive HA clusters
</p>

<p align="center">
  <a href="https://github.com/your-org/simpleha/actions/workflows/ci.yml">
    <img src="https://github.com/your-org/simpleha/workflows/CI/CD%20Pipeline/badge.svg" alt="CI Status"/>
  </a>
  <a href="https://pypi.org/project/simpleha/">
    <img src="https://img.shields.io/pypi/v/simpleha.svg" alt="PyPI Version"/>
  </a>
  <a href="https://pypi.org/project/simpleha/">
    <img src="https://img.shields.io/pypi/pyversions/simpleha.svg" alt="Python Versions"/>
  </a>
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License"/>
  </a>
</p>

---

## Overview

SimpleHA is a **simplified high availability cluster manager** inspired by [Pacemaker](https://github.com/ClusterLabs/pacemaker) and [RoseHA](https://www.roseha.com/) patterns. It provides an active/passive HA solution with modern Python implementation.

### Key Features

- **Active/Passive Clustering**: Automatic failover between nodes
- **Resource Management**: IP addresses, filesystems, services, custom resources
- **Heartbeat Monitoring**: Real-time node health detection
- **STONITH/Fencing**: Prevents split-brain scenarios
- **Quorum/Arbitration Disk**: Disk-based quorum for split-brain prevention
- **REST API**: Full cluster management via HTTP
- **CLI Tools**: Command-line cluster management
- **Docker Support**: Containerized deployment
- **CI/CD Pipeline**: Automated testing and deployment

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        SimpleHA                             │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │    CLI      │  │  REST API   │  │  Monitor Service │    │
│  └─────────────┘  └─────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐    │
│  │              ClusterManager (Core)                   │    │
│  ├──────────────┬───────────────┬────────────────────┤    │
│  │ Heartbeat    │ Failover      │ Quorum             │    │
│  │ Monitor      │ Manager       │ Manager            │    │
│  └──────────────┴───────────────┴────────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │  IP Agent   │  │ Service     │  │ Filesystem      │    │
│  │             │  │ Agent       │  │ Agent           │    │
│  └─────────────┘  └─────────────┘  └─────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│           ┌─────────────────────────────┐                  │
│           │   Arbitration Disk (iSCSI)  │                  │
│           │   Split-Brain Prevention     │                  │
│           └─────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

## Installation

### RHEL 8.5 / CentOS Stream 8 (Recommended)

详细部署指南请查看: [部署文档](./docs/deployment/rhel8-deployment.md)

**一键安装脚本:**

```bash
# 下载并运行安装脚本
curl -O https://raw.githubusercontent.com/s20040521-glitch/simpleha/main/scripts/install_rhel8.sh
chmod +x install_rhel8.sh
sudo ./install_rhel8.sh
```

**手动安装:**

```bash
# 1. 安装依赖
sudo dnf install -y gcc python39-devel python39-pip libffi-devel openssl-devel

# 2. 安装 SimpleHA
python3.9 -m pip install simpleha

# 3. 生成配置
simpleha config generate /etc/simpleha/ha.yaml
```

### From PyPI

```bash
pip install simpleha
```

### From Source

```bash
git clone https://github.com/s20040521-glitch/simpleha.git
cd simpleha
pip install -e .
```

### Docker

```bash
# Pull from GitHub Container Registry
docker pull ghcr.io/s20040521-glitch/simpleha:latest

# Or build locally
docker build -t simpleha:latest .
```

## Quick Start

### 1. Create Configuration

```bash
# Generate sample configuration
simpleha config generate config/ha.yaml

# Edit configuration
vim config/ha.yaml
```

### 2. Start Cluster

```bash
# Start as daemon
simpleha start --config config/ha.yaml

# Or use Docker Compose
docker-compose up -d
```

### 3. Check Status

```bash
# CLI status
simpleha status

# REST API
curl http://localhost:8080/api/v1/cluster/status
```

### 4. Manage Resources

```bash
# List resources
simpleha resource list

# Start a resource
simpleha resource start web-service

# Stop a resource
simpleha resource stop web-service
```

## Configuration

```yaml
cluster_name: "simpleha-cluster"
cluster_id: "ha-001"

nodes:
  - name: "node1"
    address: "192.168.1.10"
    priority: 2

  - name: "node2"
    address: "192.168.1.11"
    priority: 1

resources:
  - name: "float-ip"
    type: "ip"
    agent: "simpleha.agents.ip:IPAgent"
    params:
      ip: "192.168.1.100"
      netmask: "24"

  - name: "web-service"
    type: "service"
    agent: "simpleha.agents.service:ServiceAgent"
    params:
      service_name: "nginx"

heartbeat_interval: 2.0
stonith_enabled: true
api_enabled: true
api_port: 8080
```

## Quorum and Arbitration Disk

SimpleHA supports **disk-based quorum** to prevent split-brain scenarios in HA clusters.

### How It Works

```
┌──────────────┐         ┌──────────────┐
│    Node 1    │         │    Node 2    │
│   (Active)   │   ???   │  (Passive)   │
└──────┬───────┘         └──────┬───────┘
       │                         │
       │    ┌───────────────────┘
       │    │
       ▼    ▼
┌─────────────────────┐
│  Arbitration Disk   │
│   (Shared Storage)  │
│  iSCSI / FC / NFS  │
└─────────────────────┘
```

1. All nodes write heartbeat markers to the shared arbitration disk
2. Nodes monitor disk accessibility in real-time
3. When quorum is lost (disk offline or insufficient votes), resources stop
4. Nodes without quorum access are fenced via STONITH

### Configuration

```yaml
# Quorum settings
quorum_required: true
expected_votes: 2
votes_needed: 2

# Arbitration disk (optional but recommended for 2-node)
arb_disk_enabled: true
arb_disk_device: "/dev/sdb"          # Shared storage device
arb_disk_type: "iscsi"               # iscsi, fc, nfs, rbd
arb_disk_timeout: 5.0                # Disk operation timeout (seconds)
arb_disk_interval: 2.0               # Heartbeat interval to disk
arb_fence_delay: 0.0                 # Delay before fencing (seconds)
```

### Two-Node Optimistic Mode

For 2-node clusters, you can enable optimistic mode:

```yaml
two_node_optimistic: true
votes_needed: 1
```

This allows single-node operation when the other node is unreachable, but requires careful configuration to avoid split-brain.

### Quorum States

| State | Description | Action |
|-------|-------------|--------|
| `HAS_QUORUM` | Cluster has sufficient votes | Normal operation |
| `NO_QUORUM` | Not enough votes | Resources stop, fencing possible |
| `LOST` | Quorum completely lost | Emergency shutdown |
| `UNKNOWN` | Quorum state unclear | Wait for stabilization |

## CLI Reference

| Command | Description |
|---------|-------------|
| `simpleha status` | Show cluster status |
| `simpleha node list` | List cluster nodes |
| `simpleha node add <name> <address>` | Add a node |
| `simpleha resource list` | List resources |
| `simpleha resource start <name>` | Start a resource |
| `simpleha resource stop <name>` | Stop a resource |
| `simpleha failover trigger` | Trigger failover |
| `simpleha config show` | Show configuration |

## REST API

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/cluster/status` | Cluster status |
| GET | `/api/v1/cluster/nodes` | List nodes |
| POST | `/api/v1/cluster/nodes` | Add node |
| DELETE | `/api/v1/cluster/nodes/{name}` | Remove node |
| GET | `/api/v1/quorum/status` | Quorum status |
| GET | `/api/v1/quorum/info` | Detailed quorum info |
| GET | `/api/v1/quorum/has_quorum` | Check quorum availability |
| GET | `/api/v1/resources` | List resources |
| GET | `/api/v1/resources/{name}` | Resource details |
| POST | `/api/v1/resources/{name}/start` | Start resource |
| POST | `/api/v1/resources/{name}/stop` | Stop resource |
| POST | `/api/v1/failover/trigger` | Trigger failover |
| GET | `/api/v1/failover/history` | Failover history |

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/your-org/simpleha.git
cd simpleha

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Format code
black src/ tests/
ruff check --fix src/ tests/
```

### CI/CD Pipeline

The project uses GitHub Actions for CI/CD:

1. **Code Quality**: Black, Ruff, MyPy
2. **Security**: Bandit, Safety dependency scan
3. **Unit Tests**: pytest with coverage
4. **Integration Tests**: Full cluster simulation
5. **Build**: Python package + Docker image
6. **Deploy**: Blue-green deployment to staging/production

## Architecture Comparison

| Feature | Pacemaker | RoseHA | SimpleHA |
|---------|-----------|--------|----------|
| Language | C | C/C++ | Python |
| Complexity | High | Medium | Low |
| Active/Active | ✓ | - | - |
| Active/Passive | ✓ | ✓ | ✓ |
| Resource Agents | OCF | Custom | Python Agents |
| CLI | crm/sh | Proprietary | simpleha CLI |
| REST API | Limited | Limited | Full REST |
| Learning Curve | Steep | Medium | Easy |

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest tests/`
5. Submit a pull request

## References

- [Pacemaker Documentation](https://clusterlabs.org/pacemaker/)
- [RoseHA Documentation](https://www.roseha.com/)
- [OCF Resource Agent Standard](https://clusterlabs.org/ocf/)
