# 基金盘中实时估值监测系统 - 设计文档

> 日期：2026-02-15
> 状态：已批准

## 1. 项目概述

构建一个基金盘中实时估值监测工具，帮助用户在交易时段内实时了解所持基金的估算净值变化，辅助买入卖出决策。

### 核心需求

- **基金类型**：股票型/混合型基金
- **产品形态**：微信小程序 + Web 页面（uni-app 一套代码）
- **核心功能**：盘中实时估值显示 + 多基金组合监控
- **数据源**：免费（akshare）
- **技术栈**：Python (FastAPI) 后端

## 2. 方案选择

采用 **自主计算估值** 方案：从公开渠道获取基金季报持仓数据，结合股票实时行情，自行加权计算估值。

**优点**：完全自主可控，可深度定制算法，无第三方依赖。
**局限**：持仓数据来自季报（有滞后性），仅覆盖前十大重仓股（约占60-80%仓位），基金经理季报间调仓会导致估值偏差。

## 3. 系统架构

```
┌─────────────────┐  ┌──────────────────┐
│  微信小程序      │  │   Web 页面 (Vue3) │
└───────┬─────────┘  └────────┬─────────┘
        │                     │
        └──────────┬──────────┘
                   │ HTTP/WebSocket
          ┌────────▼─────────┐
          │  FastAPI 后端     │
          │  - REST API      │
          │  - WebSocket推送  │
          └────────┬─────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
  ┌─────▼──┐ ┌────▼───┐ ┌───▼────┐
  │ Redis  │ │ SQLite │ │akshare │
  │ 行情缓存│ │ 持仓/  │ │ 实时   │
  │        │ │ 用户数据│ │ 行情源 │
  └────────┘ └────────┘ └────────┘
```

### 核心模块

| 模块 | 职责 |
|------|------|
| 行情采集器 | 定时（每15-30秒）通过 akshare 拉取股票实时行情，缓存到 Redis |
| 持仓管理器 | 从 akshare 获取基金季报持仓数据，存储到 SQLite |
| 估值计算引擎 | 根据持仓权重 + 实时股价计算基金估值变化率 |
| API 服务 | FastAPI 提供 REST API + WebSocket 实时推送 |
| 组合管理 | 用户自定义基金组合，计算组合整体盈亏 |

### 估值算法

```
估值涨跌幅 = Σ (第i只重仓股涨跌幅 × 该股占基金净值比例)
估算净值 = 昨日净值 × (1 + 估值涨跌幅)
```

未覆盖部分（非前十大重仓股）假设涨跌幅为 0。

## 4. 数据模型

### SQLite 表结构

```sql
-- 基金基本信息
fund (
    fund_code TEXT PRIMARY KEY,   -- 基金代码
    fund_name TEXT,               -- 基金名称
    fund_type TEXT,               -- 类型：股票型/混合型
    last_nav REAL,                -- 最近公布的净值
    nav_date TEXT,                -- 净值日期
    updated_at TEXT
)

-- 基金持仓（来自季报）
fund_holding (
    id INTEGER PRIMARY KEY,
    fund_code TEXT,               -- 关联基金
    stock_code TEXT,              -- 股票代码
    stock_name TEXT,              -- 股票名称
    holding_ratio REAL,           -- 占净值比例
    report_date TEXT,             -- 报告期
    updated_at TEXT
)

-- 用户组合
portfolio (
    id INTEGER PRIMARY KEY,
    name TEXT,                    -- 组合名称
    created_at TEXT
)

-- 组合中的基金
portfolio_fund (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER,
    fund_code TEXT,
    shares REAL,                  -- 持有份额
    cost_nav REAL,                -- 成本净值
    added_at TEXT
)
```

### Redis 缓存

```
stock:realtime:{stock_code}  →  { price, change_pct, timestamp }  TTL=60s
fund:estimate:{fund_code}    →  { est_nav, est_change_pct, timestamp }  TTL=30s
```

## 5. API 设计

| Method | Path | 描述 |
|--------|------|------|
| GET | `/api/fund/{code}` | 获取基金信息 + 当前估值 |
| GET | `/api/fund/{code}/holdings` | 获取基金持仓明细 |
| GET | `/api/fund/{code}/estimate` | 获取实时估值数据 |
| POST | `/api/portfolio` | 创建基金组合 |
| GET | `/api/portfolio/{id}` | 获取组合详情 + 整体盈亏 |
| POST | `/api/portfolio/{id}/funds` | 向组合添加基金 |
| DELETE | `/api/portfolio/{id}/funds/{code}` | 从组合移除基金 |
| WS | `/ws/estimate` | WebSocket 实时估值推送 |

## 6. 数据更新策略

| 数据 | 更新频率 | 方式 |
|------|---------|------|
| 股票实时行情 | 每 15-30 秒 | 后台定时任务，仅交易时段 9:30-15:00 |
| 基金持仓 | 季报发布时 | 手动触发或定时检查 |
| 基金净值 | 每日收盘后 | 定时任务，晚上 8-9 点抓取 |

## 7. 前端设计

### 页面结构（uni-app，同时输出 Web + 小程序）

1. **首页 - 组合概览**：所有组合卡片，显示今日整体盈亏
2. **组合详情页**：组合内基金列表，每只基金估算净值/涨跌幅/盈亏，底部汇总
3. **基金详情页**：基本信息、盘中估值分时图、前十大持仓涨跌
4. **设置页**：组合管理、基金增删、份额/成本设置

### 交互规范

- 交易时段自动刷新，非交易时段显示收盘数据
- 红涨绿跌（A股习惯）
- 估值数据标注"估"字样提醒

## 8. 项目目录结构

```
fund-monitor/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── api/                  # API 路由
│   │   ├── models/               # 数据模型
│   │   ├── services/             # 业务逻辑
│   │   │   ├── market_data.py    # 行情采集
│   │   │   ├── estimator.py      # 估值计算引擎
│   │   │   ├── fund_info.py      # 基金信息管理
│   │   │   └── portfolio.py      # 组合管理
│   │   ├── tasks/                # 定时任务
│   │   └── config.py             # 配置
│   ├── requirements.txt
│   └── tests/
├── frontend/                     # uni-app 项目
│   ├── src/
│   │   ├── pages/
│   │   │   ├── index/            # 首页
│   │   │   ├── portfolio/        # 组合详情
│   │   │   ├── fund-detail/      # 基金详情
│   │   │   └── settings/         # 设置
│   │   ├── components/
│   │   ├── api/
│   │   └── store/
│   └── ...
└── docs/
```
