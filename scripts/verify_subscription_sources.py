"""Genuine network checks in an isolated temporary database; never overwrites old evidence."""
import argparse
import json
import secrets
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.api import create_app
from app.config import Settings
from app.db import utcnow

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-Requested-With": "daily-ai-news", "Origin": "http://localhost:3000"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/subscription-enhancement/sources-live.json")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output already exists; choose a new --output file to preserve evidence")
    report = {"checked_at": utcnow(), "kind": "actual HTTPS RSS requests, no LLM, disposable database", "presets": []}
    with tempfile.TemporaryDirectory(prefix="daybreak-feeds-") as folder:
        app = create_app(Settings(data_dir=Path(folder), worker_enabled=False, scheduler_enabled=False, deepseek_api_key=""))
        with TestClient(app) as client:
            client.post("/api/auth/register", headers=HEADERS, json={"email": "live-feeds@example.com", "password": secrets.token_urlsafe(24)}).raise_for_status()
            for source in client.get("/api/sources").json():
                result = client.post(f"/api/sources/{source['id']}/check", headers=HEADERS)
                result.raise_for_status()
                report["presets"].append(result.json())
                print(f"{source['id']}: {'OK' if result.json()['ok'] else result.json()['error']}", flush=True)
            available = [s for s in report["presets"] if s["ok"]]
            if not available:
                report["custom"] = {"error": "No reachable preset available for a genuine custom-feed check"}
            else:
                chosen = next((s for s in available if s["id"] in {"arxiv", "microsoft_research"}), available[0])
                created = client.post("/api/sources", headers=HEADERS, json={"name": "Live custom RSS validation", "url": chosen["feed"]})
                created.raise_for_status()
                custom = created.json()
                sid = custom["id"]
                client.put(f"/api/sources/{sid}", headers=HEADERS, json={"enabled": True}).raise_for_status()
                prefs = client.get("/api/preferences").json()
                prefs.update(sources=[sid], topics=["language models"], lookback_days=14,
                             watch_objects=[{"type": "topic", "name": "LLM", "aliases": ["AI", "artificial intelligence", "large language model", "language models"]}])
                client.put("/api/preferences", headers=HEADERS, json=prefs).raise_for_status()
                preview = client.post("/api/search-preview", headers=HEADERS)
                preview.raise_for_status()
                report["custom"] = {k: v for k, v in custom.items() if k != "id"}
                report["preview"] = preview.json()
                report["side_effect_counts"] = {table: app.state.db.one(f"SELECT count(*) AS n FROM {table}")["n"] for table in ("runs", "articles", "digests", "deliveries", "notifications")}
                failed = client.post("/api/sources", headers=HEADERS, json={"name": "Live invalid HTML feed", "url": "https://openai.com/"})
                failed.raise_for_status()
                report["invalid_feed"] = {k: v for k, v in failed.json().items() if k != "id"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidence saved: {args.output.name}")


if __name__ == "__main__":
    main()
