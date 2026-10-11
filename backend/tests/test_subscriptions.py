"""Offline fixtures validate contracts; live RSS evidence is recorded separately."""
import json
import time
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.config import Settings
from app.db import utcnow
from app.schemas import WatchObject
from app.security import SecurityError
from app.services.news import NewsService, SafeHTTP, normalize_public_url, bounded_dns
from test_agent import ScriptedModel, call
from app.agent.graph import run_agent

HEADERS = {"X-Requested-With": "daily-ai-news", "Origin": "http://localhost:3000"}


def rss(names=("Qwen 3 VL update", "LangGraph news", "Unrelated fixture")):
    items = ''.join(f'<item><title>{name}</title><link>https://example.com/news/{i}</link><pubDate>{utcnow()}</pubDate></item>' for i, name in enumerate(names))
    return f'<rss version="2.0"><channel><title>Offline test only</title>{items}</channel></rss>'.encode()


class FixtureHTTP:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else rss()
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "broken" in url:
            raise ValueError("News source returned HTTP 404")
        return self.payload, url


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, worker_enabled=False, deepseek_api_key=""))
    app.state.subscriptions.news = NewsService(FixtureHTTP())
    with TestClient(app) as c:
        c.post("/api/auth/register", headers=HEADERS, json={"email": "one@example.com", "password": "Test-password-123"})
        yield c, app


def add(client, url="https://example.com/feed.xml"):
    return client.post("/api/sources", headers=HEADERS, json={"name": "Offline fixture", "url": url})


def test_custom_feed_normalization_duplicate_and_enable_delete(client):
    c, app = client
    response = add(c, "https://EXAMPLE.com:443/feed.xml#fragment")
    assert response.status_code == 201
    source = response.json()
    assert source["feed"] == "https://example.com/feed.xml" and source["ok"] and not source["enabled"]
    assert source["checked_at"]
    assert add(c).status_code == 409
    sid = source["id"]
    assert c.put(f"/api/sources/{sid}", headers=HEADERS, json={"enabled": True}).status_code == 200
    assert sid in c.get("/api/preferences").json()["sources"]
    assert c.put(f"/api/sources/{sid}", headers=HEADERS, json={"enabled": False}).status_code == 200
    assert sid not in c.get("/api/preferences").json()["sources"]
    assert c.delete(f"/api/sources/{sid}", headers=HEADERS).status_code == 200
    assert not app.state.db.one("SELECT id FROM news_sources")


def test_failed_feed_keeps_reason_and_cannot_enable(client):
    c, _ = client
    source = add(c, "https://example.com/broken.xml").json()
    assert not source["ok"] and "404" in source["error"]
    assert c.put(f"/api/sources/{source['id']}", headers=HEADERS, json={"enabled": True}).status_code == 422


def test_sources_objects_isolated_and_cannot_select_unverified(client):
    c, _ = client
    sid = add(c).json()["id"]
    prefs = c.get("/api/preferences").json()
    prefs["watch_objects"] = [{"type": "project", "name": "LangGraph", "aliases": ["lang graph"]}]
    assert c.put("/api/preferences", headers=HEADERS, json=prefs).status_code == 200
    c.post("/api/auth/logout", headers=HEADERS)
    assert c.get("/api/sources").status_code == 401
    c.post("/api/auth/register", headers=HEADERS, json={"email": "two@example.com", "password": "Test-password-123"})
    assert not any(s["id"] == sid for s in c.get("/api/sources").json())
    assert c.get("/api/preferences").json()["watch_objects"] == []
    for method, path, body in [("post", f"/api/sources/{sid}/check", None), ("delete", f"/api/sources/{sid}", None), ("put", f"/api/sources/{sid}", {"enabled": True})]:
        assert getattr(c, method)(path, headers=HEADERS, **({"json": body} if body else {})).status_code == 404
    prefs["sources"] = [sid]
    assert c.put("/api/preferences", headers=HEADERS, json=prefs).status_code == 422
    prefs["sources"] = ["anthropic"]
    assert c.put("/api/preferences", headers=HEADERS, json=prefs).status_code == 422


