import asyncio
import uuid
import pytest
from app.security import SecurityError, Workspace
from app.services.news import canonical_url, public_ips
from app.tools.registry import SPECS


async def test_real_workspace_tools(setup):
    ctx, tools = setup
    assert len(SPECS) == 10
    await tools.call("write_file", {"path": "notes/day.md", "content": "AI news\nverified line"})
    assert (await tools.call("list_dir", {"path": "notes"}))["entries"][0]["name"] == "day.md"
    assert "AI news" in (await tools.call("read_file", {"path": "notes/day.md"}))["content"]
    assert (await tools.call("search_content", {"query": "verified"}))["matches"][0]["line"] == 2
    assert "AI news" in (await tools.call("bash", {"command": "cat notes/day.md"}))["stdout"]
    assert (await tools.call("bash", {"command": "wc notes/day.md"}))["exit_code"] == 0
    assert (await tools.call("get_preferences", {}))["language"] == "zh"


@pytest.mark.parametrize("path", ["../.env", "/etc/passwd", "C:/Windows/win.ini", "a\\..\\b", ".env", "x:stream", "CON.txt", "a/../../b"])
async def test_path_attacks(setup, path):
    _, tools = setup
    with pytest.raises(SecurityError):
        await tools.call("read_file", {"path": path})


@pytest.mark.parametrize("command", ["env", "python -c print(1)", "cat ../.env", "ls; whoami", "cat $(env)", "ls | cat", "ls -R", "curl https://example.com", "pwd > x", "bash"])
async def test_command_attacks(setup, command):
    with pytest.raises(SecurityError):
        await setup[1].call("bash", {"command": command})


async def test_tenant_isolation_and_quota(setup):
    ctx, tools = setup
    other = Workspace(ctx.settings.data_dir, uuid.uuid4().hex)
    other.write("secret.txt", "another user's secret")
    assert (await tools.call("search_content", {"query": "secret"}))["matches"] == []
    with pytest.raises(SecurityError):
        await tools.call("write_file", {"path": "run.py", "content": "print(1)"})
    with pytest.raises(SecurityError):
        ctx.workspace.write("big.txt", "x" * 128001)


def test_hardlink_cannot_read_outside_file(setup, tmp_path):
    import os
    ctx, _ = setup
    outside = tmp_path / "outside.txt"
    outside.write_text("private content")
    link = ctx.workspace.root / "link.txt"
    os.link(outside, link)
    with pytest.raises(SecurityError, match="Hard links"):
        ctx.workspace.read("link.txt")


@pytest.mark.parametrize("url", ["http://openai.com/news/", "https://127.0.0.1", "https://openai.com.evil.com", "https://user@openai.com/", "https://openai.com:8443/"])
def test_ssrf_urls(url):
    with pytest.raises((SecurityError, ValueError)):
        canonical_url(url)


def test_dns_private_rejected(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(SecurityError):
        public_ips("openai.com")


async def test_discovery_and_identity_are_not_model_controlled(setup):
    from pydantic import ValidationError
    with pytest.raises(SecurityError):
        await setup[1].call("fetch_article", {"url": "https://openai.com/news/"})
    with pytest.raises(ValidationError):
        await setup[1].call("get_preferences", {"user_id": "another-user"})
    with pytest.raises(SecurityError):
        await setup[1].call("send_digest", {"digest_id": "another-users-digest"})


async def test_digest_evidence_and_idempotency(setup):
    from app.db import utcnow
    ctx, tools = setup
    content = "This is a real-looking fixture used only in offline tests; it is not live news."
    ctx.db.execute("INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?)", (
        "fixture", ctx.user_id, ctx.run_id, "https://openai.com/news/test", "Test fixture", "openai", utcnow(), utcnow(), content, "test-hash"))
    args = {"title": "Offline test digest", "items": [{"article_id": "fixture", "summary": "An explicitly labelled test fixture summary.", "evidence_quote": content}]}
    result = await tools.call("save_digest", args)
    assert result["created"]
    assert not (await tools.call("save_digest", args))["created"]
    await asyncio.gather(*(tools.call("send_digest", {"digest_id": result["digest_id"]}) for _ in range(4)))
    ctx.delivery.deliver_pending()
    ctx.delivery.deliver_pending()
    assert len(ctx.db.all("SELECT * FROM notifications")) == 1
    assert len(ctx.db.all("SELECT * FROM deliveries")) == 1
    args["items"][0]["evidence_quote"] = "Fabricated quote that does not exist in the article"
    with pytest.raises(ValueError, match="exact excerpt"):
        await tools.call("save_digest", args)


async def test_expand_same_run_draft_before_delivery_then_lock(setup):
    from app.db import utcnow
    ctx, tools = setup
    content = "An explicit offline fixture quote for regression testing."
    for article_id in ("one", "two"):
        ctx.db.execute("INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?)", (
            article_id, ctx.user_id, ctx.run_id, f"https://openai.com/index/{article_id}", "Fixture", "openai", utcnow(), utcnow(), content, "fixture-hash"))
    item = {"article_id": "one", "summary": "Explicit offline fixture summary for testing only.", "evidence_quote": content}
    first = await tools.call("save_digest", {"title": "Regression test", "items": [item]})
    expanded = await tools.call("save_digest", {"title": "Regression test", "items": [item, {**item, "article_id": "two"}]})
    assert expanded["digest_id"] == first["digest_id"]
    assert expanded["updated"] and expanded["items"] == 2
    assert not expanded["created"]
    await tools.call("send_digest", {"digest_id": first["digest_id"]})
    with pytest.raises(SecurityError, match="immutable"):
        await tools.call("save_digest", {"title": "Regression test", "items": [item]})
    unchanged = await tools.call("save_digest", {"title": "Regression test", "items": [item, {**item, "article_id": "two"}]})
    assert unchanged["items"] == 2 and not unchanged["updated"]
