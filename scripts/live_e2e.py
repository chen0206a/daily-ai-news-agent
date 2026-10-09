"""Real DeepSeek + real news + SQLite + in-app delivery through the application API.

This is opt-in, consumes API credit, never sends email, and uses no scripted model.
Credentials remain in ignored evidence/private/demo-login.json.
"""
import json
import secrets
import time
import uuid
from pathlib import Path

from app.agent.graph import redact
from app.api import create_app
from app.config import Settings
from app.db import utcnow
from fastapi.testclient import TestClient
import httpx


def main():
    settings = Settings(worker_enabled=True, scheduler_enabled=False)
    if not settings.deepseek_api_key:
        print("BLOCKED: DEEPSEEK_API_KEY is not configured. No model result was fabricated.")
        return 2
    # Use a running local API when available, otherwise start an embedded app WITH its real worker.
    # Never bypass the queue claim or race a second worker against the live application.
    try:
        health = httpx.get("http://127.0.0.1:8000/api/health", timeout=2, trust_env=False)
        external = health.status_code == 200 and health.json().get("model") is not None
    except httpx.HTTPError:
        external = False
    client_context = httpx.Client(base_url="http://127.0.0.1:8000", timeout=15, trust_env=False) if external else TestClient(create_app(settings))
    headers = {"X-Requested-With": "daily-ai-news", "Origin": settings.frontend_origin}
    email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
    password = secrets.token_urlsafe(24)
    private = Path("evidence/private")
    private.mkdir(parents=True, exist_ok=True)
    (private / "demo-login.json").write_text(json.dumps({"email": email, "password": password}, indent=2), encoding="utf-8")
    with client_context as client:
        response = client.post("/api/auth/register", json={"email": email, "password": password}, headers=headers)
        response.raise_for_status()
        prefs = client.get("/api/preferences").json()
        prefs.update(sources=["openai", "google_ai", "techcrunch"], topics=["AI", "agents", "LLM"], max_articles=3,
                     lookback_days=7, email_enabled=False, in_app_enabled=True)
        client.put("/api/preferences", json=prefs, headers=headers).raise_for_status()
        response = client.post("/api/runs", headers={**headers, "Idempotency-Key": uuid.uuid4().hex})
        response.raise_for_status()
        run_id = response.json()["id"]
        print(f"Live run started: {run_id}; model={settings.deepseek_model}", flush=True)
        deadline = time.monotonic() + settings.run_timeout_seconds + 30
        while True:
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] not in {"queued", "running"} or time.monotonic() >= deadline:
                break
            time.sleep(1)
        for _ in range(8):
            if client.get("/api/notifications").json() or run["status"] != "completed":
                break
            time.sleep(1)
        trace = client.get(f"/api/runs/{run_id}/trace").json()
        digests = client.get("/api/digests").json()
        digest = client.get(f"/api/digests/{digests[0]['id']}").json() if digests else None
        notifications = client.get("/api/notifications").json()
        # User identifiers and entire article bodies are kept in local SQLite, not the public evidence artifact.
        public_trace = []
        for event in trace:
            data = event["data"]
            if event["kind"] == "tool" and data.get("name") == "fetch_article" and data.get("ok"):
                data["result"] = {k: v for k, v in data["result"].items() if k not in ("content", "snippet")}
            if event["kind"] == "tool" and data.get("name") == "search_news" and data.get("ok"):
                data["result"]["candidates"] = [{k: v for k, v in c.items() if k != "snippet"} for c in data["result"]["candidates"]]
            public_trace.append({"kind": event["kind"], "created_at": event["created_at"], "data": data})
        report = {"kind": "REAL_DEEPSEEK_END_TO_END", "executed_at": utcnow(), "run_id": run_id,
                  "status": run["status"], "error": run["error"], "final_text": run["final_text"],
                  "model": settings.deepseek_model, "trace": public_trace,
                  "digest": {k: digest[k] for k in ("id", "title", "digest_date", "items", "deliveries")} if digest else None,
                  "in_app_notifications": len(notifications), "email": "NOT_SENT; disabled for this demo"}
        Path("evidence/live-e2e.json").write_text(json.dumps(redact(report, settings.deepseek_api_key), ensure_ascii=False, indent=2), encoding="utf-8")
        if digest:
            Path("evidence/verified-digest.md").write_text(digest["markdown"].rstrip() + "\n", encoding="utf-8")
        print(f"Live run status: {run['status']}; digest={bool(digest)}; notifications={len(notifications)}; error={run['error']}")
        return 0 if run["status"] == "completed" and digest and notifications else 1


if __name__ == "__main__":
    raise SystemExit(main())