def test_preview_saved_preferences_aliases_limit_and_no_delivery(client):
    c, app = client
    service = app.state.subscriptions.news
    service.http.payload = rss(tuple(f"Qwen 3 VL update {i}" for i in range(8)))
    sid = add(c).json()["id"]
    c.put(f"/api/sources/{sid}", headers=HEADERS, json={"enabled": True})
    prefs = c.get("/api/preferences").json()
    prefs.update(sources=[sid], topics=["nonmatching-topic"])
    c.put("/api/preferences", headers=HEADERS, json=prefs)
    assert c.post("/api/search-preview", headers=HEADERS).json()["candidates"] == []
    prefs["watch_objects"] = [{"type": "model", "name": "Qwen3-VL", "aliases": ["Qwen 3 VL"]}, {"type": "company", "name": "DeepSeek", "aliases": []}]
    c.put("/api/preferences", headers=HEADERS, json=prefs)
    preview = c.post("/api/search-preview", headers=HEADERS).json()
    assert len(preview["candidates"]) == 5
    assert all(v["matched_objects"] == ["Qwen3-VL"] for v in preview["candidates"])
    assert preview["unmatched_objects"] == ["DeepSeek"]
    assert preview["saved_preferences"]["watch_objects"] == prefs["watch_objects"]
    for table in ("runs", "trace", "articles", "digests", "deliveries", "notifications"):
        assert app.state.db.one(f"SELECT count(*) AS n FROM {table}")["n"] == 0


def test_partial_failure_budget_and_cache():
    http = FixtureHTTP()
    news = NewsService(http)
    definitions = {"a": {"name": "A", "feed": "https://example.com/feed", "custom": True},
                   "b": {"name": "B", "feed": "https://example.com/broken", "custom": True}}
    result = news.search("LangGraph", ["a", "b"], 3, definitions=definitions)
    assert len(result["candidates"]) == 1 and "404" in result["source_errors"][0]["error"]
    news.search("LangGraph", ["a", "b"], 3, definitions=definitions)
    assert len(http.calls) == 2  # failure AND success get the one-minute network cooldown
    result = news.search("LangGraph", ["a", "b"], 3, definitions=definitions, budget_seconds=0)
    assert not result["candidates"] and len(result["source_errors"]) == 2
    assert all("budget" in e["error"] for e in result["source_errors"])


@pytest.mark.parametrize("payload", [b"not XML", b"<rss><channel/></rss>", b'<rss><channel><item><title>Undated</title><link>https://example.com/x</link></item></channel></rss>'])
def test_invalid_feed_rejected(payload):
    with pytest.raises(ValueError):
        NewsService(FixtureHTTP(payload)).feed({"feed": "https://example.com/rss", "custom": True})


@pytest.mark.parametrize("url", ["http://example.com/feed", "file:///etc/passwd", "https://127.0.0.1/rss", "https://[::1]/", "https://10.0.0.1/", "https://169.254.169.254/latest/meta-data", "https://user:pass@example.com/", "https://example.com:8443/", "https://metadata.google.internal/", "https://localhost./", "https://168.63.129.16/", "https://[::ffff:127.0.0.1]/", "https://[64:ff9b::a9fe:a9fe]/"])
def test_custom_url_ssrf_syntax(url):
    with pytest.raises(SecurityError):
        normalize_public_url(url)


def test_ssrf_public_host_resolves_private_mixed_and_dns_timeout(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2,1,6,"",("8.8.8.8",443)), (2,1,6,"",("10.0.0.1",443))])
    with pytest.raises(SecurityError):
        SafeHTTP().get("https://example.com/rss", public=True)
    monkeypatch.setattr("app.services.news.public_ips", lambda _: time.sleep(.1))
    start = time.monotonic()
    with pytest.raises(ValueError, match="DNS resolution timeout"):
        bounded_dns("example.com", .01)
    assert time.monotonic() - start < .08


class FakeResponse:
    def __init__(self, status=200, headers=None, payload=b"<rss/>"):
        self.status, self.headers, self.payload = status, headers or {"Content-Type": "application/xml"}, payload
        self.connection = None
    def read1(self, size, **kwargs):
        result, self.payload = self.payload[:size], self.payload[size:]
        return result
    def close(self): pass


def fake_network(monkeypatch, response):
    monkeypatch.setattr("app.services.news.bounded_dns", lambda *a: ["8.8.8.8"])
    pool = SimpleNamespace(urlopen=lambda *a, **k: response, close=lambda: None)
    monkeypatch.setattr("urllib3.HTTPSConnectionPool", lambda *a, **k: pool)


