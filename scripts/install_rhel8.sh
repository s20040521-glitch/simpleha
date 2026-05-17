#!/bin/bash
#===============================================================================
# SimpleHA RHEL 8.5 一键安装脚本
#
# 用法:
#   chmod +x install_rhel8.sh
#   ./install_rhel8.sh
#
# 作者: DevOps Automation Team
# 版本: 1.0.0
# 日期: 2026-05-17
#===============================================================================

set -e  # 遇到错误立即退出
set -u  # 使用未定义的变量时报错

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否以 root 运行
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本必须以 root 用户运行"
        echo "请使用: sudo $0"
        exit 1
    fi
}

# 检查 RHEL 版本
check_rhel_version() {
    if [[ -f /etc/redhat-release ]]; then
        local version=$(cat /etc/redhat-release | grep -oE '[0-9]+\.[0-9]+' | head -1)
        log_info "检测到 RHEL/CentOS 版本: $version"

        if [[ "$version" != "8."* ]]; then
            log_warning "此脚本针对 RHEL/CentOS 8.x 优化，其他版本可能需要调整"
        fi
    else
        log_warning "无法检测系统版本"
    fi
}

# 注册 RHEL 订阅
register_subscription() {
    if ! subscription-manager status &>/dev/null; then
        log_info "需要注册 RHEL 订阅..."
        read -p "请输入用户名: " username
        read -sp "请输入密码: " password
        echo

        subscription-manager register --username="$username" --password="$password"
        subscription-manager refresh

        log_success "订阅注册成功"
    else
        log_info "系统已注册 RHEL 订阅"
    fi
}

# 启用仓库
enable_repos() {
    log_info "启用 RHEL 8 仓库..."

    subscription-manager repos \
        --enable=rhel-8-for-x86_64-baseos-rpms \
        --enable=rhel-8-for-x86_64-appstream-rpms \
        --enable=codeready-builder-for-rhel-8-x86_64-rpms 2>/dev/null || true

    # 如果是 CentOS Stream 或其他变体，使用 dnf config-manager
    if ! subscription-manager repos --list-enabled 2>/dev/null | grep -q "rhel-8"; then
        log_info "检测到非标准 RHEL，使用 dnf 配置..."
        dnf config-manager --set-enabled rhel-8-for-x86_64-baseos-rpms 2>/dev/null || true
        dnf config-manager --set-enabled rhel-8-for-x86_64-appstream-rpms 2>/dev/null || true
    fi

    dnf makecache
    log_success "仓库配置完成"
}

# 安装基础依赖
install_base_deps() {
    log_info "安装基础依赖包..."

    dnf install -y \
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
        redis \
        iscsi-initiator-utils \
        device-mapper-multipath \
        nfs-utils \
        chrony

    log_success "基础依赖安装完成"
}

# 安装 Python
install_python() {
    log_info "安装 Python 3.9..."

    dnf module reset python39 2>/dev/null || true
    dnf module enable python39:3.9 -y 2>/dev/null || true

    dnf install -y \
        python39 \
        python39-devel \
        python39-pip \
        python39-virtualenv \
        python39-psycopg2

    # 升级 pip
    python3.9 -m pip install --upgrade pip setuptools wheel

    log_success "Python 3.9 安装完成"
    python3.9 --version
}

# 创建应用目录和虚拟环境
setup_app_directory() {
    log_info "创建应用目录..."

    APP_DIR="/opt/simpleha"
    USER_HOME=$(eval echo ~${SUDO_USER:-$(whoami)})
    APP_USER="${SUDO_USER:-$(whoami)}"

    # 创建目录
    mkdir -p "$APP_DIR"
    mkdir -p /etc/simpleha
    mkdir -p /var/log/simpleha
    mkdir -p /var/run/simpleha

    # 创建虚拟环境
    python3.9 -m venv "$APP_DIR/venv"

    # 设置权限
    chown -R "$APP_USER:$APP_USER" "$APP_DIR" 2>/dev/null || true
    chown -R "$APP_USER:$APP_USER" /etc/simpleha 2>/dev/null || true
    chown -R "$APP_USER:$APP_USER" /var/log/simpleha 2>/dev/null || true
    chown -R "$APP_USER:$APP_USER" /var/run/simpleha 2>/dev/null || true

    log_success "应用目录创建完成"
}

# 安装 SimpleHA
install_simpleha() {
    log_info "安装 SimpleHA..."

    source /opt/simpleha/venv/bin/activate

    # 升级 pip
    pip install --upgrade pip setuptools wheel

    # 安装 SimpleHA
    pip install simpleha

    log_success "SimpleHA 安装完成"
}

