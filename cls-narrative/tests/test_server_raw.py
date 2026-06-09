"""Test with the exact raw data from production server — full request/response logging"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import NarrativeExtract
from prompt import build_messages
import urllib.request
import httpx

raw = json.loads(urllib.request.urlopen("http://124.222.117.105:8900/api/raw/2393235").read())
msgs = build_messages(raw)

print("=" * 80)
print("RAW DATA")
print("=" * 80)
print(json.dumps(raw, ensure_ascii=False, indent=2))

print("\n" + "=" * 80)
print("REQUEST MESSAGES")
print("=" * 80)
for i, msg in enumerate(msgs):
    print(f"\n--- messages[{i}] role={msg['role']} ---")
    print(msg["content"] if isinstance(msg["content"], str) else json.dumps(msg["content"], ensure_ascii=False, indent=2))

# Build the exact request payload
payload = {
    "model": "deepseek-v4-flash",
    "max_tokens": 4096,
    "temperature": 0.7,
    "system": msgs[0]["content"],
    "messages": msgs[1:],
    "tools": [{
        "name": "extract_narrative",
        "description": "Extract structured narrative data",
        "input_schema": NarrativeExtract.model_json_schema(),
    }],
    "tool_choice": {"type": "tool", "name": "extract_narrative"},
    "thinking": {"type": "disabled"},
}

print("\n" + "=" * 80)
print("FULL REQUEST PAYLOAD")
print("=" * 80)
print(json.dumps(payload, ensure_ascii=False, indent=2))

# Send request
print("\n" + "=" * 80)
print("SENDING REQUEST...")
print("=" * 80)
t0 = time.time()
resp = httpx.post(
    "https://api.deepseek.com/anthropic/v1/messages",
    headers={
        "x-api-key": "sk-6eb6ad5d52e44d3eb48591a448a63833",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    },
    json=payload,
    timeout=120.0,
)
elapsed = time.time() - t0

print(f"\nStatus: {resp.status_code}")
print(f"Latency: {elapsed:.1f}s")

print("\n" + "=" * 80)
print("FULL RESPONSE")
print("=" * 80)
body = resp.json()
print(json.dumps(body, ensure_ascii=False, indent=2))

# Parse result
print("\n" + "=" * 80)
print("PARSED RESULT")
print("=" * 80)
for block in body.get("content", []):
    if block["type"] == "tool_use" and block.get("input"):
        try:
            result = NarrativeExtract.model_validate(block["input"])
            print("OK")
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"VALIDATION ERROR: {e}")
    elif block["type"] == "tool_use":
        print("EMPTY tool_use input")
    elif block["type"] == "text":
        print(f"TEXT: {block['text'][:300]}")
    elif block["type"] == "thinking":
        print(f"THINKING ({len(block.get('thinking', ''))} chars)")

# ── Test 2: cache-busting ──
print("\n\n" + "=" * 80)
print("CACHE-BUSTING TEST (timestamp prefix in system prompt)")
print("=" * 80)

busted_payload = {**payload}
busted_payload["system"] = f"[retry-id:{time.time_ns()}] " + payload["system"]

print("\n--- System prompt (first 120 chars) ---")
print(busted_payload["system"][:120] + "...")

print("\nSENDING REQUEST...")
t0 = time.time()
resp2 = httpx.post(
    "https://api.deepseek.com/anthropic/v1/messages",
    headers={
        "x-api-key": "sk-6eb6ad5d52e44d3eb48591a448a63833",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    },
    json=busted_payload,
    timeout=120.0,
)
elapsed2 = time.time() - t0
print(f"Status: {resp2.status_code}  Latency: {elapsed2:.1f}s")

body2 = resp2.json()
print("\n--- Full Response ---")
print(json.dumps(body2, ensure_ascii=False, indent=2))

print("\n--- Parsed Result ---")
for block in body2.get("content", []):
    if block["type"] == "tool_use" and block.get("input"):
        try:
            result = NarrativeExtract.model_validate(block["input"])
            print("OK")
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"VALIDATION ERROR: {e}")
    elif block["type"] == "tool_use":
        print("EMPTY tool_use input")
    elif block["type"] == "text":
        print(f"TEXT: {block['text'][:300]}")
    elif block["type"] == "thinking":
        print(f"THINKING ({len(block.get('thinking', ''))} chars)")
