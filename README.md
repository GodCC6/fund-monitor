# Fund Monitor

一个基金实时监控和净值追踪系统，支持基金组合管理、净值可视化和基准指数对比。

## 功能特性

- **基金组合管理**：创建和管理多个基金组合，按名称搜索添加基金
- **逐基金 P&L 展示**：组合详情显示每只基金名称、估算净值、今日涨跌、持仓收益
- **实时净值估算**：根据基金实际持仓 + 实时股票报价，估算当前净值（标注「估」徽章）
- **可视化图表**：使用 ECharts 展示净值历史走势
- **基准对比**：支持与沪深300等基准指数进行归一化对比
- **多周期切换**：支持日线、周线、月线等多种时间周期
- **自动更新**：交易时段内每30秒自动更新股票报价和估算数据

## 技术栈

### 后端
- **FastAPI**：高性能异步 Web 框架
- **SQLAlchemy + aiosqlite**：异步 ORM，SQLite 数据库
- **AKShare**：A股数据获取
- **APScheduler**：定时任务调度

### 前端
- **Vue 3 + TypeScript**：现代化前端框架
- **Vite**：快速构建工具
- **ECharts**：数据可视化
- **Vue Router**：前端路由（history mode）

## 项目结构

```
fund-monitor/
├── docker-compose.yml     # 生产部署编排
├── .env.example           # 环境变量模板
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt       # 生产依赖
│   ├── requirements-dev.txt   # 开发/测试依赖
│   ├── app/
│   │   ├── api/           # API 路由
│   │   ├── models/        # 数据模型
│   │   ├── services/      # 业务逻辑
│   │   └── tasks/         # 定时任务
│   └── tests/
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    └── src/
        ├── api/           # API 调用层
        ├── components/    # Vue 组件
        ├── router/        # 路由配置
        └── views/         # 页面视图
```

## 快速开始

### 方式一：Docker（推荐）

**环境要求：** Docker Desktop 或 Docker Engine + Compose v2

```bash
# 1. 复制配置文件
cp .env.example .env

# 2. 构建并启动
docker compose up --build -d

# 3. 访问应用
open http://localhost
```

服务说明：
- 前端（Nginx）：`http://localhost`
- 后端 API：通过 Nginx 反代，路径 `/api/*`
- SQLite 数据：持久化到宿主机 `./backend/data/fund_monitor.db`

停止服务：
```bash
docker compose down
```

**服务器部署（HTTPS、备份、运维）**：详见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

### 方式二：本地开发

**环境要求：** Python 3.11+、Node.js 18+

**后端：**

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements-dev.txt

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端运行在 `http://localhost:8000`，API 文档：`http://localhost:8000/docs`

**前端：**

```bash
cd frontend
npm install
npm run dev
```

前端运行在 `http://localhost:5173`

## 测试

```bash
cd backend

# 安装测试依赖（含生产依赖）
pip install -r requirements-dev.txt

# 运行测试
pytest tests/ -v
```

## API 简介

### 健康检查

```bash
curl http://localhost/api/health
# {"status":"ok"}
```

### 组合管理

```bash
# 创建组合
curl -X POST http://localhost/api/portfolio \
  -H "Content-Type: application/json" \
  -d '{"name": "我的组合"}'

# 获取组合详情（含每只基金 P&L）
curl http://localhost/api/portfolio/1
```

### 基金搜索

```bash
# 按名称或代码搜索
curl "http://localhost/api/fund/search?q=华夏"
```

### 添加基金到组合

```bash
# 先初始化基金数据
curl -X POST http://localhost/api/fund/setup/110011

# 再添加到组合
curl -X POST http://localhost/api/portfolio/1/funds \
  -H "Content-Type: application/json" \
  -d '{"fund_code": "110011", "shares": 1000.0, "cost_nav": 2.5}'
```

## 环境变量

复制 `.env.example` 为 `.env` 并按需修改：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | SQLite（本地文件） | 数据库连接串，迁移 MySQL 时修改此项 |

## 许可证

MIT License
