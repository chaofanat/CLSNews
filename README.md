# CLSNews — 财联社电报监控与金融叙事提取系统

7×24 实时采集财联社电报，通过 LLM 对每条电报进行四层结构化叙事提取，输出可量化分析的金融事件数据。

## 架构

```
cls-monitor ──Webhook──→ cls-narrative ──→ SQLite
     │                        │
  SQLite              LLM API (GLM/GPT/Ollama)
```

- **cls-monitor** — 财联社电报采集器（[独立仓库](https://github.com/chaofanat/cls-monitor)，通过 git submodule 引入）
- **cls-narrative** — LLM 叙事提取引擎，提供 Webhook 接收 + 只读查询 API

## 快速部署

### 1. 克隆项目

```bash
git clone --recursive https://github.com/chaofanat/CLSNews.git
cd CLSNews
```

已有仓库但缺少 submodule：

```bash
git submodule update --init --recursive
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写 `LLM_API_KEY`：

```env
# --- cls-monitor ---
POLL_INTERVAL=10            # 轮询间隔（秒）
NOTIFY_LEVEL=B              # 通知最低等级 A/B/C
KEYWORDS=                   # 关键词过滤，逗号分隔
STOCK_CODES=                # 股票代码过滤，逗号分隔
WEBHOOK_SECRET=             # Webhook 签名密钥（可选）
PUSH_HANDLERS=sqlite,webhook

# --- cls-narrative ---
SERVER_PORT=8900
LLM_MODEL=zai/glm-4.7-flashx
LLM_API_KEY=your-api-key-here   # 必填
LLM_BASE_URL=                   # 自定义 API 地址（可选）
MAX_RETRIES=3
```

### 3. 启动

```bash
docker compose up -d
```

首次启动会自动构建镜像，narrative 健康检查通过后 monitor 才开始轮询。

### 4. 验证

```bash
# 服务状态
docker compose ps

# 查看日志
docker compose logs -f

# 健康检查
curl http://localhost:8900/health

# 统计概览
curl http://localhost:8900/api/stats

# API 文档
# 浏览器打开 http://localhost:8900/docs
```

## 常用命令

```bash
docker compose up -d              # 启动
docker compose down               # 停止
docker compose up -d --build      # 代码变更后重建并启动
docker compose logs -f monitor    # 查看 monitor 日志
docker compose logs -f narrative  # 查看 narrative 日志
docker compose ps                 # 服务状态
```

## 查询 API

所有 API 为只读，无需认证。

| 端点 | 说明 |
|------|------|
| `GET /api/stats` | 统计概览（总数、平均分、分类分布） |
| `GET /api/raw?limit=20&offset=0&level=B` | 原文列表（分页、按等级筛选） |
| `GET /api/raw/{id}` | 单条原文详情 |
| `GET /api/raw/{id}/narrative` | 原文对应的叙事提取结果 |
| `GET /api/narrative?text_type=事实报道&narrative_trend=利空&sentiment_min=-1&sentiment_max=0` | 叙事列表（多维筛选） |
| `GET /api/narrative/{narrative_id}` | 单条叙事详情（按 NAR-YYYYMMDD-NNN） |
| `POST /webhook` | 接收 cls-monitor 推送（OpenAPI 文档中有完整 Schema） |

## 切换 LLM 模型

通过 `.env` 中的 `LLM_MODEL` 和 `LLM_BASE_URL` 切换：

```env
# 智谱 GLM（默认）
LLM_MODEL=zai/glm-4.7-flashx
LLM_API_KEY=your-key

# OpenAI
LLM_MODEL=openai/gpt-4o-mini
LLM_API_KEY=sk-xxx

# 本地 Ollama
LLM_MODEL=ollama/qwen3:14b-q8_0
LLM_API_KEY=ollama
LLM_BASE_URL=http://host.docker.internal:11434
```

修改后重启 narrative 生效：

```bash
docker compose up -d --force-recreate narrative
```

## 数据持久化

数据存储在 Docker 命名卷中，容器重建不丢失：

```bash
# 查看卷
docker volume ls | grep clsnews

# 直接查询 SQLite（需先安装 sqlite3）
docker compose exec narrative sqlite3 /app/db/narrative.db "SELECT COUNT(*) FROM raw"
docker compose exec narrative sqlite3 /app/db/narrative.db "SELECT narrative_mode, COUNT(*) FROM narrative GROUP BY narrative_mode"
```

## 数据模型

### 叙事提取四层结构

| 层 | 字段 | 说明 |
|----|------|------|
| 基础事实 | publish_time, source, text_type, main_subject | 原文元数据与分类 |
| 叙事核心 | core_story, actor_list, action_behavior, scene_context | 客观事实摘要与参与主体 |
| 分类属性 | narrative_mode, narrative_trend, narrative_firmness, keyword_core | 枚举约束分类 |
| 量化映射 | direct_causal_chain, potential_risk_benefit, sentiment_score, narrative_intensity, affected_targets, narrative_link | 因果链、情感、强度、标的 |
