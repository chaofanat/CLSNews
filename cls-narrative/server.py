from __future__ import annotations

import hashlib
import hmac
import json
import logging
import asyncio
import traceback
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import HTMLResponse as _HTMLResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import LLM_CONCURRENCY, SERVER_PORT, WEBHOOK_SECRET
from extractor import enqueue_extraction, get_running_tasks, start_workers
from models import WebhookMessage
from storage import close_db, delete_failed, get_db, get_failed_raws, get_orphaned_raws, list_failed, save_raw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="cls-narrative")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _verify_secret(request: Request, body: bytes) -> bool:
    if not WEBHOOK_SECRET:
        return True
    sig = request.headers.get("X-Webhook-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def _parse_json_fields(row: dict, *fields: str) -> dict:
    for f in fields:
        v = row.get(f)
        if isinstance(v, str):
            try:
                row[f] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                pass
    return row


_JSON_FIELDS_RAW = ("stocks", "subjects")

_JSON_FIELDS_NARRATIVE = (
    "actor_list", "keyword_core", "direct_causal_chain",
    "potential_risk_benefit", "affected_targets", "narrative_link",
)


# ── Webhook ingest ──


class WebhookResponse(BaseModel):
    status: str
    count: int


@app.post("/webhook", response_model=WebhookResponse)
async def receive(
    message: WebhookMessage,
    request: Request,
):
    if WEBHOOK_SECRET:
        body = await request.body()
        if not _verify_secret(request, body):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="invalid signature")

    await save_raw(message.model_dump())
    await enqueue_extraction(message.model_dump())

    logger.info("received message #%d", message.id)
    return {"status": "ok", "count": 1}


# ── Read-only query API ──


@app.get("/api/raw")
async def list_raw(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    level: Optional[str] = None,
):
    db = await get_db()
    clauses: list[str] = []
    params: list = []

    if level:
        clauses.append("level = ?")
        params.append(level)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params += [limit, offset]

    rows = await db.execute_fetchall(
        f"SELECT * FROM raw {where} ORDER BY id DESC LIMIT ? OFFSET ?", params
    )
    total = await db.execute_fetchall(
        f"SELECT COUNT(*) as cnt FROM raw {where}", params[:-2]
    )
    return {
        "total": total[0]["cnt"],
        "items": [_parse_json_fields(dict(r), *_JSON_FIELDS_RAW) for r in rows],
    }


