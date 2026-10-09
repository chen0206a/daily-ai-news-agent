import httpx
from openai import AsyncOpenAI


class DeepSeekModel:
    def __init__(self, settings):
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
        self.name = settings.deepseek_model
        self.client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url,
                                  timeout=60, max_retries=1,
                                  http_client=httpx.AsyncClient(timeout=60, trust_env=False))

    async def complete(self, messages, tools):
        response = await self.client.chat.completions.create(
            model=self.name, messages=messages, tools=tools, tool_choice="auto",
            temperature=0.2, max_tokens=4096)
        msg = response.choices[0].message
        message = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            message["tool_calls"] = [call.model_dump(exclude_none=True) for call in msg.tool_calls]
        # Keep provider-required reasoning in protocol history when present; never expose it in Trace.
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning is not None:
            message["reasoning_content"] = reasoning
        return message, {"response_id": response.id, "model": response.model,
                         "usage": response.usage.model_dump() if response.usage else {},
                         "finish_reason": response.choices[0].finish_reason}

    async def close(self):
        await self.client.close()
