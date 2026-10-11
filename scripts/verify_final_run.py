"""Verify real model output against private SQLite evidence without exporting user records."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from app.config import Settings
from app.db import Database, utcnow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=Path("evidence/final-2026-10-11"))
    args = parser.parse_args()
    report = json.loads((args.evidence / "live-e2e.json").read_text(encoding="utf-8"))
    db = Database(Settings().db_path)
    run = db.one("SELECT * FROM runs WHERE id=?", (report["run_id"],))
    digest = db.one("SELECT * FROM digests WHERE run_id=? AND user_id=?", (run["id"], run["user_id"]))
    items = []
    for item in report["digest"]["items"]:
        article = db.one("SELECT * FROM articles WHERE id=? AND run_id=? AND user_id=?", (item["article_id"], run["id"], run["user_id"]))
        def normalize(text):
            return re.sub(r"\s+", " ", text).strip()
        checks = {"owned_current_run": bool(article), "exact_quote": bool(article and normalize(item["evidence_quote"]) in normalize(article["content"])),
                  "sha256_matches_body": bool(article and hashlib.sha256(article["content"].encode()).hexdigest() == item["sha256"] == article["sha256"]),
                  "citation_matches_fetched_url": bool(article and item["url"] == article["url"] and item["url"] in digest["markdown"]),
                  "quote_word_limit": len(item["evidence_quote"].split()) <= 25}
        items.append({"article_id": item["article_id"], "url": item["url"], "checks": checks})
    deliveries = db.all("SELECT channel,status FROM deliveries WHERE digest_id=? AND user_id=?", (digest["id"], run["user_id"]))
    notifications = db.one("SELECT count(*) AS n FROM notifications WHERE digest_id=? AND user_id=?", (digest["id"], run["user_id"]))["n"]
    model_events = [e["data"] for e in report["trace"] if e["kind"] == "model"]
    checks = {"run_completed": run["status"] == report["status"] == "completed", "real_response_ids": all(e.get("response_id") and e.get("model") != "scripted-test-double" for e in model_events),
              "all_article_checks": bool(items) and all(all(i["checks"].values()) for i in items), "notification_unique": notifications == 1,
              "in_app_sent": {"channel": "in_app", "status": "sent"} in deliveries, "no_email_delivery": all(d["channel"] != "email" for d in deliveries),
              "focus_in_saved_snapshot": json.loads(run["preferences"])["watch_objects"] == report["preferences"]["watch_objects"],
              "partial_failure_kept_valid_candidates": bool(report["preview"]["source_errors"] and report["preview"]["candidates"])}
    output = {"verified_at": utcnow(), "run_id": run["id"], "checks": checks, "articles": items, "deliveries": deliveries,
              "notifications": notifications, "note": "Verifies origin/quotes/hashes and side effects, not the semantic truth of model summaries."}
    (args.evidence / "citation-checks.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Persisted evidence checks:", checks)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
