"""
Test: Zhipu AI via Anthropic SDK
智谱 Anthropic 兼容接口测试
"""
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from config import LLM_API_KEY
from prompt import build_messages
from models import NarrativeExtract

ZHIPU_ANTHROPIC_BASE = "https://open.bigmodel.cn/api/anthropic"

# ── Sample news ──
SAMPLE_RAW = {
    "id": 999999,
    "level": "B",
    "time": "2025-01-15 14:30:00",
    "title": "工信部：加快推动新能源汽车产业发展 研究制定相关扶持政策",
    "brief": "工信部表示将进一步加大新能源汽车产业支持力度，研究制定新一轮扶持政策",
    "content": """
工业和信息化部今日召开新闻发布会，表示将加快推动新能源汽车产业发展。
1. 研究制定新一轮新能源汽车购置税减免政策；
2. 推动智能网联汽车标准体系建设；
3. 支持充电基础设施进一步覆盖下沉市场。
相关负责人表示，2026年国内新能源汽车渗透率目标为50%以上，相关扶持政策将持续发力。
    """,
    "stocks": [
        {"code": "300750", "name": "宁德时代"},
        {"code": "002594", "name": "比亚迪"},
    ],
    "subjects": ["新能源汽车", "产业政策"],
}


def extract_json_from_text(text: str) -> Optional[dict]:
    """Extract JSON object from text response, stripping markdown fences."""
    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n```$", "", text.strip())
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


def show_result(ne: NarrativeExtract):
    data = ne.model_dump()
    for key, val in data.items():
        if isinstance(val, list):
            print(f"  {key}: [{len(val)} items]")
            for item in val[:3]:
                if isinstance(item, dict):
                    print(f"    - {json.dumps(item, ensure_ascii=False)}")
                else:
                    print(f"    - {item}")
        else:
            print(f"  {key}: {val}")


def test_model(model: str, extra_body: dict | None = None):
    client = anthropic.Anthropic(
        api_key=LLM_API_KEY,
        base_url=ZHIPU_ANTHROPIC_BASE,
    )

    messages = build_messages(SAMPLE_RAW)
    system_prompt = messages[0]["content"]
    user_messages = messages[1:]

    label = f"{model} extra_body={extra_body}" if extra_body else model
    print(f"\n{'='*60}")
    print(f"Model: {label}")
    print(f"Target fields: {len(NarrativeExtract.model_json_schema()['properties'])}")

    tool_schema = NarrativeExtract.model_json_schema()

    kwargs = dict(
        model=model,
        max_tokens=4096,
        temperature=0.1,
        system=system_prompt,
        messages=user_messages,
        tools=[{
            "name": "extract_narrative",
            "description": "Extract structured narrative data from financial news",
            "input_schema": tool_schema,
        }],
        tool_choice={"type": "tool", "name": "extract_narrative"},
    )
    if extra_body:
        kwargs["extra_body"] = extra_body

    t0 = time.time()
    try:
        response = client.messages.create(**kwargs)
        elapsed = time.time() - t0
        print(f"Latency: {elapsed:.1f}s")

        tool_use = None
        text_blocks: list[str] = []
        for block in response.content:
            if block.type == "tool_use":
                tool_use = block
            elif block.type == "text":
                text_blocks.append(block.text)

        if tool_use:
            print("Response mode: tool_use")
            raw_data = tool_use.input
        elif text_blocks:
            raw_json = "".join(text_blocks)
            print("Response mode: text -> JSON")
            print(f"Raw (first 300 chars): {raw_json[:300]}")
            raw_data = extract_json_from_text(raw_json)
            if raw_data is None:
                print("ERROR: cannot extract JSON")
                return
        else:
            print("ERROR: empty response")
            print(f"Content: {response.content}")
            return

        try:
            result = NarrativeExtract.model_validate(raw_data)
            print("PARSED OK")
            show_result(result)
        except Exception as e:
            # Show first 5 errors
            errors = str(e).split("\n")
            print(f"VALIDATION ERRORS ({sum(1 for l in errors if '[' in l and 'type=' in l)} total, showing first 5):")
            for line in errors[:6]:
                if line.strip():
                    print(f"  {line.strip()}")

        print(f"Usage: input={response.usage.input_tokens} output={response.usage.output_tokens}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"ERROR after {elapsed:.1f}s: {type(e).__name__}: {e}")


if __name__ == "__main__":
    # Test glm-4.7-flashx with and without thinking
    test_model("glm-4.7-flashx", extra_body={"enable_thinking": False})
