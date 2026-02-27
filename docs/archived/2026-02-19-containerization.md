# 容器化改造 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 通过 `docker compose up --build` 一键启动 fund-monitor，前端由 Nginx 容器服务并反代 `/api` 到后端容器。

**Architecture:** backend（python:3.13-slim + uvicorn）和 frontend（nginx:alpine，多阶段构建）两个容器，通过 Docker 内网通信；后端不对外暴露端口；SQLite 数据通过 bind mount 持久化到宿主机 `./backend/data/`。

**Tech Stack:** Docker Compose v2, Python 3.13-slim, Node 22-alpine, nginx:alpine

---

### Task 1: 让 DATABASE_URL 可通过环境变量覆盖

**Files:**
- Modify: `backend/app/config.py`

**Step 1: 修改 config.py，读取环境变量**

将 `DATABASE_URL` 那行替换为优先读取环境变量的版本：

```python
"""Application configuration."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "fund_monitor.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")

# Cache settings (in-memory, replaces Redis for MVP)
STOCK_CACHE_TTL = 60  # seconds
ESTIMATE_CACHE_TTL = 30  # seconds

# Market data settings
MARKET_DATA_INTERVAL = 30  # seconds between stock quote fetches
TRADING_START = "09:30"
TRADING_END = "15:00"

# Ensure data directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
```

说明：`os.getenv("DATABASE_URL", fallback)` — 有环境变量时用环境变量（Docker 场景），没有时用原来的路径计算（本地开发场景）。

**Step 2: 运行全量测试，确认无回归**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/ -v --tb=short
```

预期：52 passed

**Step 3: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/config.py
git commit -m "feat: allow DATABASE_URL override via environment variable"
```

---

### Task 2: 修复前端 API URL 在生产环境的处理

**Files:**
- Modify: `frontend/src/api/index.ts`

**背景：** 当前代码是 `VITE_API_URL || 'http://localhost:8000'`。JS 中空字符串 `''` 被 `||` 视为 falsy，Docker 构建时传入 `VITE_API_URL=""` 会被忽略，导致仍然请求 `localhost:8000`。改为 `??`（nullish coalescing）即可正确处理空字符串。

**Step 1: 修改第 1 行**

将：
```typescript
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
```

改为：
```typescript
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
```

说明：
- 本地开发（未设置 VITE_API_URL）：`undefined ?? 'http://localhost:8000'` → `'http://localhost:8000'` ✓
- Docker 生产（VITE_API_URL=""）：`'' ?? 'http://localhost:8000'` → `''`（空字符串 = 相对 URL）✓

**Step 2: 无需自动化测试**（纯类型修改，Docker 集成测试会覆盖）

**Step 3: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/api/index.ts
git commit -m "fix: use nullish coalescing for VITE_API_URL to support empty string in production"
```

---

### Task 3: 创建后端 Dockerfile

**Files:**
- Create: `backend/Dockerfile`

**Step 1: 创建文件**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/

# Ensure data directory exists at runtime
RUN mkdir -p /app/data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

说明：
- 只复制 `app/` 目录（不含 `tests/`、`data/`），减小镜像体积
- `data/` 目录在 Dockerfile 中预创建，确保挂载前路径存在
- 先复制 `requirements.txt` 再复制代码，依赖层可被缓存

**Step 2: 验证镜像构建成功**

```bash
cd /Users/cc/fund-monitor/backend
docker build -t fund-monitor-backend .
```

预期：最后一行 `Successfully built ...` 或 `=> exporting to image`，无 ERROR

**Step 3: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/Dockerfile
git commit -m "feat: add backend Dockerfile"
```

---

### Task 4: 创建前端 Nginx 配置

**Files:**
- Create: `frontend/nginx.conf`

**Step 1: 创建文件**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # Proxy API requests to backend container
    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # SPA fallback: all other routes serve index.html (Vue Router history mode)
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

说明：
- `http://backend:8000` — Docker Compose 内网中 `backend` 是 backend 容器的 hostname
- `try_files $uri $uri/ /index.html` — Vue Router history mode 刷新页面不 404

**Step 2: 无需单独验证**（下一个 Task 的 docker build 会验证）