@pytest.mark.parametrize("response,reason", [(FakeResponse(302, {"Location": "https://169.254.169.254/"}), "public HTTPS"), (FakeResponse(headers={"Content-Type": "text/xml", "Content-Encoding": "gzip"}), "Compressed"), (FakeResponse(payload=b"x" * 11), "size limit"), (FakeResponse(302, {"Location": "https://example.com/loop"}), "redirects")])
def test_redirect_and_response_bounds(monkeypatch, response, reason):
    fake_network(monkeypatch, response)
    with pytest.raises(ValueError, match=reason):
        SafeHTTP().get("https://example.com/rss", public=True, max_bytes=10)


def test_slow_response_cannot_extend_total_deadline(monkeypatch):
    response = FakeResponse()
    response.read1 = lambda *a, **k: (time.sleep(.02), b"x")[1]
    fake_network(monkeypatch, response)
    with pytest.raises(ValueError, match="total timeout"):
        SafeHTTP().get("https://example.com/rss", public=True, timeout=.01)


def test_tls_connection_pins_ip_preserves_hostname_and_disables_redirects(monkeypatch):
    options = {}
    def pool(address, **kwargs):
        options.update(address=address, **kwargs)
        def request(*a, **k):
            options.update(request=k)
            return FakeResponse()
        return SimpleNamespace(urlopen=request, close=lambda: None)
    monkeypatch.setattr("app.services.news.bounded_dns", lambda *a: ["8.8.8.8"])
    monkeypatch.setattr("urllib3.HTTPSConnectionPool", pool)
    SafeHTTP().get("https://example.com/rss", public=True)
    assert options["address"] == "8.8.8.8"
    assert options["server_hostname"] == options["assert_hostname"] == "example.com"
    assert options["cert_reqs"] == "CERT_REQUIRED" and options["request"]["redirect"] is False


def test_custom_check_and_preview_rate_limit(client):
    c, _ = client
    sid = add(c).json()["id"]
    for _ in range(11):
        assert c.post(f"/api/sources/{sid}/check", headers=HEADERS).status_code == 200
    assert c.post(f"/api/sources/{sid}/check", headers=HEADERS).status_code == 429
    for _ in range(6):
        assert c.post("/api/search-preview", headers=HEADERS).status_code == 200
    assert c.post("/api/search-preview", headers=HEADERS).status_code == 429


async def test_watch_objects_reach_agent_state_and_original_tool_loop(setup):
    ctx, registry = setup
    ctx.preferences.watch_objects = [WatchObject(type="project", name="vLLM", aliases=["v llm"])]
    model = ScriptedModel([{"role": "assistant", "tool_calls": [call("get_preferences")]}, {"role": "assistant", "content": "No relevant updates (offline fixture)."}])
    result = await run_agent(model, registry)
    assert result["preferences"]["watch_objects"][0]["name"] == "vLLM"
    assert "vLLM" in model.histories[0][-1]["content"]
    assert json.loads(model.histories[1][-1]["content"])["watch_objects"][0]["aliases"] == ["v llm"]


async def test_custom_discovery_fetch_and_revocation(setup):
    ctx, registry = setup
    sid = "custom_" + "a" * 32
    ctx.db.execute("INSERT INTO news_sources VALUES(?,?,?,?,1,?,1,NULL)", (sid, ctx.user_id, "Offline fixture", "https://example.com/rss", utcnow()))
    ctx.preferences.sources = [sid]
    ctx.preferences.topics = ["nonmatching"]
    ctx.preferences.watch_objects = [WatchObject(type="project", name="LangGraph")]
    http = FixtureHTTP()
    ctx.news = NewsService(http)
    result = await registry.call("search_news", {"query": "nonmatching"})
    assert result["candidates"][0]["matched_objects"] == ["LangGraph"]
    url = result["candidates"][0]["url"]
    http.payload = b"<article>" + b"Clearly marked offline fixture article content. " * 10 + b"</article>"
    article = await registry.call("fetch_article", {"url": url})
    assert article["article_id"] and len(ctx.db.all("SELECT * FROM articles")) == 1
    ctx.db.execute("UPDATE news_sources SET enabled=0 WHERE id=?", (sid,))
    with pytest.raises(SecurityError, match="revoked"):
        await registry.call("fetch_article", {"url": url})
