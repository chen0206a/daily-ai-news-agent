import uuid
from fastapi.testclient import TestClient
from app.api import create_app
from app.config import Settings

HEADERS = {"X-Requested-With": "daily-ai-news", "Origin": "http://localhost:3000"}


def test_auth_csrf_preferences_and_tenant_authorization(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, worker_enabled=False))
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        body = {"email": "alice@example.com", "password": "Strong-test-password"}
        assert client.post("/api/auth/register", json=body).status_code == 403
        response = client.post("/api/auth/register", json=body, headers=HEADERS)
        assert response.status_code == 201
        assert "HttpOnly" in response.headers["set-cookie"]
        alice = response.json()["id"]
        prefs = client.get("/api/preferences").json()
        prefs["timezone"] = "Not/AZone"
        assert client.put("/api/preferences", json=prefs, headers=HEADERS).status_code == 422
        prefs["timezone"] = "Asia/Shanghai"
        prefs["topics"] = ["RAG", "AI agents"]
        assert client.put("/api/preferences", json=prefs, headers=HEADERS).status_code == 200
        assert client.get("/api/preferences").json()["topics"] == prefs["topics"]
        client.post("/api/auth/logout", headers=HEADERS)
        assert client.get("/api/me").status_code == 401
        assert client.post("/api/auth/login", headers=HEADERS, json={**body, "password": "wrong-password"}).status_code == 401
        assert client.post("/api/auth/login", headers=HEADERS, json=body).status_code == 200
        # A second principal cannot read or mark Alice's resources, even knowing their IDs.
        run_id = uuid.uuid4().hex
        app.state.db.execute("INSERT INTO runs(id,user_id,status,trigger,slot,preferences,created_at,model) VALUES(?,?,?,?,?,?,?,?)",
                             (run_id, alice, "completed", "test", "x", "{}", "2026-10-08", "test"))
        client.post("/api/auth/logout", headers=HEADERS)
        client.post("/api/auth/register", headers=HEADERS, json={**body, "email": "bob@example.com"})
        assert client.get(f"/api/runs/{run_id}/trace").status_code == 404
        assert client.get(f"/api/runs/{run_id}").status_code == 404
        assert client.get("/api/runs").json() == []


def test_idempotent_api_run_and_missing_model(tmp_path):
    settings = Settings(data_dir=tmp_path, worker_enabled=False, deepseek_api_key="")
    with TestClient(create_app(settings)) as client:
        client.post("/api/auth/register", headers=HEADERS, json={"email": "demo@example.com", "password": "Strong-password"})
        assert client.post("/api/runs", headers=HEADERS).status_code == 503
        settings.deepseek_api_key = "test-only"
        first = client.post("/api/runs", headers={**HEADERS, "Idempotency-Key": "abc"})
        assert first.status_code == 202
        second = client.post("/api/runs", headers={**HEADERS, "Idempotency-Key": "abc"})
        assert first.json()["id"] == second.json()["id"]