# 生成示例配置
generate_config() {
    log_info "生成示例配置..."

    source /opt/simpleha/venv/bin/activate

    # 生成默认配置
    simpleha config generate /etc/simpleha/ha.yaml 2>/dev/null || {
        log_warning "simpleha config 命令不可用，创建默认配置..."

        cat > /etc/simpleha/ha.yaml <<'EOF'
# SimpleHA 配置文件
cluster_name: "simpleha-cluster"
cluster_id: "ha-001"

nodes:
  - name: "node1"
    address: "192.168.1.10"
    port: 8081
    priority: 2

  - name: "node2"
    address: "192.168.1.11"
    port: 8081
    priority: 1

heartbeat_interval: 2.0
heartbeat_timeout: 10.0

resources: []

stonith_enabled: true
stonith_timeout: 30

quorum_required: true
expected_votes: 2
votes_needed: 2

arb_disk_enabled: false
arb_disk_device: "/dev/sdb"
arb_disk_type: "iscsi"
arb_disk_timeout: 5.0

api_enabled: true
api_host: "0.0.0.0"
api_port: 8080
EOF
    }

    # 设置权限
    chown -R "${SUDO_USER:-$(whoami)}:${SUDO_USER:-$(whoami)}" /etc/simpleha

    log_success "配置文件已创建: /etc/simpleha/ha.yaml"
}

# 配置 Redis
setup_redis() {
    log_info "配置 Redis..."

    systemctl enable --now redis 2>/dev/null || {
        log_warning "Redis 服务配置失败，跳过"
        return 0
    }

    # 配置 Redis 绑定
    sed -i 's/^bind 127.0.0.1$/bind 0.0.0.0/' /etc/redis.conf 2>/dev/null || true
    systemctl restart redis

    log_success "Redis 配置完成"
}

# 配置 iSCSI（可选）
setup_iscsi() {
    log_info "配置 iSCSI 客户端..."

    systemctl enable --now iscsi iscsid 2>/dev/null || {
        log_warning "iSCSI 服务配置失败，跳过"
        return 0
    }

    log_success "iSCSI 客户端配置完成"
}

# 配置 NTP
setup_ntp() {
    log_info "配置 NTP 时间同步..."

    systemctl enable --now chronyd
    sleep 2
    chronyc sources | head -5

    log_success "NTP 配置完成"
}

# 创建 systemd 服务
create_systemd_service() {
    log_info "创建 systemd 服务..."

    cat > /etc/systemd/system/simpleha-api.service <<EOF
[Unit]
Description=SimpleHA API Server
Documentation=https://github.com/s20040521-glitch/simpleha
After=network.target redis.service
Wants=redis.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/simpleha
Environment="PATH=/opt/simpleha/venv/bin"
ExecStart=/opt/simpleha/venv/bin/simpleha-api --config /etc/simpleha/ha.yaml
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
# 安全设置
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/simpleha /var/run/simpleha /etc/simpleha

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable simpleha-api

    log_success "systemd 服务创建完成"
}

# 验证安装
verify_installation() {
    log_info "验证安装..."

    source /opt/simpleha/venv/bin/activate

    echo ""
    echo "========================================"
    echo "        安装验证"
    echo "========================================"
    echo ""

    # 验证 Python
    echo -n "Python 版本: "
    python3.9 --version

    # 验证 pip
    echo -n "pip 版本: "
    pip --version

    # 验证 SimpleHA
    echo -n "SimpleHA 版本: "
    simpleha --version 2>/dev/null || echo "CLI 未配置"

    # 验证配置文件
    echo ""
    echo "配置文件位置: /etc/simpleha/ha.yaml"
    if [[ -f /etc/simpleha/ha.yaml ]]; then
        echo "配置文件状态: ✓ 存在"
    else
        echo "配置文件状态: ✗ 不存在"
    fi

    # 验证服务
    echo ""
    echo "服务状态: "
    systemctl is-enabled simpleha-api 2>/dev/null && echo "simpleha-api: ✓ 已启用" || echo "simpleha-api: ✗ 未启用"

    echo ""
    echo "========================================"
    echo "        安装完成!"
    echo "========================================"
}

# 显示使用说明
show_usage() {
    echo ""
    echo "========================================"
    echo "        SimpleHA 使用指南"
    echo "========================================"
    echo ""
    echo "1. 激活虚拟环境:"
    echo "   source /opt/simpleha/venv/bin/activate"
    echo ""
    echo "2. 编辑配置文件:"
    echo "   vim /etc/simpleha/ha.yaml"
    echo ""
    echo "3. 启动服务:"
    echo "   sudo systemctl start simpleha-api"
    echo "   sudo systemctl status simpleha-api"
    echo ""
    echo "4. 测试 API:"
    echo "   curl http://localhost:8080/health"
    echo ""
    echo "5. 查看日志:"
    echo "   journalctl -u simpleha-api -f"
    echo ""
    echo "6. 停止服务:"
    echo "   sudo systemctl stop simpleha-api"
    echo ""
    echo "========================================"
}

# 主函数
main() {
    echo ""
    echo "========================================"
    echo "   SimpleHA RHEL 8.5 安装脚本"
    echo "   版本: 1.0.0"
    echo "========================================"
    echo ""

    check_root
    check_rhel_version

    # 注册订阅（可选）
    if [[ "${SKIP_SUBSCRIPTION:-false}" != "true" ]]; then
        register_subscription
    fi

    enable_repos
    install_base_deps
    install_python
    setup_app_directory
    install_simpleha
    generate_config
    setup_redis
    setup_iscsi
    setup_ntp
    create_systemd_service
    verify_installation
    show_usage

    log_success "安装脚本执行完成!"
}

# 运行主函数
main "$@"
