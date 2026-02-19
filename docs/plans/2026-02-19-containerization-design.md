# 容器化改造设计文档

> 设计日期：2026-02-19
> 目标：生产一键部署

---

## 背景与目标

- **目标**：将 fund-monitor 打包为 Docker 镜像，支持在任意服务器通过 `docker compose up` 一键启动
- **数据库现状**：SQLite（MVP 阶段），后续将迁移至 MySQL；设计需为此留出迁移路径

---

## 架构决策

| 维度 | 决策 | 理由 |
|------|------|------|
| 前端服务方式 | Nginx 容器（反代 `/api`） | 性能优、易加 HTTPS、扩展路径清晰 |
| 后端端口暴露 | 仅内网，不对外 | 安全，所有流量经 Nginx 统一入口 |
| 数据持久化 | Bind Mount `./backend/data:/app/data` | SQLite 文件直接在宿主机可见，便于迁移至 MySQL 时导出数据 |
| 配置管理 | `.env` 文件（gitignore）+ `.env.example` | 敏感值不进 git，`cp .env.example .env` 即可启动 |

---

## 文件结构

```
fund-monitor/
├── docker-compose.yml         ← 编排入口
├── .env                       ← 本地/服务器配置（gitignore）
├── .env.example               ← 配置模板（提交 git）
├── backend/
│   └── Dockerfile             ← python:3.13-slim + uvicorn
└── frontend/
    ├── Dockerfile             ← 多阶段：node build → nginx serve
    └── nginx.conf             ← /api 反代 + SPA fallback
```

---

## 容器设计

### backend 容器

- **基础镜像**：`python:3.13-slim`
- **构建步骤**：安装 requirements.txt → 复制代码
- **启动命令**：`uvicorn app.main:app --host 0.0.0.0 --port 8000`
- **端口**：仅内网 8000，不对外暴露
- **挂载**：`./backend/data:/app/data`（SQLite 数据库持久化）

### frontend 容器

- **阶段一（build）**：`node:22-alpine`，`npm ci && npm run build`，产出 `dist/`
- **阶段二（serve）**：`nginx:alpine`，只复制 `dist/`，镜像体积小
- **端口**：对外暴露 `80:80`

### nginx.conf 路由规则

```
/api/*  → proxy_pass http://backend:8000
/       → try_files $uri $uri/ /index.html   (Vue Router history mode)
```

---

## 环境变量

`.env.example` 提供以下变量模板：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `sqlite+aiosqlite:////app/data/fund_monitor.db` | 数据库连接串，迁移 MySQL 时修改此项 |

---

## MySQL 迁移路径

1. 在 `docker-compose.yml` 增加 `mysql` 服务 + named volume
2. 修改 `.env` 中 `DATABASE_URL` 为 MySQL 连接串
3. 从 bind mount 的 `.db` 文件导出数据后导入 MySQL
4. 无需改动 Nginx 或前端

---

## 验收标准

- [ ] `docker compose up --build` 后访问 `http://localhost` 可正常使用前端
- [ ] 前端 API 请求通过 Nginx 正确代理到后端
- [ ] Vue Router 刷新页面不 404
- [ ] `./backend/data/fund_monitor.db` 在宿主机可见且持久化
- [ ] `.env` 未提交 git，`.env.example` 已提交
