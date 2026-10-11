"""User-owned feed catalog; authentication and delivery remain server-bound."""
import sqlite3
import uuid
from fastapi import HTTPException
from ..db import utcnow
from ..schemas import Preferences
from ..security import auth_limit
from .news import SOURCES, normalize_public_url


class Subscriptions:
    def __init__(self, db, news):
        self.db, self.news = db, news

    def list(self, uid):
        checks = {r["id"]: r for r in self.db.all("SELECT * FROM preset_checks")}
        result = []
        for key, source in SOURCES.items():
            check = checks.get(key, {})
            result.append({"id": key, "name": source["name"], "feed": source["feed"], "custom": False,
                           "enabled": not source.get("requires_check") or bool(check.get("ok")),
                           "checked_at": check.get("checked_at"), "ok": check.get("ok"), "error": check.get("error")})
        return result + [{**r, "custom": True} for r in self.db.all(
            "SELECT id,name,feed,enabled,checked_at,ok,error FROM news_sources WHERE user_id=? ORDER BY rowid", (uid,))]

    def definitions(self, uid):
        return {r["id"]: {**r, "hosts": SOURCES[r["id"]]["hosts"] if not r["custom"] else set()}
                for r in self.list(uid) if r["enabled"]}

    def validate_selection(self, uid, ids):
        if any(sid not in self.definitions(uid) for sid in ids):
            raise HTTPException(422, "Source is disabled, unverified or not owned by this account")

    def status(self, uid, sid, ok, error):
        if sid in SOURCES:
            self.db.execute("INSERT INTO preset_checks VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET checked_at=excluded.checked_at,ok=excluded.ok,error=excluded.error",
                            (sid, utcnow(), int(ok), error))
        else:
            self.db.execute("UPDATE news_sources SET checked_at=?,ok=?,error=? WHERE id=? AND user_id=?", (utcnow(), int(ok), error, sid, uid))

    def check(self, uid, sid):
        auth_limit(self.db, f"feed-check:{uid}", 12)
        source = next((r for r in self.list(uid) if r["id"] == sid), None)
        if not source:
            raise HTTPException(404, "Source not found")
        if not source["custom"]:
            source = SOURCES[sid]
        try:
            entries, _ = self.news.feed(source)
            self.status(uid, sid, True, None)
            count = len(entries)
        except ValueError as exc:
            self.status(uid, sid, False, str(exc))
            count = 0
        result = next(r for r in self.list(uid) if r["id"] == sid)
        return {**result, "valid_entries": count}

    def add(self, uid, body):
        try:
            url = normalize_public_url(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if self.db.one("SELECT id FROM news_sources WHERE user_id=? AND feed=?", (uid, url)):
            raise HTTPException(409, "This RSS URL has already been added")
        auth_limit(self.db, f"feed-check:{uid}", 12)
        if self.db.one("SELECT count(*) AS n FROM news_sources WHERE user_id=?", (uid,))["n"] >= 8:
            raise HTTPException(422, "At most 8 custom sources per account")
        ok, error = True, None
        try:
            self.news.feed({"feed": url, "custom": True})
        except ValueError as exc:
            ok, error = False, str(exc)
        sid = "custom_" + uuid.uuid4().hex
        try:
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT count(*) FROM news_sources WHERE user_id=?", (uid,)).fetchone()[0] >= 8:
                    raise HTTPException(422, "At most 8 custom sources per account")
                conn.execute("INSERT INTO news_sources VALUES(?,?,?,?,0,?,?,?)", (sid, uid, body.name, url, utcnow(), int(ok), error))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "This RSS URL has already been added")
        return next(r for r in self.list(uid) if r["id"] == sid)

    def change(self, uid, sid, enabled=None, delete=False):
        if not self.db.one("SELECT id FROM news_sources WHERE id=? AND user_id=?", (sid, uid)):
            raise HTTPException(404, "Source not found")
        if enabled:
            checked = self.check(uid, sid)
            if not checked["ok"]:
                raise HTTPException(422, "Cannot enable RSS: " + (checked["error"] or "validation failed"))
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT id FROM news_sources WHERE id=? AND user_id=?", (sid, uid)).fetchone():
                raise HTTPException(404, "Source not found")
            prefs = Preferences.model_validate_json(conn.execute("SELECT data FROM preferences WHERE user_id=?", (uid,)).fetchone()[0])
            selected = [v for v in prefs.sources if v != sid]
            if enabled and not delete:
                selected.append(sid)
            if not selected or len(selected) > 12:
                raise HTTPException(422, "Keep between 1 and 12 subscribed sources")
            prefs.sources = selected
            if delete:
                conn.execute("DELETE FROM news_sources WHERE id=? AND user_id=?", (sid, uid))
            else:
                conn.execute("UPDATE news_sources SET enabled=? WHERE id=? AND user_id=?", (int(enabled), sid, uid))
            conn.execute("UPDATE preferences SET data=?,updated_at=? WHERE user_id=?", (prefs.model_dump_json(), utcnow(), uid))
        return {"ok": True, "sources": selected}

    def search(self, uid, prefs, query="", budget_seconds=35):
        return self.news.search(query, prefs.sources, prefs.lookback_days, definitions=self.definitions(uid),
                                topics=prefs.topics, watch_objects=[o.model_dump() for o in prefs.watch_objects],
                                budget_seconds=budget_seconds,
                                status_callback=lambda sid, ok, err: self.status(uid, sid, ok, err))
