"""Read-only content/history/link audit. Reports locations and counts, never credential values."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from app.config import Settings
from app.db import utcnow

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(rb"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|news_session=[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|\$argon2id\$v=\d+\$m=\d+[^\s\"']+")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/final-2026-10-11/release-audit.json")
    args = parser.parse_args()
    settings = Settings()
    secrets = [v.encode() for v in (settings.deepseek_api_key, settings.smtp_password) if len(v) >= 8]
    credential_files = list((ROOT / "evidence/private").rglob("*.json"))
    for file in credential_files:
        value = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            secrets.extend(v.encode() for k, v in value.items() if k in {"password", "api_key", "token"} and isinstance(v, str) and len(v) >= 8)
    names = [n.decode() for n in git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0") if n]
    findings, links = [], []

    def scan(name, content):
        if any(value in content for value in secrets) or PATTERN.search(content):
            findings.append(name)

    forbidden = []
    for name in names:
        p = ROOT / name
        if not p.is_file():
            continue
        if (name.startswith((".env", "data/", "evidence/private/", "dist/", ".venv/")) and name != ".env.example") or any(part in {"node_modules", ".next", "__pycache__", "test-results", "playwright-report"} for part in Path(name).parts):
            forbidden.append(name)
        content = p.read_bytes()
        scan("working:" + name, content)
        if p.suffix.lower() == ".md":
            # Relative document/image destinations; network checks are a separate verification step.
            for dest in re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", content.decode("utf-8")):
                dest = dest.strip("<>")
                if not dest.startswith(("http:", "https:", "mailto:", "#")):
                    if not (p.parent / dest.split("#")[0]).exists():
                        links.append({"file": name, "target": dest})

    # Batch-read every reachable historical blob, including fetched origin refs.
    objects = git("rev-list", "--objects", "--all").decode().splitlines()
    requests = "\n".join(line.split(" ", 1)[0] for line in objects) + "\n"
    raw = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=requests.encode(), stdout=subprocess.PIPE, check=True).stdout
    position, blobs = 0, 0
    for line in objects:
        header_end = raw.index(b"\n", position)
        header = raw[position:header_end].split()
        size = int(header[2])
        start = header_end + 1
        content = raw[start:start + size]
        position = start + size + 1
        if header[1] == b"blob":
            blobs += 1
            scan("history:" + line, content)
    ignored = {}
    for name in (".env", "evidence/private/demo-login.json", "data/news.sqlite3", "frontend/node_modules", "frontend/.next", "dist/daily-ai-news-agent-submission.zip"):
        ignored[name] = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0
    report = {"executed_at": utcnow(), "scope": "Current public candidates plus every reachable blob in local/fetched Git history; exact local private credential comparison; common token/hash/cookie patterns",
              "candidate_files": len(names), "historical_blobs": blobs, "private_credential_files_compared": len(credential_files),
              "sensitive_content_findings": findings, "forbidden_paths": forbidden, "broken_relative_links": links, "ignored_private_paths": ignored,
              "fixtures": "Test-only passwords and example.com emails are labelled test fixtures; real demo passwords are private random values and compared exactly",
              "screenshots": "Final live screenshots hide account labels and delivery hints; historical anonymous demo screenshots reviewed separately",
              "remote_ref_at_scan": git("rev-parse", "origin/main").decode().strip(),
              "historical_evidence_hashes": {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names if n.startswith("evidence/") and "/" not in n[len("evidence/"):] and (ROOT / n).is_file()}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audit: {len(names)} candidates, {blobs} historical blobs; secret locations={len(findings)}, forbidden paths={len(forbidden)}, broken links={len(links)}")
    if findings or forbidden or links or not all(ignored.values()):
        print("Failed locations (values withheld):", findings + forbidden + [str(link) for link in links])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
