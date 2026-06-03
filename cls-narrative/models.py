from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── Enums ──

class TextType(str, Enum):
    FACTUAL = "事实报道"
    OPINION = "观点研判"
    POLICY = "政策发布"
    DATA = "数据发布"
    RUMOR = "市场传闻"
    ANNOUNCEMENT = "公告披露"


class NarrativeMode(str, Enum):
    BREAKTHROUGH = "突破型"
    CONFIRMATION = "确认型"
    DENIAL = "否认型"
    ESCALATION = "升级型"
    MITIGATION = "缓和型"
    MAINTENANCE = "延续型"
    REVERSAL = "反转型"


class NarrativeTrend(str, Enum):
    BULLISH = "利好"
    BEARISH = "利空"
    NEUTRAL = "中性"
    UNCERTAIN = "待观察"


class NarrativeFirmness(str, Enum):
    CONFIRMED = "已确认"
    HIGH_PROBABILITY = "高概率"
    SPECULATIVE = "推测性"
    RUMOR = "传闻"


# ── Raw message (cls-monitor payload) ──

class RawMessage(BaseModel):
    id: int
    level: str = ""
    time: str = ""
    title: str = ""
    brief: str = ""
    content: str = ""
    stocks: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)


# ── Narrative extraction sub-models ──

class Actor(BaseModel):
    name: str = Field(description="实体/主体名称")
    role: str = Field(description="在该叙事中的角色，如：政策制定者、企业、行业、市场参与者")


class CausalLink(BaseModel):
    cause: str = Field(description="因")
    effect: str = Field(description="果")
    confidence: Literal["高", "中", "低"] = Field(description="因果关联置信度")


class RiskBenefit(BaseModel):
    direction: Literal["正面", "负面", "中性"] = Field(description="方向")
    description: str = Field(description="具体风险或利好描述")
    targets: list[str] = Field(default_factory=list, description="受影响的标的或板块")


class AffectedTarget(BaseModel):
    name: str = Field(description="标的名称")
    target_type: Literal["个股", "板块", "指数", "宏观", "行业"] = Field(description="标的类型")
    impact: Literal["直接受益", "间接受益", "直接受损", "间接受损", "影响不确定"] = Field(description="影响方向")


class NarrativeLink(BaseModel):
    related_event: str = Field(description="关联事件简述")
    link_type: Literal["前因", "后续", "平行", "对比", "延续", "关联"] = Field(description="关联类型")


# ── NarrativeExtract: four-layer structured output ──

class NarrativeExtract(BaseModel):
    """四层结构化叙事提取结果"""

    # Layer 1: 基础事实
    publish_time: str = Field(description="原文发布时间，ISO 8601")
    source: str = Field(default="财联社", description="信息来源")
    text_type: TextType = Field(description="文本类型")
    main_subject: str = Field(description="核心主体（谁/什么机构/什么事件）")

    # Layer 2: 叙事核心
    core_story: str = Field(description="客观事实摘要，禁止主观预判和市场推演")
    actor_list: list[Actor] = Field(default_factory=list, description="参与主体列表")
    action_behavior: str = Field(description="核心动作/行为描述")
    scene_context: str = Field(description="场景背景（行业、市场、政策环境）")

    # Layer 3: 分类属性
    narrative_mode: NarrativeMode = Field(description="叙事模式")
    narrative_trend: NarrativeTrend = Field(description="叙事趋势方向")
    narrative_firmness: NarrativeFirmness = Field(description="叙事确定性")
    keyword_core: list[str] = Field(default_factory=list, description="核心关键词（3-5个）")

    # Layer 4: 量化映射
    direct_causal_chain: list[CausalLink] = Field(
        default_factory=list,
        description="直接因果链，仅取原文显性因果，不脑补",
    )
    potential_risk_benefit: list[RiskBenefit] = Field(
        default_factory=list, description="潜在风险与利好"
    )
    sentiment_score: float = Field(
        ge=-1.0, le=1.0, description="情感得分 [-1, 1]，研报看多≠市场实际表现"
    )
    narrative_intensity: float = Field(
        ge=0.0, le=1.0, description="叙事强度 [0, 1]，衡量该事件的信息量和影响力"
    )
    affected_targets: list[AffectedTarget] = Field(
        default_factory=list, description="受影响标的列表"
    )
    narrative_link: list[NarrativeLink] = Field(
        default_factory=list, description="叙事关联链接"
    )
