from __future__ import annotations

import asyncio
import logging
import traceback

import instructor
import litellm

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MAX_RETRIES
from models import NarrativeExtract
from prompt import build_messages
from storage import save_narrative

logger = logging.getLogger(__name__)

# Use litellm.acompletion for async
_async_client = instructor.from_litellm(litellm.acompletion)


async def extract_narrative(raw: dict) -> NarrativeExtract:
    messages = build_messages(raw)

    kwargs: dict = {
        "model": LLM_MODEL,
        "messages": messages,
        "response_model": NarrativeExtract,
        "max_retries": 0,  # we handle retries ourselves
        "temperature": 0.1,
        "extra_body": {"enable_thinking": False},
    }
    if LLM_API_KEY:
        kwargs["api_key"] = LLM_API_KEY
    if LLM_BASE_URL:
        kwargs["api_base"] = LLM_BASE_URL

    return await _async_client.create(**kwargs)


async def extract_and_save(raw: dict) -> None:
    raw_id = raw["id"]
    model_version = LLM_MODEL

    for attempt in range(MAX_RETRIES):
        try:
            result = await extract_narrative(raw)
            await save_narrative(raw_id, result, model_version, retry_count=attempt)
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
