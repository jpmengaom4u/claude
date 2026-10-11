#!/usr/bin/env python3
"""Minimal client for Jev (typesafe/jev-1.13) via OpenRouter's Decisions route.

Usage:
    python3 jev.py request.json          # or: cat request.json | python3 jev.py -

request.json holds {"state": ..., "questions": {...}}; "model" defaults to
typesafe/jev-1.13. Prints one JSON object: the raw response plus
elapsed_ms, cost_usd, and a per-question "confidence" (Nouls get |2p-1|).

Auth: uses OPENROUTER_API_KEY if set. In a Claude Code cloud environment
with an OpenRouter network secret, the proxy adds the header instead, so
the key never touches this process. The key is never printed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"


def confidence(answer):
    if answer.get("type") == "noul":
        return round(abs(2 * answer["noul"] - 1), 4)
    return answer.get("confidence")


def ask(payload, timeout=60):
    payload = {"model": DEFAULT_MODEL, **payload}
    headers = {"Content-Type": "application/json", "X-OpenRouter-Title": "jev-skill"}
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            status = resp.status
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        raw = e.read().decode(errors="replace")
        return {"ok": False, "status": e.code, "elapsed_ms": round(elapsed), "error": raw}
    except urllib.error.URLError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {"ok": False, "status": None, "elapsed_ms": round(elapsed), "error": str(e.reason)}
    elapsed = (time.perf_counter() - start) * 1000
    for a in body.get("answers", {}).values():
        a["confidence"] = confidence(a)
    return {
        "ok": True,
        "status": status,
        "elapsed_ms": round(elapsed),
        "cost_usd": body.get("usage", {}).get("cost"),
        "response": body,
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "-"
    data = json.load(sys.stdin if src == "-" else open(src))
    result = ask(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)
