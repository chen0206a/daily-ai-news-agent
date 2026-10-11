"""Archive exact committed HEAD bytes; refuse secrets and attach a verifiable manifest."""
import hashlib
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=ROOT).returncode:
        raise SystemExit("Commit all tracked changes before packaging; working files are never substituted for HEAD.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    archive_bytes = subprocess.check_output(["git", "archive", "--format=zip", "--prefix=daily-ai-news-agent/", "HEAD"], cwd=ROOT)
    from app.config import Settings
    settings = Settings()
    secret_values = [v.encode() for v in (settings.deepseek_api_key, settings.smtp_password) if len(v) >= 8]
    for login_file in (ROOT / "evidence/private").rglob("*.json"):
        try:
            value = json.loads(login_file.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                secret_values.extend(v.encode() for k, v in value.items() if k in {"password", "token", "api_key"} and isinstance(v, str) and len(v) >= 8)
        except (ValueError, OSError):
            raise SystemExit("Unreadable private credential metadata; cannot complete package safety scan")
    entries = {}
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            name = entry.filename.removeprefix("daily-ai-news-agent/")
            parts = Path(name).parts
            if name != ".env.example" and (name.startswith(".env") or name.startswith(("data/", "evidence/private/", ".venv/", "dist/")) or any(p in {"node_modules", ".next", "__pycache__", "test-results", "playwright-report"} for p in parts) or Path(name).suffix in {".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key"}):
                raise SystemExit(f"Refusing private path: {name}")
            content = archive.read(entry)
            if any(secret in content for secret in secret_values) or re.search(rb"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", content):
                raise SystemExit(f"Credential detected; refusing to package: {name}")
            entries[name] = hashlib.sha256(content).hexdigest()
    output = ROOT / "dist" / "daily-ai-news-agent-submission.zip"
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(archive_bytes)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    output.with_suffix(".zip.manifest.json").write_text(json.dumps({"commit": commit, "tree": tree, "branch": branch,
        "archive_sha256": digest, "file_count": len(entries), "files": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Packaged exact commit {commit}: {len(entries)} files; {output.stat().st_size} bytes. Credential scan passed.")


if __name__ == "__main__":
    main()