**Step 3: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/nginx.conf
git commit -m "feat: add nginx config for frontend with API proxy"
```

---

### Task 5: 创建前端多阶段 Dockerfile

**Files:**
- Create: `frontend/Dockerfile`

**Step 1: 创建文件**

```dockerfile
# Stage 1: Build Vue3 app
FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json .
RUN npm ci

COPY . .

# Empty VITE_API_URL = use relative URLs, Nginx proxies /api to backend
ENV VITE_API_URL=""
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
```

说明：
- 两阶段构建：第一阶段 `node:22-alpine` 只用于编译，最终镜像只含 `nginx:alpine` + 静态文件，体积极小
- `ENV VITE_API_URL=""` 在构建时设置，Vite 将其编译进 bundle，前端请求用相对路径

**Step 2: 验证镜像构建成功**

```bash
cd /Users/cc/fund-monitor/frontend
docker build -t fund-monitor-frontend .
```

预期：两阶段构建成功，无 ERROR

**Step 3: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/Dockerfile
git commit -m "feat: add frontend multi-stage Dockerfile with nginx"
```

---

### Task 6: 创建 docker-compose.yml 和 .env.example

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

**Step 1: 创建 docker-compose.yml**

```yaml
services:
  backend:
    build: ./backend
    env_file: .env
    volumes:
      - ./backend/data:/app/data
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped
```

说明：
- `env_file: .env` — 从 `.env` 读取环境变量注入 backend 容器
- `./backend/data:/app/data` — bind mount，SQLite 文件持久化到宿主机，迁移 MySQL 时直接可访问
- backend 不暴露 `ports`，只通过内网被 Nginx 访问
- `restart: unless-stopped` — 服务器重启后自动恢复

**Step 2: 创建 .env.example**

```bash
# Fund Monitor 环境配置
# 使用方法：cp .env.example .env，然后按需修改

# 数据库连接串
# SQLite（默认）: sqlite+aiosqlite:////app/data/fund_monitor.db
# MySQL（迁移后）: mysql+aiomysql://user:password@db:3306/fund_monitor
DATABASE_URL=sqlite+aiosqlite:////app/data/fund_monitor.db
```

注意 SQLite URL 有 4 个斜杠：`sqlite+aiosqlite:////app/data/...`
- `sqlite+aiosqlite://` — scheme（含两斜杠）
- `//app/data/...` — 绝对路径（含两斜杠）

**Step 3: 确认 .gitignore 已忽略 .env**

检查 `.gitignore`：

```bash
grep "^\.env$" /Users/cc/fund-monitor/.gitignore
```

预期输出：`.env`（已存在，无需修改）

**Step 4: 提交**

```bash
cd /Users/cc/fund-monitor
git add docker-compose.yml .env.example
git commit -m "feat: add docker-compose.yml and .env.example for production deployment"
```

---

### Task 7: 端到端验证

**Step 1: 创建本地 .env**

```bash
cd /Users/cc/fund-monitor
cp .env.example .env
```

**Step 2: 构建并启动所有容器**

```bash
cd /Users/cc/fund-monitor
docker compose up --build -d
```

预期：两个容器启动，无 ERROR（warning 可忽略）

**Step 3: 确认容器运行状态**

```bash
docker compose ps
```

预期：backend 和 frontend 均为 `running` 状态

**Step 4: 验证 API 健康检查**

```bash
curl http://localhost/api/health
```

预期：`{"status":"ok"}`

**Step 5: 验证前端可访问**

```bash
curl -s http://localhost | head -5
```

预期：返回 HTML，含 `<div id="app">`

**Step 6: 验证 SQLite 文件持久化**

```bash
ls -la backend/data/fund_monitor.db
```

预期：文件存在（容器启动时 FastAPI 的 `init_db()` 会创建它）

**Step 7: 清理**

```bash
docker compose down
```

**Step 8: 提交验收**

```bash
cd /Users/cc/fund-monitor
git add .
git commit -m "chore: verify docker compose end-to-end"
```

---

## 验收标准

- [ ] `docker compose up --build` 无报错启动
- [ ] `GET http://localhost/api/health` 返回 `{"status":"ok"}`
- [ ] `GET http://localhost` 返回前端 HTML
- [ ] `backend/data/fund_monitor.db` 在宿主机可见
- [ ] `.env` 未提交到 git（`.gitignore` 已覆盖）
- [ ] `.env.example` 已提交
