import asyncio
import hashlib
import json
import sqlite3
import uuid
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .db import Database, utcnow
from .schemas import Credentials, Preferences
from .security import password_hasher, verify_password, create_session, session_user, auth_limit
from .services.news import NewsService, SOURCES
from .services.delivery import DeliveryService
from .services.worker import Worker, InstanceLock, enqueue_run


def create_app(settings=None):
    settings = settings or get_settings()
    db = Database(settings.db_path)
    delivery = DeliveryService(db, settings)
    worker = Worker(db, settings, NewsService(), delivery)

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        task, lock = None, None
        if settings.worker_enabled:
            lock = InstanceLock(settings.data_dir / "worker.lock")
            lock.acquire()
            worker.recover()
            task = asyncio.create_task(worker.loop())
        yield
        if task:
            worker.stopping.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if lock:
            lock.close()

    app = FastAPI(title="Daily AI News Agent", version="1.0.0", lifespan=lifespan)
    app.state.db, app.state.worker = db, worker
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type", "X-Requested-With", "Idempotency-Key"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            origin = request.headers.get("origin")
            if (origin and origin != settings.frontend_origin) or request.headers.get("x-requested-with") != "daily-ai-news":
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Request origin / CSRF header rejected"}, status_code=403)
            size = request.headers.get("content-length", "0")
            if not size.isdigit() or int(size) > 16000:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Request too large"}, status_code=413)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16000:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def user(request: Request):
        return session_user(db, request.cookies.get("news_session"))

    def cookie(response, user_id):
        token = create_session(db, user_id)
        response.set_cookie("news_session", token, httponly=True, secure=settings.cookie_secure,
                            samesite="lax", max_age=604800, path="/")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model_configured": bool(settings.deepseek_api_key),
                "smtp_configured": bool(settings.smtp_host and settings.smtp_from), "model": settings.deepseek_model}

    @app.get("/api/sources")
    def sources():
        return [{"id": key, "name": value["name"], "feed": value["feed"]} for key, value in SOURCES.items()]

    @app.post("/api/auth/register", status_code=201)
    def register(body: Credentials, request: Request, response: Response):
        auth_limit(db, f"register:{request.client.host}", 6)
        user_id, email = uuid.uuid4().hex, str(body.email).lower()
        try:
            with db.connect() as conn:
                conn.execute("INSERT INTO users VALUES(?,?,?,?)", (user_id, email, password_hasher.hash(body.password), utcnow()))
                conn.execute("INSERT INTO preferences VALUES(?,?,?)", (user_id, Preferences().model_dump_json(), utcnow()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Account already exists")
        cookie(response, user_id)
        return {"id": user_id, "email": email}

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        auth_limit(db, f"login:{request.client.host}")
        row = db.one("SELECT * FROM users WHERE email=?", (str(body.email).lower(),))
        valid = verify_password(row["password_hash"] if row else None, body.password)
        if not row or not valid:
            raise HTTPException(401, "Invalid email or password")
        cookie(response, row["id"])
        return {"id": row["id"], "email": row["email"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get("news_session", "")
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie("news_session", path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(current=Depends(user)):
        return current

    @app.get("/api/preferences", response_model=Preferences)
    def preferences(current=Depends(user)):
        return json.loads(db.one("SELECT data FROM preferences WHERE user_id=?", (current["id"],))["data"])

    @app.put("/api/preferences", response_model=Preferences)
    def update_preferences(body: Preferences, current=Depends(user)):
        db.execute("UPDATE preferences SET data=?,updated_at=? WHERE user_id=?", (body.model_dump_json(), utcnow(), current["id"]))
        return body

    @app.post("/api/runs", status_code=202)
    def start_run(request: Request, current=Depends(user)):
        if not settings.deepseek_api_key:
            raise HTTPException(503, "Configure DEEPSEEK_API_KEY before generating a digest")
        auth_limit(db, f"run:{current['id']}", 6)
        key = request.headers.get("idempotency-key")
        if key and (len(key) > 80 or not all(c.isalnum() or c in "-_" for c in key)):
            raise HTTPException(422, "Invalid idempotency key")
        prefs = Preferences.model_validate_json(db.one("SELECT data FROM preferences WHERE user_id=?", (current["id"],))["data"])
        return enqueue_run(db, current["id"], prefs, settings.deepseek_model, slot=f"request:{key}" if key else None)

    @app.get("/api/runs")
    def runs(limit: int = Query(30, ge=1, le=100), current=Depends(user)):
        return db.all("SELECT id,status,trigger,created_at,finished_at,error,model FROM runs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (current["id"], limit))

    def owned_run(run_id, current):
        row = db.one("SELECT * FROM runs WHERE id=? AND user_id=?", (run_id, current["id"]))
        if not row:
            raise HTTPException(404, "Run not found")
        return row

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, current=Depends(user)):
        return owned_run(run_id, current)

    @app.get("/api/runs/{run_id}/trace")
    def trace(run_id: str, after: int = Query(0, ge=0), current=Depends(user)):
        owned_run(run_id, current)
        rows = db.all("SELECT * FROM trace WHERE run_id=? AND id>? ORDER BY id LIMIT 200", (run_id, after))
        return [{**row, "data": json.loads(row["data"])} for row in rows]

    @app.get("/api/digests")
    def digests(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), current=Depends(user)):
        return db.all("SELECT id,run_id,digest_date,title,created_at FROM digests WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (current["id"], limit, offset))

    @app.get("/api/digests/{digest_id}")
    def digest_detail(digest_id: str, current=Depends(user)):
        row = db.one("SELECT * FROM digests WHERE id=? AND user_id=?", (digest_id, current["id"]))
        if not row:
            raise HTTPException(404, "Digest not found")
        return {**row, "items": json.loads(row["items"]), "deliveries": db.all("SELECT channel,status,error,sent_at FROM deliveries WHERE digest_id=? AND user_id=?", (digest_id, current["id"]))}

    @app.get("/api/notifications")
    def notifications(current=Depends(user)):
        return db.all("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (current["id"],))

    @app.post("/api/digests/{digest_id}/send")
    def send_saved_digest(digest_id: str, current=Depends(user)):
        digest = db.one("SELECT id FROM digests WHERE id=? AND user_id=?", (digest_id, current["id"]))
        if not digest:
            raise HTTPException(404, "Digest not found")
        auth_limit(db, f"send:{current['id']}", 6)
        prefs = Preferences.model_validate_json(db.one("SELECT data FROM preferences WHERE user_id=?", (current["id"],))["data"])
        delivery.enqueue(current["id"], digest_id, prefs)
        # Explicit user retry only for failures BEFORE SMTP submission / revoked channels.
        for channel, enabled in (("email", prefs.email_enabled), ("in_app", prefs.in_app_enabled)):
            if enabled:
                db.execute("UPDATE deliveries SET status='pending',error=NULL WHERE digest_id=? AND user_id=? AND channel=? AND status IN ('failed','cancelled')", (digest_id, current["id"], channel))
        return db.all("SELECT channel,status,error FROM deliveries WHERE digest_id=? AND user_id=?", (digest_id, current["id"]))

    @app.post("/api/notifications/{notification_id}/read")
    def mark_read(notification_id: str, current=Depends(user)):
        if not db.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=?", (utcnow(), notification_id, current["id"])):
            raise HTTPException(404, "Notification not found")
        return {"ok": True}

    return app


app = create_app()