@app.get("/api/raw/{raw_id}")
async def get_raw_detail(raw_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM raw WHERE id = ?", (raw_id,))
    row = await cursor.fetchone()
    if not row:
        return {"error": "not found"}, 404
    return _parse_json_fields(dict(row), *_JSON_FIELDS_RAW)


@app.get("/api/narrative")
async def list_narrative(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    text_type: Optional[str] = None,
    narrative_mode: Optional[str] = None,
    narrative_trend: Optional[str] = None,
    narrative_firmness: Optional[str] = None,
    sentiment_min: Optional[float] = None,
    sentiment_max: Optional[float] = None,
    intensity_min: Optional[float] = None,
    intensity_max: Optional[float] = None,
):
    db = await get_db()
    clauses: list[str] = []
    params: list = []

    if text_type:
        clauses.append("text_type = ?")
        params.append(text_type)
    if narrative_mode:
        clauses.append("narrative_mode = ?")
        params.append(narrative_mode)
    if narrative_trend:
        clauses.append("narrative_trend = ?")
        params.append(narrative_trend)
    if narrative_firmness:
        clauses.append("narrative_firmness = ?")
        params.append(narrative_firmness)
    if sentiment_min is not None:
        clauses.append("sentiment_score >= ?")
        params.append(sentiment_min)
    if sentiment_max is not None:
        clauses.append("sentiment_score <= ?")
        params.append(sentiment_max)
    if intensity_min is not None:
        clauses.append("narrative_intensity >= ?")
        params.append(intensity_min)
    if intensity_max is not None:
        clauses.append("narrative_intensity <= ?")
        params.append(intensity_max)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params += [limit, offset]

    rows = await db.execute_fetchall(
        f"SELECT * FROM narrative {where} ORDER BY id DESC LIMIT ? OFFSET ?", params
    )
    total = await db.execute_fetchall(
        f"SELECT COUNT(*) as cnt FROM narrative {where}", params[:-2]
    )
    return {
        "total": total[0]["cnt"],
        "items": [_parse_json_fields(dict(r), *_JSON_FIELDS_NARRATIVE) for r in rows],
    }


@app.get("/api/narrative/{narrative_id}")
async def get_narrative_detail(narrative_id: str):
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM narrative WHERE narrative_id = ?", (narrative_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return {"error": "not found"}, 404
    return _parse_json_fields(dict(row), *_JSON_FIELDS_NARRATIVE)


@app.get("/api/raw/{raw_id}/narrative")
async def get_raw_narrative(raw_id: int):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM narrative WHERE raw_id = ?", (raw_id,))
    row = await cursor.fetchone()
    if not row:
        return {"error": "not found"}, 404
    return _parse_json_fields(dict(row), *_JSON_FIELDS_NARRATIVE)


@app.get("/api/stats")
async def stats():
    db = await get_db()
    raw_count = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM raw")
    nar_count = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM narrative")

    mode_dist = await db.execute_fetchall(
        "SELECT narrative_mode, COUNT(*) as cnt FROM narrative GROUP BY narrative_mode"
    )
    trend_dist = await db.execute_fetchall(
        "SELECT narrative_trend, COUNT(*) as cnt FROM narrative GROUP BY narrative_trend"
    )
    type_dist = await db.execute_fetchall(
        "SELECT text_type, COUNT(*) as cnt FROM narrative GROUP BY text_type"
    )

    avg_scores = await db.execute_fetchall(
        "SELECT AVG(sentiment_score) as avg_sentiment, AVG(narrative_intensity) as avg_intensity FROM narrative"
    )

    return {
        "raw_count": raw_count[0]["cnt"],
        "narrative_count": nar_count[0]["cnt"],
        "failed_count": (await db.execute_fetchall("SELECT COUNT(*) as cnt FROM extraction_failed"))[0]["cnt"],
        "avg_sentiment": round(avg_scores[0]["avg_sentiment"] or 0, 4),
        "avg_intensity": round(avg_scores[0]["avg_intensity"] or 0, 4),
        "distribution": {
            "narrative_mode": {r["narrative_mode"]: r["cnt"] for r in mode_dist},
            "narrative_trend": {r["narrative_trend"]: r["cnt"] for r in trend_dist},
            "text_type": {r["text_type"]: r["cnt"] for r in type_dist},
        },
    }


# ── Failed extraction management ──


@app.get("/api/failed")
async def api_list_failed(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items = await list_failed(limit, offset)
    return {"items": items, "count": len(items)}


@app.post("/api/failed/backfill")
async def trigger_backfill(background_tasks: BackgroundTasks):
    """Manually trigger orphaned raw backfill."""
    background_tasks.add_task(_backfill_orphans)
    return {"status": "backfill started"}


@app.post("/api/failed/{raw_id}/retry")
async def retry_failed(raw_id: int, background_tasks: BackgroundTasks):
    from storage import get_raw
    raw = await get_raw(raw_id)
    if not raw:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="raw message not found")

    # Check if already has narrative
    nar = await db.execute_fetchall("SELECT id FROM narrative WHERE raw_id = ?", (raw_id,)) if False else None
    db = await get_db()
    existing = await db.execute_fetchall("SELECT id FROM narrative WHERE raw_id = ?", (raw_id,))
    if existing:
        await delete_failed(raw_id)
        return {"status": "skipped", "message": "narrative already exists"}

    background_tasks.add_task(_retry_one, raw_id, raw)
    return {"status": "retrying", "raw_id": raw_id}


async def _retry_one(raw_id: int, raw: dict):
    # Success/failure cleanup is handled by extract_and_save internally
    await enqueue_extraction(raw)
    logger.info("retry enqueued for raw_id=%s", raw_id)


async def _backfill_orphans():
    """Register orphaned raw records (no narrative + no failed) into extraction_failed.
    Actual retry is handled by the main loop."""
    from storage import save_failed
    orphans = await get_orphaned_raws()
    if not orphans:
        return
    logger.info("backfill: registering %d orphaned raw records", len(orphans))
    for row in orphans:
        await save_failed(row["id"], "backfilled: no prior extraction record")


async def _retry_failed_loop():
    await asyncio.sleep(60)  # wait for startup
    while True:
        try:
            # Also pick up new orphans each cycle
            await _backfill_orphans()
        except Exception:
            logger.error("backfill orphans error: %s", traceback.format_exc(limit=1))
        try:
            failed = await get_failed_raws()
            if failed:
                logger.info("auto-retry: found %d failed extractions", len(failed))
                for row in failed:
                    raw = {k: row[k] for k in ("id", "level", "time", "title", "brief", "content", "stocks", "subjects") if k in row}
                    await _retry_one(row["raw_id"], raw)
                    await asyncio.sleep(5)  # pace between retries
        except Exception:
            logger.error("auto-retry loop error: %s", traceback.format_exc(limit=1))
        await asyncio.sleep(1800)  # every 30 minutes


@app.on_event("startup")
async def startup():
    start_workers(LLM_CONCURRENCY)
    asyncio.create_task(_retry_failed_loop())


# ── Running tasks ──


@app.get("/api/running")
async def running_tasks():
    tasks = get_running_tasks()
    return {
        "count": len(tasks["running"]),
        "queued": tasks["queued"],
        "workers": tasks["workers"],
        "items": tasks["running"],
    }


# ── Dashboard ──


@app.get("/dashboard", response_class=_HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return _HTMLResponse(html_path.read_text("utf-8"))


# ── Health ──


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("shutdown")
async def shutdown():
    await close_db()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT)
