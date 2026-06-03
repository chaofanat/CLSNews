from __future__ import annotations

NARRATIVE_SYSTEM_PROMPT = """\
你是一名金融叙事结构化提取专家。你的任务是从财联社电报原文中提取四层结构化叙事数据。

## 核心约束

1. **core_story（客观事实摘要）**：只陈述原文明确表述的事实，禁止任何主观预判、市场推演和价值判断。
2. **direct_causal_chain（直接因果链）**：仅提取原文中显性表达的因果关系，禁止推断或脑补隐含因果。
3. **sentiment_score 与 narrative_intensity 分离**：研报看多不等于市场实际表现，情感得分反映信息本身的倾向，叙事强度衡量信息量和影响力。
4. **分类边界校准**：
   - 研报观点归类为"观点研判"而非"事实报道"
   - 未经证实的消息归类为"市场传闻"
   - 已有官方确认的归类为"已确认"

## 输出格式

严格按照 NarrativeExtract 模型输出，所有字段必须填写。

## 文本类型判定规则

- **事实报道**：已发生的客观事件报道
- **观点研判**：分析师、机构、专家的观点和预测
- **政策发布**：政府部门、监管机构的政策、法规、通知
- **数据发布**：经济数据、行业数据、企业财报等
- **市场传闻**：未经官方确认的传言、小道消息
- **公告披露**：上市公司公告、交易所披露信息

## 叙事模式判定规则

- **突破型**：全新事件或重大突破
- **确认型**：对既有事件/传闻的确认
- **否认型**：对既有事件/传闻的否认
- **升级型**：既有事件的进一步发展或升级
- **缓和型**：紧张局势或风险的缓解
- **延续型**：既有趋势的延续或确认
- **反转型**：与既有预期或趋势相反的发展
"""

NARRATIVE_USER_TEMPLATE = """\
请从以下财联社电报中提取结构化叙事数据。

## 原文信息

- 标题：{title}
- 等级：{level}
- 时间：{time}
- 摘要：{brief}
- 正文：{content}
- 关联股票：{stocks}
- 关联话题：{subjects}

## 提取要求

1. publish_time 使用 ISO 8601 格式
2. core_story 必须客观，不含主观判断
3. actor_list 至少包含一个主体
4. keyword_core 提供 3-5 个核心关键词
5. sentiment_score 范围 [-1, 1]，精确到小数点后一位
6. narrative_intensity 范围 [0, 1]，精确到小数点后一位
7. direct_causal_chain 仅提取原文显性因果，没有则为空数组
"""


def build_messages(raw: dict) -> list[dict]:
    stocks = raw.get("stocks", [])
    if stocks and isinstance(stocks[0], dict):
        stocks = [s.get("name", str(s)) for s in stocks]
    subjects = raw.get("subjects", [])
    if subjects and isinstance(subjects[0], dict):
        subjects = [s.get("name", str(s)) for s in subjects]

    user_content = NARRATIVE_USER_TEMPLATE.format(
        title=raw.get("title", ""),
        level=raw.get("level", ""),
        time=raw.get("time", ""),
        brief=raw.get("brief", ""),
        content=raw.get("content", ""),
        stocks=", ".join(stocks),
        subjects=", ".join(subjects),
    )
    return [
        {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
