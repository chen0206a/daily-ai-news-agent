import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from ..agent.graph import run_agent, redact
from ..agent.model import DeepSeekModel
from ..db import utcnow
from ..schemas import Preferences
from ..tools.registry import ToolContext, ToolRegistry


def enqueue_run(db, user_id, prefs, model, trigger="manual", slot=None, now=None):
    now = now or datetime.now(timezone.utc)
    date = now.astimezone(ZoneInfo(prefs.timezone)).date().isoformat()
    existing = db.one("SELECT r.* FROM runs r JOIN digests d ON d.run_id=r.id WHERE d.user_id=? AND d.digest_date=?", (user_id, date))
    if existing:
        return existing
    run_id = uuid.uuid4().hex
    try:
        db.execute("INSERT INTO runs(id,user_id,status,trigger,slot,preferences,created_at,model) VALUES(?,?,?,?,?,?,?,?)",
                   (run_id, user_id, "queued", trigger, slot or f"manual:{run_id}", prefs.model_dump_json(), now.isoformat(), model))
    except sqlite3.IntegrityError:
        existing = db.one("SELECT * FROM runs WHERE user_id=? AND (slot=? OR status IN ('queued','running')) ORDER BY created_at DESC LIMIT 1", (user_id, slot or ""))
        if existing:
            return existing
        raise
    return db.one("SELECT * FROM runs WHERE id=?", (run_id,))


def schedule_due(db, settings, now=None):
    now = now or datetime.now(timezone.utc)
    scheduled = []
    for row in db.all("SELECT * FROM preferences"):
        prefs = Preferences.model_validate_json(row["data"])
        if not prefs.schedule_enabled:
            continue
        local = now.astimezone(ZoneInfo(prefs.timezone))
        if local.strftime("%H:%M") >= prefs.delivery_time:
            # One slot per local calendar date, survives service restarts; no multi-day catch-up burst.
            slot = f"schedule:{local.date().isoformat()}"
            scheduled.append(enqueue_run(db, row["user_id"], prefs, settings.deepseek_model, "schedule", slot, now))
    return scheduled


class Worker:
    def __init__(self, db, settings, news, delivery, model_factory=None):
        self.db, self.settings, self.news, self.delivery = db, settings, news, delivery
        self.model_factory = model_factory or (lambda: DeepSeekModel(settings))
        self.stopping = asyncio.Event()

    def recover(self):
        # Called only after the exclusive instance lock has been acquired.
        self.db.execute("UPDATE runs SET status='interrupted',error='Service restarted during run; start a new run',finished_at=? WHERE status='running'", (utcnow(),))
        self.db.execute("UPDATE deliveries SET status='uncertain',error='Service restarted during SMTP submission; inspect server log before retry' WHERE status='sending'")

    async def execute(self, run_id):
        if not self.db.execute("UPDATE runs SET status='running',started_at=? WHERE id=? AND status='queued'", (utcnow(), run_id)):
            return
        row = self.db.one("SELECT * FROM runs WHERE id=?", (run_id,))
        ctx = ToolContext(row["user_id"], run_id, Preferences.model_validate_json(row["preferences"]),
                          self.db, self.settings, self.news, self.delivery)
        model = None
        self.db.event(run_id, "lifecycle", {"status": "running", "model": self.settings.deepseek_model})
        try:
            model = self.model_factory()
            state = await run_agent(model, ToolRegistry(ctx))
            digest = self.db.one("SELECT id FROM digests WHERE run_id=?", (run_id,))
            queued = self.db.one("SELECT id FROM deliveries WHERE digest_id=?", (digest["id"],)) if digest else None
            channels = ctx.preferences.in_app_enabled or ctx.preferences.email_enabled
            status = "completed" if digest and (queued or not channels) else "incomplete"
            final = redact(state["messages"][-1].get("content") or "", self.settings.deepseek_api_key)
            self.db.execute("UPDATE runs SET status=?,final_text=?,finished_at=? WHERE id=?", (status, final, utcnow(), run_id))
            self.db.event(run_id, "lifecycle", {"status": status, "turns": state["turns"], "tool_calls": state["calls"]})
        except asyncio.CancelledError:
            self.db.execute("UPDATE runs SET status='interrupted',error='Worker stopped',finished_at=? WHERE id=?", (utcnow(), run_id))
            raise
        except Exception as exc:
            # Error strings from HTTP libraries may contain request details. Persist a safe type + controlled message.
            error = type(exc).__name__
            if isinstance(exc, ValueError) and "not configured" in str(exc):
                error = str(exc)
            self.db.execute("UPDATE runs SET status='failed',error=?,finished_at=? WHERE id=?", (error, utcnow(), run_id))
            self.db.event(run_id, "error", {"type": error})
        finally:
            if model and hasattr(model, "close"):
                await model.close()

    async def loop(self):
        while not self.stopping.is_set():
            try:
                if self.settings.scheduler_enabled:
                    schedule_due(self.db, self.settings)
                await asyncio.to_thread(self.delivery.deliver_pending)
                row = self.db.one("SELECT id FROM runs WHERE status='queued' ORDER BY created_at LIMIT 1")
                if row:
                    await self.execute(row["id"])
                    continue
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Worker tick failed")
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=3)
            except TimeoutError:
                pass


class InstanceLock:
    """OS lock, automatically released on crash. One API worker per SQLite data directory."""
    def __init__(self, path):
        self.file = open(path, "a+b")
        self.file.seek(0)
        if path.stat().st_size == 0:
            self.file.write(b"1")
            self.file.flush()
        self.file.seek(0)

    def acquire(self):
        import os
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("A worker already uses this DATA_DIR. Run uvicorn with --workers 1.")

    def close(self):
        self.file.close()
