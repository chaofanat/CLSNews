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
# 安装依赖
pip install -r requirements.txt

# 启动服务（默认端口 8900）
python server.py
```

## 配置

通过环境变量或直接修改 `config.py`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_PORT` | `8900` | 服务端口 |
| `WEBHOOK_SECRET` | 空 | Webhook 签名密钥（与 cls-monitor 对应） |
| `LLM_MODEL` | `zai/glm-4.7-flashx` | litellm 模型标识 |
| `LLM_API_KEY` | 空 | LLM API Key |
| `LLM_BASE_URL` | 空 | 自定义 API 地址（本地模型代理等） |
| `DB_PATH` | `db/narrative.db` | SQLite 数据库路径 |
| `MAX_RETRIES` | `3` | 提取失败最大重试次数 |

切换模型示例：

```bash
# 智谱 GLM-4.7-FlashX
LLM_MODEL=zai/glm-4.7-flashx LLM_API_KEY=your-key python server.py

# 本地 Ollama
LLM_MODEL=ollama/qwen3:14b-q8_0 LLM_API_KEY=ollama LLM_BASE_URL=http://localhost:11434 python server.py
```

## 与 cls-monitor 对接

在 cls-monitor 的 `config.py` 中配置：

```python
WEBHOOK_URL = "http://localhost:8900/webhook"
WEBHOOK_SECRET = ""  # 与本服务保持一致
PUSH_HANDLERS = ["sqlite", "webhook"]
```

## 项目结构

```
cls-narrative/
├── server.py        # FastAPI Webhook 端点
├── config.py        # 配置项
├── models.py        # Pydantic 数据模型
├── extractor.py     # LLM 调用与重试逻辑
├── prompt.py        # 叙事提取提示词模板
├── storage.py       # SQLite 存储层
├── requirements.txt
└── db/              # 数据库目录（自动创建）
```

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

额外字段：`raw_id`（关联原文）、`narrative_id`（自增唯一标识 NAR-YYYYMMDD-NNN）、`extracted_at`、`model_version`、`retry_count`。

### 枚举值

- **text_type**：事实报道 / 观点研判 / 政策发布 / 数据发布 / 市场传闻 / 公告披露
- **narrative_mode**：突破型 / 确认型 / 否认型 / 升级型 / 缓和型 / 延续型 / 反转型
- **narrative_trend**：利好 / 利空 / 中性 / 待观察
- **narrative_firmness**：已确认 / 高概率 / 推测性 / 传闻

## API

### POST /webhook

接收 cls-monitor 推送的消息。

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

### GET /health

健康检查，返回 `{"status": "ok"}`。

## 验证

```bash
# 启动服务
python server.py

# 模拟推送（Python，避免 Windows curl 编码问题）
python -c "
import json, urllib.request
msg = {'id':1,'level':'B','time':'2026-06-03 12:00:00','title':'测试','brief':'摘要','content':'正文内容','stocks':[],'subjects':[]}
data = json.dumps(msg, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request('http://localhost:8900/webhook', data=data, headers={'Content-Type': 'application/json; charset=utf-8'})
print(urllib.request.urlopen(req).read().decode())
"

# 查看 raw 表
sqlite3 db/narrative.db "SELECT id, title, level FROM raw ORDER BY id DESC LIMIT 5"

# 查看 narrative 表
sqlite3 db/narrative.db "SELECT narrative_id, text_type, narrative_mode, sentiment_score FROM narrative ORDER BY id DESC LIMIT 5"

# 分类分布统计
sqlite3 db/narrative.db "SELECT narrative_mode, COUNT(*) FROM narrative GROUP BY narrative_mode"
```

## 技术栈

- **FastAPI** — 异步 Web 框架
- **instructor + litellm** — LLM 结构化输出（支持 OpenAI / 智谱 / Ollama 等多后端）
- **Pydantic** — 数据校验与枚举约束
- **SQLite WAL** — 单机持久化
- **uvicorn** — ASGI 服务器
