# 部署指南

本文档面向将 fund-monitor 部署到 Linux 服务器的场景，覆盖从环境准备到日常运维的全流程。

---

## 架构概览

```
用户浏览器
    │  HTTP/HTTPS
    ▼
[宿主机: 80/443]
    │
    ▼
Nginx（前端容器）──── 转发 /api/* ────► FastAPI（后端容器:8000, 仅内网）
    │                                          │
    ▼                                          ▼
Vue3 SPA                              SQLite（volume 挂载至宿主机）
```

- **前端容器**：Nginx 同时提供 SPA 静态文件和 `/api/*` 反向代理
- **后端容器**：FastAPI 仅暴露在 Docker 内部网络，外部不可直接访问
- **数据持久化**：SQLite 文件挂载到 `./backend/data/fund_monitor.db`，容器重建不丢失

---

## 一、服务器环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 22.04 / Debian 12（推荐）或 CentOS 9 |
| 内存 | 最低 1 GB，建议 2 GB（akshare 拉取数据时内存峰值较高） |
| 磁盘 | 最低 5 GB 可用空间 |
| 外网访问 | **必须**（AKShare 需访问东方财富等数据源） |
| Docker Engine | 24.0+ |
| Docker Compose | v2（`docker compose`，非旧版 `docker-compose`） |

---

## 二、安装 Docker

**Ubuntu / Debian：**

```bash
# 一键安装脚本（官方）
curl -fsSL https://get.docker.com | sh

# 将当前用户加入 docker 组（无需每次 sudo）
sudo usermod -aG docker $USER
newgrp docker

# 验证
docker --version       # Docker version 24.x.x
docker compose version # Docker Compose version v2.x.x
```

**CentOS / RHEL：**

```bash
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
```

---

## 三、部署应用

### 3.1 获取代码

```bash
git clone https://github.com/your-username/fund-monitor.git
cd fund-monitor
```

### 3.2 配置环境变量

```bash
cp .env.example .env
```

默认配置即可直接使用（SQLite）。如需修改数据库路径：

```bash
# .env 内容（默认无需改动）
DATABASE_URL=sqlite+aiosqlite:////app/data/fund_monitor.db
```

### 3.3 启动服务

```bash
docker compose up --build -d
```

首次构建约 3~5 分钟（需下载镜像和安装 Python 依赖）。

### 3.4 验证运行状态

```bash
# 查看容器状态（均应为 Up）
docker compose ps

# 健康检查
curl http://localhost/api/health
# {"status":"ok"}

# 查看启动日志
docker compose logs --tail=50
```

访问 `http://服务器IP` 即可使用。

---

## 四、防火墙配置

```bash
# Ubuntu/Debian（ufw）
sudo ufw allow 80/tcp
sudo ufw allow 22/tcp   # 保留 SSH
sudo ufw enable
sudo ufw status

# CentOS/RHEL（firewalld）
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

> 若启用 HTTPS（第五节），还需开放 443 端口。

---

## 五、HTTPS 配置（推荐）

应用本身不处理 HTTPS，推荐在宿主机上使用 **Caddy** 作为反向代理，自动申请和续期 Let's Encrypt 证书。

> **前提**：服务器拥有公网域名，且 DNS A 记录已指向该服务器 IP。

### 5.1 安装 Caddy

```bash
# Ubuntu/Debian
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# CentOS/RHEL
sudo dnf install -y 'dnf-command(copr)'
sudo dnf copr enable @caddy/caddy
sudo dnf install -y caddy
```

### 5.2 修改 docker-compose.yml，仅绑定本地端口

为避免 Caddy 和容器同时占用 80 端口，将前端容器改为仅监听 localhost：

```yaml
# docker-compose.yml
services:
  frontend:
    ports:
      - "127.0.0.1:8080:80"   # 改为仅本地监听，Caddy 负责对外暴露
```

重启容器使配置生效：

```bash
docker compose down && docker compose up -d
```

### 5.3 配置 Caddyfile

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
your-domain.com {
    reverse_proxy localhost:8080
}
EOF

sudo systemctl reload caddy
```

