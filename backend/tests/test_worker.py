from app.services.worker import Worker
from test_agent import ScriptedModel


async def test_worker_requires_persisted_outcome_not_llm_success_claim(setup):
    ctx, _ = setup
    ctx.db.execute("UPDATE runs SET status='queued' WHERE id=?", (ctx.run_id,))
    worker = Worker(ctx.db, ctx.settings, None, ctx.delivery, model_factory=lambda: ScriptedModel([
        {"role": "assistant", "content": "I generated and delivered everything (an intentionally false offline test claim)."}]))
    await worker.execute(ctx.run_id)
    assert ctx.db.one("SELECT status FROM runs WHERE id=?", (ctx.run_id,))["status"] == "incomplete"
    assert ctx.db.all("SELECT * FROM digests") == []


async def test_model_error_is_recorded_without_key(setup):
    ctx, _ = setup
    ctx.db.execute("UPDATE runs SET status='queued' WHERE id=?", (ctx.run_id,))

    class BrokenModel:
        async def complete(self, *args):
            raise RuntimeError(f"Network error with credential {ctx.settings.deepseek_api_key}")

    worker = Worker(ctx.db, ctx.settings, None, ctx.delivery, model_factory=BrokenModel)
    await worker.execute(ctx.run_id)
    row = ctx.db.one("SELECT status,error FROM runs WHERE id=?", (ctx.run_id,))
    assert row == {"status": "failed", "error": "RuntimeError"}
    assert ctx.settings.deepseek_api_key not in str(ctx.db.all("SELECT * FROM trace"))


def test_restart_marks_running_interrupted(setup):
    ctx, _ = setup
    Worker(ctx.db, ctx.settings, None, ctx.delivery).recover()
    assert ctx.db.one("SELECT status FROM runs WHERE id=?", (ctx.run_id,))["status"] == "interrupted"
