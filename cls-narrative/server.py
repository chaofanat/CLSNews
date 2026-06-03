from __future__ import annotations

import hashlib
import hmac
import logging
import traceback

from fastapi import BackgroundTasks, FastAPI, Request

from config import SERVER_PORT, WEBHOOK_SECRET
from extractor import extract_and_save
from storage import close_db, save_raw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="cls-narrative")


def _verify_secret(request: Request, body: bytes) -> bool:
    if not WEBHOOK_SECRET:
        return True
    sig = request.headers.get("X-Webhook-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


@app.post("/webhook")
async def receive(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    if not _verify_secret(request, body):
        return {"status": "error", "message": "invalid signature"}, 403

    payload = await request.json()
    messages = payload if isinstance(payload, list) else [payload]

    for msg in messages:
        await save_raw(msg)
        background_tasks.add_task(extract_and_save, msg)

    logger.info("received %d messages", len(messages))
    return {"status": "ok", "count": len(messages)}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("shutdown")
async def shutdown():
    await close_db()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT)
