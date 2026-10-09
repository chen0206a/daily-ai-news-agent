import json
import pytest
from app.agent.graph import run_agent, BudgetExceeded


def call(name, args=None):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}


class ScriptedModel:
    """Offline protocol test double only. Not evidence of a real model call."""
    def __init__(self, steps):
        self.steps = iter(steps)
        self.histories = []

    async def complete(self, messages, tools):
        self.histories.append(messages.copy())
        return next(self.steps), {"model": "scripted-test-double", "response_id": "offline"}


@pytest.mark.parametrize("names", [("list_dir", "get_preferences"), ("get_preferences", "list_dir")])
async def test_llm_controls_order_and_stop(setup, names):
    ctx, registry = setup
    model = ScriptedModel([{"role": "assistant", "tool_calls": [call(n)]} for n in names] +
                          [{"role": "assistant", "content": "Done (offline protocol test)"}])
    result = await run_agent(model, registry)
    assert result["turns"] == 3
    events = ctx.db.all("SELECT data FROM trace WHERE kind='tool' ORDER BY id")
    assert [json.loads(e["data"])["name"] for e in events] == list(names)
    assert model.histories[1][-1]["role"] == "tool"


async def test_tool_error_is_returned_to_model_for_recovery(setup):
    ctx, registry = setup
    model = ScriptedModel([
        {"role": "assistant", "tool_calls": [call("bash", {"command": "env"})]},
        {"role": "assistant", "tool_calls": [call("list_dir")]},
        {"role": "assistant", "content": "Recovered"}])
    result = await run_agent(model, registry)
    assert result["calls"] == 2
    assert "SecurityError" in model.histories[1][-1]["content"]


async def test_turn_budget_stops_infinite_loop(setup):
    ctx, registry = setup
    ctx.settings.max_model_turns = 2
    model = ScriptedModel([{"role": "assistant", "tool_calls": [call("list_dir")]}] * 5)
    with pytest.raises(BudgetExceeded):
        await run_agent(model, registry)


async def test_no_tools_is_a_valid_graph_exit(setup):
    model = ScriptedModel([{"role": "assistant", "content": "No verifiable news"}])
    state = await run_agent(model, setup[1])
    assert state["calls"] == 0


async def test_trace_does_not_expose_provider_reasoning_or_key(setup):
    ctx, registry = setup
    model = ScriptedModel([{"role": "assistant", "content": ctx.settings.deepseek_api_key,
                            "reasoning_content": "private scratchpad"}])
    await run_agent(model, registry)
    trace = ctx.db.all("SELECT data FROM trace")
    assert "private scratchpad" not in str(trace)
    assert ctx.settings.deepseek_api_key not in str(trace)


async def test_tool_budget_limits_a_batch(setup):
    ctx, registry = setup
    ctx.settings.max_tool_calls = 1
    model = ScriptedModel([{"role": "assistant", "tool_calls": [call("list_dir"), call("get_preferences")]}])
    with pytest.raises(BudgetExceeded, match="Tool call limit"):
        await run_agent(model, registry)
    assert len(ctx.db.all("SELECT * FROM trace WHERE kind='tool'")) == 1


async def test_timeout_marks_context_inactive(setup):
    import asyncio
    ctx, registry = setup
    ctx.settings.run_timeout_seconds = 0
    model = ScriptedModel([])
    with pytest.raises(asyncio.TimeoutError):
        await run_agent(model, registry)
    assert not ctx.active
