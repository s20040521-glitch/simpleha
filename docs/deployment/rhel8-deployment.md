# SimpleHA RHEL 8.5 手动部署指南

本文档详细说明如何在 Red Hat Enterprise Linux 8.5 上手动部署 SimpleHA 高可用集群管理器。

## 目录

- [环境要求](#环境要求)
- [准备工作](#准备工作)
- [安装依赖](#安装依赖)
- [部署 SimpleHA](#部署-simpleha)
- [配置集群](#配置集群)
- [验证部署](#验证部署)
- [启动服务](#启动服务)
- [卸载步骤](#卸载步骤)

---

## 环境要求

### 硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|----------|----------|
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 20 GB | 50 GB+ |
| 网络 | 1 Gbps | 10 Gbps |

### 软件要求

- **操作系统**: RHEL 8.5 / CentOS Stream 8 / Rocky Linux 8
- **Python**: 3.9+
- **Red Hat 订阅**: 有效订阅（用于获取仓库）

### 网络规划

```
+------------------+         +------------------+
|     Node 1       |         |     Node 2       |
| 192.168.1.10/24  |<------>| 192.168.1.11/24  |
|    (Active)      |  心跳   |    (Passive)     |
+------------------+         +------------------+
         |                           |
         |    +-------------------+  |
         +----|  Shared Storage   |---+
              |  (仲裁盘/iSCSI)   |
              |  /dev/sdb         |
              +-------------------+
```

---

## 准备工作

### 1. 注册 RHEL 订阅（如果尚未注册）

```bash
# 注册系统
sudo subscription-manager register --username=<用户名> --password=<密码>

# 列出可用订阅
sudo subscription-manager list --available

# 附加订阅（根据你的订阅类型）
sudo subscription-manager attach --pool=<订阅池ID>
```

### 2. 启用必要的仓库

```bash
# 启用 RHEL 基础仓库
sudo subscription-manager repos \
    --enable=rhel-8-for-x86_64-baseos-rpms \
    --enable=rhel-8-for-x86_64-appstream-rpms \
    --enable=codeready-builder-for-rhel-8-x86_64-rpms

# 验证仓库已启用
sudo dnf repolist
```

**预期输出:**
```
repo id                            repo name
rhel-8-for-x86_64-baseos-rpms      Red Hat Enterprise Linux 8.5 - BaseOS
rhel-8-for-x86_64-appstream-rpms  Red Hat Enterprise Linux 8.5 - AppStream
codeready-builder-for-rhel-8-x86_64-rpms CodeReady Builder for RHEL 8
```

### 3. 关闭 SELinux 和防火墙（测试环境）

```bash
# 临时关闭（立即生效）
sudo setenforce 0

# 永久关闭（重启后生效）
sudo sed -i 's/^SELINUX=enforcing$/SELINUX=disabled/' /etc/selinux/config

# 停止并禁用防火墙
sudo systemctl stop firewalld
sudo systemctl disable firewalld
```

**注意**: 生产环境请配置正确的 SELinux 策略和防火墙规则。

### 4. 同步时间（NTP）

```bash
# 安装 chrony
sudo dnf install -y chrony

# 启动并启用 chrony
sudo systemctl enable --now chronyd

# 验证时间同步
chronyc sources
```

### 5. 配置 hosts 文件

```bash
# 在所有节点上执行
sudo tee -a /etc/hosts <<EOF

# SimpleHA Cluster Nodes
192.168.1.10  node1 simpleha-node1
192.168.1.11  node2 simpleha-node2

# Floating IP (集群 VIP)
192.168.1.100 simpleha-vip
EOF

# 验证网络连通性
ping -c 3 node1
ping -c 3 node2
```

---

## 安装依赖

### 1. 安装基础开发工具

```bash
sudo dnf groupinstall -y "Development Tools"
```

### 2. 安装 Python 和相关依赖

```bash
# 安装 Python 3.9 和开发工具
sudo dnf install -y \
    python39 \
    python39-devel \
    python39-pip \
    python39-virtualenv

# 升级 pip
python3.9 -m pip install --upgrade pip setuptools wheel
```

### 3. 安装系统依赖库

```bash
sudo dnf install -y \
    gcc \
    gcc-c++ \
    make \
    libffi-devel \
    openssl-devel \
    krb5-devel \
    zlib-devel \
    bzip2 \
    bzip2-devel \
    libuuid-devel \
    curl \
    git \
    redis
```

### 4. 验证 Python 版本

```bash
python3.9 --version
```

**预期输出:**
```
Python 3.9.x
```

### 5. 配置 Python 虚拟环境（推荐）

```bash
# 创建应用目录
sudo mkdir -p /opt/simpleha
sudo chown $USER:$USER /opt/simpleha

# 创建虚拟环境
python3.9 -m venv /opt/simpleha/venv

# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 升级基础包
pip install --upgrade pip setuptools wheel
```

---

## 部署 SimpleHA

### 方式一：从 PyPI 安装（推荐）

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 安装 SimpleHA
pip install simpleha
```

### 方式二：从 GitHub 安装最新版本

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 从 GitHub 安装
pip install git+https://github.com/s20040521-glitch/simpleha.git
```

### 方式三：从源码安装（开发用）

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 克隆源码（如果还没有）
git clone https://github.com/s20040521-glitch/simpleha.git /tmp/simpleha

# 安装（包含开发依赖）
cd /tmp/simpleha
pip install -e ".[dev]"
```

### 4. 验证安装

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 验证 CLI
simpleha --version

# 预期输出类似:
# SimpleHA version 1.0.0
```

---

## 配置集群

### 1. 创建配置目录

```bash
# 创建配置目录
sudo mkdir -p /etc/simpleha
sudo mkdir -p /var/log/simpleha
sudo mkdir -p /var/run/simpleha

# 设置权限
sudo chown -R $USER:$USER /etc/simpleha
sudo chown -R $USER:$USER /var/log/simpleha
sudo chown -R $USER:$USER /var/run/simpleha
```

### 2. 生成示例配置

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 生成默认配置
simpleha config generate /etc/simpleha/ha.yaml

# 查看配置
cat /etc/simpleha/ha.yaml
```

### 3. 编辑配置文件

```bash
vim /etc/simpleha/ha.yaml
```

**完整配置示例:**

```yaml
# 集群基本信息
cluster_name: "simpleha-cluster"
cluster_id: "ha-001"

# 节点配置
nodes:
  - name: "node1"
    address: "192.168.1.10"
    port: 8081
    priority: 2

  - name: "node2"
    address: "192.168.1.11"
    port: 8081
    priority: 1

# 心跳配置
heartbeat_interval: 2.0
heartbeat_timeout: 10.0

# 资源定义
resources:
  - name: "float-ip"
    type: "ip"
    agent: "simpleha.agents.ip:IPAgent"
    params:
      ip: "192.168.1.100"
      netmask: "24"
      interface: "eth0"

  - name: "shared-filesystem"
    type: "filesystem"
    agent: "simpleha.agents.filesystem:FilesystemAgent"
    params:
      device: "/dev/sdb1"
      mount_point: "/data"
      fstype: "xfs"

  - name: "nginx-service"
    type: "service"
    agent: "simpleha.agents.service:ServiceAgent"
    params:
      service_name: "nginx"

# STONITH/Fencing 配置
stonith_enabled: true
stonith_timeout: 30

# 仲裁盘配置（可选但推荐）
quorum_required: true
expected_votes: 2
votes_needed: 2

arb_disk_enabled: true
arb_disk_device: "/dev/sdb"
arb_disk_type: "iscsi"
arb_disk_timeout: 5.0
arb_disk_interval: 2.0

# API 配置
api_enabled: true
api_host: "0.0.0.0"
api_port: 8080
```

### 4. 配置仲裁盘（iSCSI）

如果使用 iSCSI 存储作为仲裁盘：

```bash
# 安装 iSCSI 客户端
sudo dnf install -y iscsi-initiator-utils device-mapper-multipath

# 启动 iSCSI 服务
sudo systemctl enable --now iscsi iscsid

# 发现 iSCSI 存储
# 替换 <iSCSI_TARGET_IP> 为实际的目标地址
sudo iscsiadm -m discovery -t sendtargets -p <iSCSI_TARGET_IP>:3260

# 登录 iSCSI 存储
sudo iscsiadm -m node -L all

# 验证设备
lsblk
sudo fdisk -l | grep -i iscsi
```

---

## 验证部署

### 1. 运行单元测试

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 运行测试
pytest /opt/simpleha/venv/lib/python3.9/site-packages/simpleha/tests/ -v
```

### 2. 验证 CLI 功能

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 查看帮助
simpleha --help

# 查看版本
simpleha --version

# 验证配置
simpleha config show --config /etc/simpleha/ha.yaml
```

### 3. 验证 Python 模块

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

python3 << 'EOF'
from simpleha.core.cluster import ClusterManager
from simpleha.core.quorum import QuorumManager
from simpleha.api.server import app

print("SimpleHA modules loaded successfully!")
print(f"ClusterManager: {ClusterManager}")
print(f"QuorumManager: {QuorumManager}")
print(f"APIServer: {app}")
EOF
```

---

## 启动服务

### 1. 启动 API 服务

```bash
# 激活虚拟环境
source /opt/simpleha/venv/bin/activate

# 前台运行（测试用）
simpleha-api --config /etc/simpleha/ha.yaml

# 或者后台运行
nohup simpleha-api --config /etc/simpleha/ha.yaml > /var/log/simpleha/api.log 2>&1 &
```

### 2. 创建 systemd 服务（推荐）

```bash
# 创建服务文件
sudo tee /etc/systemd/system/simpleha-api.service <<'EOF'
[Unit]
Description=SimpleHA API Server
After=network.target redis.service
Wants=redis.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/simpleha
Environment="PATH=/opt/simpleha/venv/bin"
ExecStart=/opt/simpleha/venv/bin/simpleha-api --config /etc/simpleha/ha.yaml
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 重新加载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl enable --now simpleha-api

# 检查服务状态
sudo systemctl status simpleha-api
```

### 3. 验证服务运行

```bash
# 检查进程
ps aux | grep simpleha

# 测试 API
curl http://localhost:8080/health

# 查看集群状态
curl http://localhost:8080/api/v1/cluster/status
```

### 4. 配置开机自启

```bash
# 确保服务已启用
sudo systemctl enable simpleha-api

# 确保 redis 已启用
sudo systemctl enable redis

# 如果使用 iSCSI
sudo systemctl enable iscsi iscsid
```

---

## 防火墙配置（生产环境）

如果需要开启防火墙：

```bash
# 开放 SimpleHA API 端口
sudo firewall-cmd --permanent --add-port=8080/tcp

# 开放集群节点间通信端口
sudo firewall-cmd --permanent --add-port=8081/tcp

# 重新加载防火墙
sudo firewall-cmd --reload

# 验证规则
sudo firewall-cmd --list-all
```

---

## 卸载步骤

```bash
# 1. 停止服务
sudo systemctl stop simpleha-api

# 2. 禁用服务
sudo systemctl disable simpleha-api

# 3. 删除 systemd 服务文件
sudo rm /etc/systemd/system/simpleha-api.service
sudo systemctl daemon-reload

# 4. 删除配置和数据
sudo rm -rf /etc/simpleha
sudo rm -rf /var/log/simpleha
sudo rm -rf /var/run/simpleha

# 5. 删除虚拟环境
sudo rm -rf /opt/simpleha

# 6. 卸载 Python 包（如果直接安装）
pip uninstall simpleha -y
```

---

## 故障排查

### 常见问题

#### 1. Python 版本问题

```bash
# 检查 Python 版本
python3.9 --version

# 如果遇到 "Python 3.9 not found"
sudo alternatives --set python3 /usr/bin/python3.9
```

#### 2. 编译错误

```bash
# 确保安装所有开发依赖
sudo dnf install -y gcc python39-devel libffi-devel openssl-devel

# 清理后重试
pip uninstall simpleha -y
pip install simpleha --no-cache-dir
```

#### 3. 权限问题

```bash
# 检查目录权限
ls -la /etc/simpleha
ls -la /var/log/simpleha
ls -la /var/run/simpleha

# 修复权限
sudo chown -R $USER:$USER /etc/simpleha
sudo chown -R $USER:$USER /var/log/simpleha
sudo chown -R $USER:$USER /var/run/simpleha
```

#### 4. iSCSI 连接问题

```bash
# 检查 iSCSI 服务状态
sudo systemctl status iscsi iscsid

# 检查 iSCSI 节点
sudo iscsiadm -m node

# 重新登录
sudo iscsiadm -m node -L all
```

#### 5. 查看日志

```bash
# API 日志
tail -f /var/log/simpleha/api.log

# systemd 日志
journalctl -u simpleha-api -f

# 系统日志
dmesg | grep -i error
```

---

## 下一步

- [配置仲裁盘](./quorum-configuration.md)
- [部署集群节点](./cluster-deployment.md)
- [配置 STONITH](./stonith-configuration.md)
- [使用 REST API](./api-reference.md)

---

**文档版本**: 1.0.0
**最后更新**: 2026-05-17
**适用版本**: SimpleHA 1.0.0+
