# Fund Monitor

一个基金实时监控和净值追踪系统，支持基金组合管理、净值可视化和基准指数对比。

## 功能特性

- **基金组合管理**：支持创建和管理多个基金组合
- **实时净值追踪**：自动获取基金最新净值和持仓数据
- **可视化图表**：使用 ECharts 展示净值历史走势
- **基准对比**：支持与沪深300等基准指数进行对比分析
- **多周期切换**：支持日线、周线、月线等多种时间周期
- **自动更新**：后台定时更新股票报价和基金数据

## 技术栈

### 后端
- **FastAPI**：高性能异步 Web 框架
- **SQLAlchemy**：ORM 数据库管理
- **AKShare**：A股数据获取
- **APScheduler**：定时任务调度
- **SQLite**：轻量级数据库

### 前端
- **Vue 3**：现代化前端框架
- **TypeScript**：类型安全的 JavaScript
- **Vite**：快速构建工具
- **ECharts**：数据可视化图表库
- **Vue Router**：前端路由管理

## 项目结构

```
fund-monitor/
├── backend/           # 后端服务
│   ├── app/
│   │   ├── api/      # API 路由
│   │   ├── models/   # 数据模型
│   │   ├── services/ # 业务逻辑
│   │   └── tasks/    # 定时任务
│   └── tests/        # 单元测试
├── frontend/         # 前端应用
│   ├── src/
│   │   ├── api/      # API 调用
│   │   ├── components/ # Vue 组件
│   │   ├── router/   # 路由配置
│   │   └── views/    # 页面视图
│   └── ...
└── docs/            # 项目文档
```

## 快速开始

### 环境要求

- Python 3.9+
- Node.js 16+
- npm 或 yarn

### 后端启动

```bash
cd backend

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn app.api.portfolio_routes:app --reload --host 0.0.0.0 --port 8000
```

后端服务将运行在 `http://localhost:8000`

API 文档地址：`http://localhost:8000/docs`

### 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端应用将运行在 `http://localhost:5173`

### 生产构建

```bash
# 前端构建
cd frontend
npm run build

# 后端使用生产模式运行
cd backend
uvicorn app.api.portfolio_routes:app --host 0.0.0.0 --port 8000
```

## API 使用示例

### 创建基金组合

```bash
curl -X POST http://localhost:8000/api/portfolio \
  -H "Content-Type: application/json" \
  -d '{"name": "我的组合", "description": "测试组合"}'
```

### 添加基金

```bash
curl -X POST http://localhost:8000/api/portfolio/1/fund/setup \
  -H "Content-Type: application/json" \
  -d '{"fund_code": "110011", "shares": 1000.0}'
```

### 获取净值历史

```bash
curl http://localhost:8000/api/fund/110011/nav/history?days=30
```

## 主要功能说明

### 基金净值估算
系统会自动获取基金的实际持仓数据，结合实时股票报价，估算基金的当前净值。

### 基准对比
支持将基金净值走势与沪深300等指数进行归一化对比，直观展示相对表现。

### 自动更新
后台定时任务会定期更新股票报价、基金净值等数据，确保数据的时效性。

## 测试

```bash
cd backend
pytest
```

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License
