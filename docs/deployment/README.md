# SimpleHA 部署文档索引

本文档索引列出所有 SimpleHA 部署相关的文档。

## 快速链接

| 文档 | 说明 | 难度 |
|------|------|------|
| [RHEL 8.5 手动部署指南](./rhel8-deployment.md) | RHEL 8.5 完整部署步骤 | ⭐⭐⭐ |
| [一键安装脚本](../scripts/install_rhel8.sh) | RHEL 8.5 自动安装脚本 | ⭐ |

## 文档列表

### 已完成

1. **RHEL 8.5 手动部署指南** (`rhel8-deployment.md`)
   - 环境要求和准备工作
   - 依赖包安装详解
   - SimpleHA 部署步骤
   - 集群配置指南
   - 仲裁盘配置（iSCSI）
   - 验证和故障排查

2. **RHEL 8.5 一键安装脚本** (`../scripts/install_rhel8.sh`)
   - 自动化安装流程
   - 订阅管理和仓库配置
   - systemd 服务配置
   - 完整的验证步骤

### 规划中

- [ ] `docker-deployment.md` - Docker 部署指南
- [ ] `cluster-deployment.md` - 多节点集群部署
- [ ] `quorum-configuration.md` - 仲裁盘配置详解
- [ ] `stonith-configuration.md` - STONITH/Fencing 配置
- [ ] `api-reference.md` - REST API 参考文档

## 快速开始

### 方式一：使用安装脚本（推荐）

```bash
# 下载脚本
curl -O https://raw.githubusercontent.com/s20040521-glitch/simpleha/main/scripts/install_rhel8.sh

# 添加执行权限
chmod +x install_rhel8.sh

# 以 root 运行
sudo ./install_rhel8.sh
```

### 方式二：手动部署

详见 [RHEL 8.5 手动部署指南](./rhel8-deployment.md)

## 环境矩阵

| 操作系统 | 支持状态 | 文档 |
|---------|---------|------|
| RHEL 8.5 | ✅ 已测试 | [部署指南](./rhel8-deployment.md) |
| CentOS Stream 8 | ✅ 兼容 | 同上 |
| Rocky Linux 8 | ✅ 兼容 | 同上 |
| AlmaLinux 8 | ✅ 兼容 | 同上 |
| RHEL 7.x | 🔜 规划中 | - |
| Ubuntu 22.04 | 🔜 规划中 | - |
| Debian 11 | 🔜 规划中 | - |

## 反馈问题

如果你在部署过程中遇到问题，请：

1. 查看 [故障排查章节](./rhel8-deployment.md#故障排查)
2. 查看 [GitHub Issues](https://github.com/s20040521-glitch/simpleha/issues)
3. 创建新的 Issue 并提供以下信息：
   - 操作系统版本
   - 错误信息
   - 安装日志

---

**最后更新**: 2026-05-17
