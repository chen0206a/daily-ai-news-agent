from datetime import datetime, timezone
from app.services.worker import schedule_due, InstanceLock
from app.services.delivery import DeliveryService


def test_schedule_timezone_dedupe_and_restart(setup):
    ctx, _ = setup
    ctx.db.execute("UPDATE runs SET status='completed'")
    ctx.preferences.schedule_enabled = True
    ctx.db.execute("UPDATE preferences SET data=? WHERE user_id=?", (ctx.preferences.model_dump_json(), ctx.user_id))
    before = datetime(2026, 10, 7, 23, 59, tzinfo=timezone.utc)
    assert schedule_due(ctx.db, ctx.settings, before) == []
    due = datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc)
    first = schedule_due(ctx.db, ctx.settings, due)
    second = schedule_due(ctx.db, ctx.settings, due)
    assert first[0]["id"] == second[0]["id"]
    assert first[0]["slot"] == "schedule:2026-10-08"
    ctx.db.execute("UPDATE runs SET status='completed'")
    assert schedule_due(ctx.db, ctx.settings, due)[0]["id"] == first[0]["id"]


def seed_delivery(ctx):
    ctx.db.execute("INSERT INTO digests VALUES(?,?,?,?,?,?,?,?)", ("digest", ctx.user_id, ctx.run_id, "2026-10-08", "Offline email test", "Fixture body", "[]", "2026-10-08"))
    prefs = ctx.preferences.model_copy(update={"email_enabled": True, "in_app_enabled": False})
    ctx.db.execute("UPDATE preferences SET data=? WHERE user_id=?", (prefs.model_dump_json(), ctx.user_id))
    ctx.delivery.enqueue(ctx.user_id, "digest", prefs)


def test_smtp_not_configured_is_failure_not_fake_success(setup):
    ctx, _ = setup
    ctx.settings.smtp_host = ""
    seed_delivery(ctx)
    ctx.delivery.deliver_pending()
    assert ctx.db.one("SELECT status FROM deliveries")["status"] == "failed"


def test_smtp_uncertain_is_never_automatically_resent(setup):
    ctx, _ = setup
    ctx.settings.smtp_host, ctx.settings.smtp_from = "localhost", "test@example.com"
    ctx.settings.smtp_starttls = False
    seed_delivery(ctx)
    sent = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass
        def ehlo(self):
            pass
        def send_message(self, message):
            sent.append(message)
            raise TimeoutError("Simulated lost acknowledgement after submission")
        def quit(self):
            pass

    service = DeliveryService(ctx.db, ctx.settings, FakeSMTP)
    service.deliver_pending()
    service.deliver_pending()
    assert len(sent) == 1
    assert ctx.db.one("SELECT status FROM deliveries")["status"] == "uncertain"


def test_instance_lock_prevents_two_workers(tmp_path):
    import pytest
    first = InstanceLock(tmp_path / "worker.lock")
    first.acquire()
    second = InstanceLock(tmp_path / "worker.lock")
    with pytest.raises(RuntimeError):
        second.acquire()
    first.close()


def test_pending_channel_revocation(setup):
    ctx, _ = setup
    seed_delivery(ctx)
    ctx.db.execute("UPDATE preferences SET data=? WHERE user_id=?", (ctx.preferences.model_dump_json(), ctx.user_id))
    ctx.delivery.deliver_pending()
    assert ctx.db.one("SELECT status FROM deliveries")["status"] == "cancelled"
