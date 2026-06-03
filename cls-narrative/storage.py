from __future__ import annotations

import json
import os
import time
from pathlib import Path

import aiosqlite

from config import DB_PATH

_CREATE_RAW = """
CREATE TABLE IF NOT EXISTS raw (
    id        INTEGER PRIMARY KEY,
    level     TEXT    NOT NULL DEFAULT '',
    time      TEXT    NOT NULL DEFAULT '',
    title     TEXT    NOT NULL DEFAULT '',
    brief     TEXT    NOT NULL DEFAULT '',
    content   TEXT    NOT NULL DEFAULT '',
    stocks    TEXT    NOT NULL DEFAULT '[]',
    subjects  TEXT    NOT NULL DEFAULT '[]',
    received_at REAL  NOT NULL DEFAULT 0
);
"""

_CREATE_NARRATIVE = """
CREATE TABLE IF NOT EXISTS narrative (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id                INTEGER NOT NULL REFERENCES raw(id),
    narrative_id          TEXT    NOT NULL,
    publish_time          TEXT    NOT NULL DEFAULT '',
    source                TEXT    NOT NULL DEFAULT '',
    text_type             TEXT    NOT NULL DEFAULT '',
    main_subject          TEXT    NOT NULL DEFAULT '',
    core_story            TEXT    NOT NULL DEFAULT '',
    actor_list            TEXT    NOT NULL DEFAULT '[]',
    action_behavior       TEXT    NOT NULL DEFAULT '',
    scene_context         TEXT    NOT NULL DEFAULT '',
    narrative_mode        TEXT    NOT NULL DEFAULT '',
    narrative_trend       TEXT    NOT NULL DEFAULT '',
    narrative_firmness    TEXT    NOT NULL DEFAULT '',
    keyword_core          TEXT    NOT NULL DEFAULT '[]',
    direct_causal_chain   TEXT    NOT NULL DEFAULT '[]',
    potential_risk_benefit TEXT   NOT NULL DEFAULT '[]',
    sentiment_score       REAL    NOT NULL DEFAULT 0,
    narrative_intensity   REAL    NOT NULL DEFAULT 0,
    affected_targets      TEXT    NOT NULL DEFAULT '[]',
    narrative_link        TEXT    NOT NULL DEFAULT '[]',
    extracted_at          REAL    NOT NULL DEFAULT 0,
    model_version         TEXT    NOT NULL DEFAULT '',
    retry_count           INTEGER NOT NULL DEFAULT 0
);
"""

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _db.executescript(_CREATE_RAW + _CREATE_NARRATIVE)
        await _db.commit()
    return _db


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def save_raw(msg: dict) -> None:
    db = await get_db()
    now = time.time()
    await db.execute(
        """INSERT OR REPLACE INTO raw
           (id, level, time, title, brief, content, stocks, subjects, received_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            msg["id"],
            msg.get("level", ""),
            msg.get("time", ""),
            msg.get("title", ""),
            msg.get("brief", ""),
            msg.get("content", ""),
            json.dumps(msg.get("stocks", []), ensure_ascii=False),
            json.dumps(msg.get("subjects", []), ensure_ascii=False),
            now,
        ),
    )
    await db.commit()


async def _next_narrative_id() -> str:
    from datetime import datetime

    db = await get_db()
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"NAR-{today}-"
    row = await db.execute(
        "SELECT narrative_id FROM narrative WHERE narrative_id LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + "%",),
    )
    last = await row.fetchone()
    if last and last[0].startswith(prefix):
        try:
            seq = int(last[0].split("-")[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:03d}"


async def save_narrative(raw_id: int, ne: "NarrativeExtract", model_version: str, retry_count: int = 0) -> None:  # noqa: F821
    from models import NarrativeExtract  # deferred to avoid circular

    db = await get_db()
    now = time.time()
    narrative_id = await _next_narrative_id()
    data = ne.model_dump()
    await db.execute(
        """INSERT INTO narrative (
            raw_id, narrative_id, publish_time, source, text_type, main_subject,
            core_story, actor_list, action_behavior, scene_context,
            narrative_mode, narrative_trend, narrative_firmness, keyword_core,
            direct_causal_chain, potential_risk_benefit,
            sentiment_score, narrative_intensity,
            affected_targets, narrative_link,
            extracted_at, model_version, retry_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            raw_id,
            narrative_id,
            data["publish_time"],
            data["source"],
            data["text_type"],
            data["main_subject"],
            data["core_story"],
            json.dumps(data["actor_list"], ensure_ascii=False),
            data["action_behavior"],
            data["scene_context"],
            data["narrative_mode"],
            data["narrative_trend"],
            data["narrative_firmness"],
            json.dumps(data["keyword_core"], ensure_ascii=False),
            json.dumps(data["direct_causal_chain"], ensure_ascii=False),
            json.dumps(data["potential_risk_benefit"], ensure_ascii=False),
            data["sentiment_score"],
            data["narrative_intensity"],
            json.dumps(data["affected_targets"], ensure_ascii=False),
            json.dumps(data["narrative_link"], ensure_ascii=False),
            now,
            model_version,
            retry_count,
        ),
    )
    await db.commit()


async def get_raw(raw_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM raw WHERE id = ?", (raw_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_narrative_by_raw(raw_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM narrative WHERE raw_id = ?", (raw_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None
