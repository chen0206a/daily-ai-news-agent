"""Package only Git-indexed files; refuse credentials and private runtime data."""
import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    names = [n for n in names if n]
    if not names:
        raise SystemExit("Stage the source with git add . before packaging.")
    from app.config import Settings
    settings = Settings()
    secret_values = [v.encode() for v in (settings.deepseek_api_key, settings.smtp_password) if len(v) >= 8]
    for name in names:
        if name == ".env" or name.startswith(("data/", "evidence/private/", ".venv/", "dist/")):
            raise SystemExit(f"Refusing private path: {name}")
        content = (ROOT / name).read_bytes()
        if any(secret in content for secret in secret_values):
            raise SystemExit(f"Credential detected; refusing to package: {name}")
    output = ROOT / "dist" / "daily-ai-news-agent-submission.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(ROOT / name, f"daily-ai-news-agent/{name}")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"Packaged {len(names)} files; {output.stat().st_size} bytes. Credential scan passed.")


if __name__ == "__main__":
    main()
