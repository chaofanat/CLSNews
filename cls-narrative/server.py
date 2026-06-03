from __future__ import annotations

import hashlib
import hmac
import json
import logging
import traceback
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import SERVER_PORT, WEBHOOK_SECRET
from extractor import extract_and_save
from models import WebhookMessage
from storage import close_db, get_db, save_raw

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
    background_tasks: BackgroundTasks,
):
    if WEBHOOK_SECRET:
        body = await request.body()
        if not _verify_secret(request, body):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="invalid signature")

    await save_raw(message.model_dump())
    background_tasks.add_task(extract_and_save, message.model_dump())

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
        "avg_sentiment": round(avg_scores[0]["avg_sentiment"] or 0, 4),
        "avg_intensity": round(avg_scores[0]["avg_intensity"] or 0, 4),
        "distribution": {
            "narrative_mode": {r["narrative_mode"]: r["cnt"] for r in mode_dist},
            "narrative_trend": {r["narrative_trend"]: r["cnt"] for r in trend_dist},
            "text_type": {r["text_type"]: r["cnt"] for r in type_dist},
        },
    }


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
