import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
 user_id TEXT PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
 trigger TEXT NOT NULL, slot TEXT NOT NULL, preferences TEXT NOT NULL, created_at TEXT NOT NULL,
 started_at TEXT, finished_at TEXT, error TEXT, final_text TEXT, model TEXT NOT NULL,
 UNIQUE(user_id, slot)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(user_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS trace (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
 kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), run_id TEXT NOT NULL REFERENCES runs(id),
 url TEXT NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL, published_at TEXT,
 fetched_at TEXT NOT NULL, content TEXT NOT NULL, sha256 TEXT NOT NULL,
 UNIQUE(run_id,url)
);
CREATE TABLE IF NOT EXISTS digests (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), run_id TEXT NOT NULL REFERENCES runs(id),
 digest_date TEXT NOT NULL, title TEXT NOT NULL, markdown TEXT NOT NULL, items TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(user_id,digest_date)
);
CREATE TABLE IF NOT EXISTS deliveries (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), digest_id TEXT NOT NULL REFERENCES digests(id),
 channel TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, sent_at TEXT,
 UNIQUE(digest_id,channel)
);
CREATE TABLE IF NOT EXISTS notifications (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), digest_id TEXT NOT NULL REFERENCES digests(id),
 title TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT, UNIQUE(user_id,digest_id)
);
CREATE TABLE IF NOT EXISTS auth_attempts (
 bucket TEXT NOT NULL, at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_attempts_bucket ON auth_attempts(bucket,at);
PRAGMA user_version=1;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def one(self, sql, args=()):
        with self.connect() as conn:
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql, args=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.connect() as conn:
            return conn.execute(sql, args).rowcount

    def event(self, run_id, kind, data):
        self.execute("INSERT INTO trace(run_id,kind,data,created_at) VALUES(?,?,?,?)",
                     (run_id, kind, dumps(data), utcnow()))
