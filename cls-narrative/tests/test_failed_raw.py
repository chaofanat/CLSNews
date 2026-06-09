"""Test the exact raw content that failed on production (raw_id=2393235)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from models import NarrativeExtract
from prompt import build_messages
import re


def _extract_json(text):
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n```\s*$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None

RAW = {
    "id": 2393235,
    "level": "C",
    "time": "2026-06-08 10:37:45",
    "title": "住建部：完善城市排水防涝体系 提升城市排水防涝能力",
    "brief": (
        "财联社6月8日电，住建部表示将落实城市更新规划，"
        "完善城市排水防涝体系，推进排水管渠、泵站、排涝通道等设施建设改造。"
    ),
    "content": (
        "住建部将会同有关部门落实城市更新规划，完善城市排水防涝体系，"
        "推进排水管渠、泵站、排涝通道、调蓄设施、智慧平台等城市排水设施建设改造，"
        "提高设施的建设标准，提升城市排水防涝能力。"
        "同时还将继续实施城市的污水管网建设，提升城市生活污水收集处理能力，"
        "因地制宜推进城市地下综合管廊建设。"
        "二是持续实施更新改造。对于供水管网，重点是对老化破损的市政配水管网进行更新改造，"
        "提高城市供水的安全保障能力。对于燃气管网，"
        "重点是改造材质落后、腐蚀严重的市政管道，消除安全隐患。"
        "对于供热管网，将重点实施城镇供热“温暖工程”，"
        "加快供热老化管线、低效换热站等的更新改造，降低热损失、保障安全运行。"
        "三是实施智能化建设改造。在加快管网建设改造的同时，"
        "统筹推进城市基础设施的生命线安全工程建设，"
        "实现对城市基础设施运行风险从监测发现到预警处置的全流程闭环管理。"
    ),
    "stocks": [],
    "subjects": ["基建投资"],
}

client = anthropic.Anthropic(
    api_key="sk-6eb6ad5d52e44d3eb48591a448a63833",
    base_url="https://api.deepseek.com/anthropic",
)

msgs = build_messages(RAW)
response = client.messages.create(
    model="deepseek-v4-flash",
    max_tokens=4096,
    temperature=0.1,
    system=msgs[0]["content"],
    messages=msgs[1:],
    tools=[{
        "name": "extract_narrative",
        "description": "Extract structured narrative data",
        "input_schema": NarrativeExtract.model_json_schema(),
    }],
    tool_choice={"type": "tool", "name": "extract_narrative"},
    extra_body={"thinking": {"type": "disabled"}},
)

payload = None
text_blocks = []
for block in response.content:
    if block.type == "tool_use":
        payload = block.input
        print(f"tool_use.input: {list(block.input.keys()) if block.input else 'EMPTY'}")
    elif block.type == "text":
        text_blocks.append(block.text)
        print(f"text block ({len(block.text)} chars)")

if payload:
    result = NarrativeExtract.model_validate(payload)
    print("PARSED OK")
    for key in ["text_type", "main_subject", "sentiment_score"]:
        print(f"  {key}: {getattr(result, key)}")
elif text_blocks:
    fallback = _extract_json("".join(text_blocks))
    if fallback:
        result = NarrativeExtract.model_validate(fallback)
        print("PARSED OK (from text fallback)")
    else:
        print("FAILED: empty payload and no parseable text")
else:
    print("FAILED: completely empty response")