Caddy 会自动申请 TLS 证书。访问 `https://your-domain.com` 验证。

### 5.4 访问控制（无公开域名时推荐）

若服务仅供个人使用，不想对公网暴露，有两种更安全的方案：

**方案 A：Tailscale（推荐个人使用）**

```bash
# 服务器安装 Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# 客户端加入同一网络后，通过 Tailscale IP 直接访问
# http://100.x.x.x（无需公网 IP 或域名）
```

**方案 B：Caddy 基本认证**

```
your-domain.com {
    basicauth {
        admin $2a$14$<caddy hash generate --plaintext "your-password" 的输出>
    }
    reverse_proxy localhost:8080
}
```

---

## 六、数据备份

SQLite 数据库文件位于宿主机 `./backend/data/fund_monitor.db`。

### 手动备份

```bash
cp ./backend/data/fund_monitor.db ./backend/data/fund_monitor_$(date +%Y%m%d).db
```

### 自动每日备份（cron）

```bash
# 编辑 crontab
crontab -e

# 每天凌晨 2 点备份，保留最近 7 份
0 2 * * * cp /path/to/fund-monitor/backend/data/fund_monitor.db \
  /path/to/fund-monitor/backend/data/backup_$(date +\%Y\%m\%d).db && \
  find /path/to/fund-monitor/backend/data/ -name "backup_*.db" -mtime +7 -delete
```

### 从备份恢复

```bash
# 停止服务，替换数据库文件，再启动
docker compose down
cp ./backend/data/backup_20260210.db ./backend/data/fund_monitor.db
docker compose up -d
```

---

## 七、日常运维

### 查看日志

```bash
# 实时查看所有服务日志
docker compose logs -f

# 只看后端日志
docker compose logs -f backend

# 只看最近 100 行
docker compose logs --tail=100
```

### 健康检查

```bash
curl http://localhost/api/health
# 正常返回: {"status":"ok"}
```

### 重启服务

```bash
# 重启所有容器
docker compose restart

# 重启单个容器
docker compose restart backend
```

### 更新到最新版本

```bash
# 拉取代码
git pull

# 重新构建并启动（数据不丢失）
docker compose up --build -d

# 清理旧镜像（可选，节省磁盘）
docker image prune -f
```

### 停止服务

```bash
# 停止但保留容器和数据
docker compose stop

# 停止并删除容器（数据 volume 保留）
docker compose down
```

### 查看磁盘占用

```bash
# Docker 镜像/容器/volume 占用
docker system df

# 数据库文件大小
ls -lh ./backend/data/fund_monitor.db
```

---

## 八、常见问题

**Q：容器启动后访问页面空白或 API 报错**

```bash
# 查看后端是否健康
docker compose ps
docker compose logs backend --tail=30
```

常见原因：
- 依赖安装失败（网络问题）：重新 `docker compose up --build`
- 数据库文件权限问题：`chmod 755 ./backend/data`

**Q：AKShare 数据拉取超时**

后端需要访问东方财富、天天基金等境内数据源。若服务器在境外，建议：
- 使用国内云服务商（阿里云、腾讯云、华为云）的大陆区域节点
- 或在服务器上配置合适的网络代理

**Q：如何重置所有数据**

```bash
docker compose down
rm ./backend/data/fund_monitor.db
docker compose up -d
```

**Q：端口 80 被占用**

```bash
# 查看占用进程
sudo lsof -i :80

# 或修改 docker-compose.yml 改用其他端口
ports:
  - "8888:80"
```

---

## 九、部署检查清单

```
□ Docker / Docker Compose 已安装
□ git clone 并 cd 进入项目目录
□ cp .env.example .env
□ docker compose up --build -d 成功
□ curl http://localhost/api/health 返回 {"status":"ok"}
□ 防火墙已开放 80（或 443）端口
□ （可选）Caddy 反代 + HTTPS 已配置
□ （可选）定时备份已设置
□ 浏览器访问页面正常
```
