import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException
from .db import utcnow

password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = password_hasher.hash("dummy-password-only-for-timing")


def verify_password(encoded, password):
    try:
        return password_hasher.verify(encoded or DUMMY_HASH, password)
    except VerificationError:
        return False


def create_session(db, user_id):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, expires))
    return token


def session_user(db, token):
    if not token:
        raise HTTPException(401, "Please sign in")
    user = db.one("SELECT u.id,u.email FROM users u JOIN sessions s ON u.id=s.user_id "
                  "WHERE s.token_hash=? AND s.expires_at>?", (hashlib.sha256(token.encode()).hexdigest(), utcnow()))
    if not user:
        raise HTTPException(401, "Session expired")
    return user


def auth_limit(db, bucket, limit=12):
    now = time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM auth_attempts WHERE at<?", (now - 600,))
        n = conn.execute("SELECT count(*) FROM auth_attempts WHERE bucket=?", (bucket,)).fetchone()[0]
        if n >= limit:
            raise HTTPException(429, "Too many attempts; try again in 10 minutes")
        conn.execute("INSERT INTO auth_attempts VALUES(?,?)", (bucket, now))


class SecurityError(ValueError):
    pass


class Workspace:
    """Private data workspace; rejects links, reparse points, ADS and hidden files."""
    def __init__(self, data_dir: Path, user_id: str):
        if not re.fullmatch(r"[a-f0-9]{32}", user_id):
            raise SecurityError("Invalid workspace identity")
        self.root = (data_dir / "workspaces" / user_id).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or self._reparse(self.root):
            raise SecurityError("Workspace links are forbidden")

    @staticmethod
    def _reparse(path):
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400) if path.exists() else False

    def path(self, value: str, *, directory=False):
        if len(value) > 240 or "\x00" in value or "\\" in value or ":" in value:
            raise SecurityError("Invalid workspace path")
        rel = Path(value)
        if rel.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in rel.parts:
            raise SecurityError("Path must stay inside the workspace")
        if any(p.startswith(".") or re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)(\..*)?", p)
               or p.endswith((" ", ".")) for p in rel.parts):
            raise SecurityError("Reserved or hidden paths are forbidden")
        target = self.root / rel
        for candidate in [target, *target.parents]:
            if candidate == self.root.parent:
                break
            if candidate.is_symlink() or self._reparse(candidate):
                raise SecurityError("Symbolic links and reparse points are forbidden")
        if not target.resolve().is_relative_to(self.root.resolve()):
            raise SecurityError("Path escapes workspace")
        if not directory and target == self.root:
            raise SecurityError("File path required")
        if target.is_file():
            if target.stat().st_nlink > 1:
                raise SecurityError("Hard links are forbidden")
            if target.stat().st_size > 128_000:
                raise SecurityError("File exceeds read limit")
        return target

    def read(self, path):
        return self.path(path).read_text(encoding="utf-8")[:32000]

    def write(self, path, content):
        target = self.path(path)
        if target.suffix.lower() not in {".md", ".txt", ".json", ".csv"}:
            raise SecurityError("Only .md/.txt/.json/.csv files can be written")
        raw = content.encode("utf-8")
        if len(raw) > 128_000:
            raise SecurityError("File exceeds write limit")
        existing = list(self.root.rglob("*"))
        if len(existing) > 200 or sum(p.stat().st_size for p in existing if p.is_file()) + len(raw) > 2_000_000:
            raise SecurityError("Workspace quota exceeded")
        target.parent.mkdir(parents=True, exist_ok=True)
        # This service never exposes link creation or arbitrary executable writes.
        with target.open("w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        if os.name != "nt":
            target.chmod(0o600)
        return {"path": path, "bytes": len(raw)}
