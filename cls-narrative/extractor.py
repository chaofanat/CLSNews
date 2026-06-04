from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import traceback
from typing import Optional

import instructor

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_PROVIDER, MAX_RETRIES
from models import NarrativeExtract
from prompt import build_messages
from storage import delete_failed, save_failed, save_narrative

logger = logging.getLogger(__name__)

ZHIPU_ANTHROPIC_BASE = "https://open.bigmodel.cn/api/anthropic"

_NARRATIVE_TOOL_LITELLM = {
    "type": "function",
    "function": {
        "name": "extract_narrative",
        "description": "Extract structured narrative data from financial news",
        "parameters": NarrativeExtract.model_json_schema(),
    },
}

_NARRATIVE_TOOL_ANTHROPIC = {
    "name": "extract_narrative",
    "description": "Extract structured narrative data from financial news",
    "input_schema": NarrativeExtract.model_json_schema(),
}


def _create_clients():
    if LLM_PROVIDER == "litellm":
        import litellm
        return instructor.from_litellm(litellm.acompletion), None
    import anthropic
    import httpx
    base_url = LLM_BASE_URL or ZHIPU_ANTHROPIC_BASE
    return None, anthropic.AsyncAnthropic(
        api_key=LLM_API_KEY,
        base_url=base_url,
        timeout=httpx.Timeout(300.0, connect=30.0),
    )


def _extract_json(text: str) -> Optional[dict]:
    """Fallback: extract JSON object from text response (handles markdown fences)."""
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


_litellm_client, _anthropic_client = _create_clients()

# ── Unified extraction queue ──
_task_queue: asyncio.Queue | None = None
_workers: list[asyncio.Task] = []
_running_tasks: dict[int, dict] = {}
_worker_count = 0


async def extract_narrative(raw: dict) -> NarrativeExtract:
    messages = build_messages(raw)

    model = LLM_MODEL
    if model.startswith("zai/"):
        model = model[4:]

    if LLM_PROVIDER == "litellm":
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "response_model": NarrativeExtract,
            "max_retries": 0,
            "temperature": 0.1,
        }
        if LLM_API_KEY:
            kwargs["api_key"] = LLM_API_KEY
        if LLM_BASE_URL:
            kwargs["api_base"] = LLM_BASE_URL
        kwargs["extra_body"] = {"enable_thinking": False}
        kwargs["timeout"] = 300.0
        return await _litellm_client.create(**kwargs)

    # anthropic provider
    system = messages[0]["content"]
    user_msgs = messages[1:]

    t0 = time.time()
    logger.info("LLM request raw_id=%s model=%s", raw.get("id"), model)
    response = await _anthropic_client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.1,
        system=system,
        messages=user_msgs,
        tools=[_NARRATIVE_TOOL_ANTHROPIC],
        tool_choice={"type": "tool", "name": "extract_narrative"},
        extra_body={"enable_thinking": False},
        timeout=300.0,
    )
    elapsed = time.time() - t0

    tool_use = None
    text_blocks: list[str] = []
    for block in response.content:
        if block.type == "tool_use":
            tool_use = block
        elif block.type == "text":
            text_blocks.append(block.text)

    if tool_use:
        result = NarrativeExtract.model_validate(tool_use.input)
    else:
        data = _extract_json("".join(text_blocks))
        if data is None:
            raise ValueError("no tool_use or valid JSON in response")
        result = NarrativeExtract.model_validate(data)

    logger.info("LLM response raw_id=%s elapsed=%.1fs tokens(in=%d out=%d)",
                 raw.get("id"), elapsed,
                 response.usage.input_tokens, response.usage.output_tokens)
    return result


async def extract_and_save(raw: dict) -> None:
    """Process a single raw message: extract narrative + persist. Called by workers."""
    raw_id = raw["id"]
    model_version = LLM_MODEL

    _running_tasks[raw_id] = {"raw_id": raw_id, "title": raw.get("title", ""), "started_at": time.time()}
    try:
        for attempt in range(MAX_RETRIES):
            try:
                result = await extract_narrative(raw)
                await save_narrative(raw_id, result, model_version, retry_count=attempt)
                await delete_failed(raw_id)
                logger.info("extracted narrative for raw_id=%s (attempt=%d)", raw_id, attempt)
                return
            except Exception:
                delay = 2 ** attempt
                logger.warning(
                    "extraction failed for raw_id=%s attempt=%d, retry in %ds: %s",
                    raw_id,
                    attempt,
                    delay,
                    traceback.format_exc(),
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)

        logger.error("extraction permanently failed for raw_id=%s after %d retries", raw_id, MAX_RETRIES)
        await save_failed(raw_id, traceback.format_exc(limit=1))
    finally:
        _running_tasks.pop(raw_id, None)


# ── Queue / worker management ──

async def _worker(worker_id: int):
    while True:
        raw = await _task_queue.get()
        try:
            await extract_and_save(raw)
        except Exception:
            logger.exception("worker %d crashed on raw_id=%s", worker_id, raw.get("id"))
        finally:
            _task_queue.task_done()


async def enqueue_extraction(raw: dict) -> None:
    """Add a raw message to the extraction queue. Non-blocking for callers."""
    await _task_queue.put(raw)


def start_workers(n: int = 2):
    global _task_queue, _workers, _worker_count
    _worker_count = n
    _task_queue = asyncio.Queue()
    _workers = [asyncio.create_task(_worker(i)) for i in range(n)]
    logger.info("started %d extraction workers", n)


def get_running_tasks() -> list[dict]:
    """Return currently executing + queued tasks for the dashboard."""
    now = time.time()
    running = [
        {**t, "elapsed_s": round(now - t["started_at"], 1)}
        for t in _running_tasks.values()
    ]
    return {
        "running": running,
        "queued": _task_queue.qsize() if _task_queue else 0,
        "workers": _worker_count,
    }
