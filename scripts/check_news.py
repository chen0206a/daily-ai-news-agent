"""Fetch real sources and retain metadata + short excerpts; never fabricate fallback entries."""
import argparse
import json
from pathlib import Path

from app.db import utcnow
from app.services.news import SOURCES, NewsService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/live-news.json")
    parser.add_argument("--days", default=7, type=int)
    args = parser.parse_args()
    news = NewsService()
    result = news.search("AI LLM agent", list(SOURCES), args.days)
    fetched = []
    for candidate in result["candidates"][:5]:
        try:
            article = news.fetch(candidate)
            fetched.append({k: article[k] for k in ("url", "title", "source", "published_at", "fetched_at", "sha256", "injection_suspected")}
                           )
        except Exception as exc:
            fetched.append({"url": candidate["url"], "error": str(exc)})
    result["candidates"] = [{k: v for k, v in c.items() if k != "snippet"} for c in result["candidates"]]
    report = {"kind": "REAL_NETWORK_FETCH_NO_LLM", "executed_at": utcnow(), "search": result, "articles": fetched}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Real RSS candidates: {len(result['candidates'])}; fetched: {sum('sha256' in a for a in fetched)}; errors: {len(result['source_errors'])}")
    return 0 if any("sha256" in a for a in fetched) else 1


if __name__ == "__main__":
    raise SystemExit(main())
