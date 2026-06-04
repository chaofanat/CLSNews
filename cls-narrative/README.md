# cls-narrative — 财联社电报金融叙事提取引擎

接收 cls-monitor 推送的财联社电报数据，调用 LLM 进行四层结构化叙事提取，持久化到 SQLite。

## 架构

```
cls-monitor ──Webhook──→ cls-narrative ──→ SQLite
                              │
                           LLM API
```

核心流程：接收 Webhook → 原文入库 → 异步调用 LLM 提取 → 结构化数据入库。接收端立即返回 200，LLM 提取在后台完成。

## 快速开始

```bash
pip install -r requirements.txt
python server.py        # 默认端口 8900
```

## 配置

所有配置通过环境变量设置（也可修改 `config.py` 中的默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_PORT` | `8900` | 服务端口 |
| `WEBHOOK_SECRET` | 空 | Webhook HMAC-SHA256 签名密钥（与 cls-monitor 对应） |
| `LLM_PROVIDER` | `anthropic` | LLM 后端：`"anthropic"`（默认，直连智谱）或 `"litellm"`（多后端） |
| `LLM_MODEL` | `glm-4.7-flashx` | 模型名称（anthropic 模式直接使用智谱模型名） |
| `LLM_API_KEY` | 空 | LLM API Key |
| `LLM_BASE_URL` | 空 | 自定义 API 地址（默认智谱 Anthropic 兼容接口） |
| `DB_PATH` | `db/narrative.db` | SQLite 数据库路径 |
| `MAX_RETRIES` | `3` | 提取失败最大重试次数 |

切换模型示例：

```bash
# 智谱 GLM-4.7-FlashX（默认，Anthropic 兼容接口）
LLM_MODEL=glm-4.7-flashx LLM_API_KEY=your-key python server.py

# 智谱高并发模型
LLM_MODEL=GLM-4-FlashX-250414 LLM_API_KEY=your-key python server.py

# litellm 多后端模式（需 pip install litellm）
LLM_PROVIDER=litellm LLM_MODEL=openai/gpt-4o-mini LLM_API_KEY=sk-xxx python server.py
```

## 与 cls-monitor 对接

在 cls-monitor 的 `.env` 或 `config.py` 中配置：

```env
WEBHOOK_URL=http://localhost:8900/webhook
WEBHOOK_SECRET=           # 与本服务保持一致
PUSH_HANDLERS=sqlite,webhook
```

## API

### Webhook（写入）

#### POST /webhook

接收 cls-monitor 推送的消息（OpenAPI 文档中有完整 Schema，访问 `/docs` 查看）。

```json
{
  "id": 12345,
  "level": "B",
  "time": "2026-06-03 14:30:00",
  "title": "...",
  "brief": "...",
  "content": "...",
  "stocks": [{"code": "sh600519", "name": "贵州茅台", "change": "+1.2%"}],
  "subjects": ["白酒"]
}
```

响应：`{"status": "ok", "count": 1}`

### 查询 API（只读）

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /api/stats` | 统计概览（总数、平均分、分类分布） |
| `GET /api/raw?limit=20&offset=0&level=B` | 原文列表（分页、按等级筛选） |
| `GET /api/raw/{id}` | 单条原文详情 |
| `GET /api/raw/{id}/narrative` | 原文对应的叙事提取结果 |
| `GET /api/narrative?text_type=事实报道&narrative_trend=利空&sentiment_min=-1` | 叙事列表（多维筛选） |
| `GET /api/narrative/{narrative_id}` | 单条叙事详情（按 NAR-YYYYMMDD-NNN） |
| `GET /api/running` | 当前执行中的提取任务 + 排队数量 + worker 信息 |

查询参数：

- **raw 列表**：`limit`（1-200）、`offset`、`level`（A/B/C）
- **narrative 列表**：`limit`、`offset`、`text_type`、`narrative_mode`、`narrative_trend`、`narrative_firmness`、`sentiment_min/max`、`intensity_min/max`

### OpenAPI 文档

启动后访问 `http://localhost:8900/docs` 查看完整交互式 API 文档。

### 失败管理 API

LLM 提取永久失败（3 次重试耗尽）后，记录写入 `extraction_failed` 表。后台每 30 分钟自动重试，也可手动触发。

| 端点 | 说明 |
|------|------|
| `GET /api/failed` | 列出失败的提取记录 |
| `POST /api/failed/{raw_id}/retry` | 手动触发重试 |
| `POST /api/failed/backfill` | 扫描有 raw 但无 narrative 无 failed 的孤儿数据，登记到重试队列 |

启动时自动执行一次 backfill，之后每 30 分钟与失败重试一起执行。`GET /api/stats` 返回的 `failed_count` 字段显示当前失败记录数。

### 提取队列

Webhook 和重试共用统一的 `asyncio.Queue`，由 2 个 worker 消费。`GET /api/running` 返回当前正在执行的任务、排队数量、worker 数。仪表盘 `/dashboard` 可查看队列和 worker 状态。

## 数据模型

### raw 表（原文快照）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 电报 ID |
| level | TEXT | 等级 A/B/C |
| time | TEXT | 发布时间 |
| title | TEXT | 标题 |
| brief | TEXT | 摘要 |
| content | TEXT | 正文 |
| stocks | JSON | 关联股票 |
| subjects | JSON | 关联话题 |
| received_at | REAL | 接收时间戳 |

### narrative 表（提取结果）

四层结构化输出：

| 层 | 字段 | 说明 |
|----|------|------|
| 基础事实 | publish_time, source, text_type, main_subject | 原文元数据与分类 |
| 叙事核心 | core_story, actor_list, action_behavior, scene_context | 客观事实摘要与参与主体 |
| 分类属性 | narrative_mode, narrative_trend, narrative_firmness, keyword_core | 枚举约束分类 |
| 量化映射 | direct_causal_chain, potential_risk_benefit, sentiment_score, narrative_intensity, affected_targets, narrative_link | 因果链、情感、强度、标的 |

额外字段：`raw_id`（关联原文）、`narrative_id`（NAR-YYYYMMDD-NNN）、`extracted_at`、`model_version`、`retry_count`。

### 枚举值

- **text_type**：事实报道 / 观点研判 / 政策发布 / 数据发布 / 市场传闻 / 公告披露
- **narrative_mode**：突破型 / 确认型 / 否认型 / 升级型 / 缓和型 / 延续型 / 反转型
- **narrative_trend**：利好 / 利空 / 中性 / 待观察
- **narrative_firmness**：已确认 / 高概率 / 推测性 / 传闻

## 项目结构

```
cls-narrative/
├── server.py        # FastAPI Webhook + 查询 API
├── config.py        # 配置项（环境变量驱动）
├── models.py        # Pydantic 数据模型 + 枚举
├── extractor.py     # LLM 调用与重试逻辑
├── prompt.py        # 叙事提取提示词模板
├── storage.py       # SQLite 存储层
├── Dockerfile
├── requirements.txt
└── db/              # 数据库目录（自动创建）
```

## 技术栈

- **FastAPI** — 异步 Web 框架
- **Anthropic SDK** — LLM 调用（默认，直连智谱 Anthropic 兼容接口）
- **instructor + litellm**（可选）— 多后端 LLM 结构化输出
- **Pydantic** — 数据校验与枚举约束
- **SQLite WAL** — 单机持久化
- **uvicorn** — ASGI 服务器
- **Chart.js** — 仪表盘图表
