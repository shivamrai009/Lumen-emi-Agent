"""A rate-limited turn is answered by the fallback model at once, not after a silent back-off."""

import asyncio
from types import SimpleNamespace

import httpx
from openai import RateLimitError
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.groq.llm import GroqLLMService

from lumen.llm import GroqFallbackLLMService


def _rate_limited(model: str, retry_after: float | None = None) -> RateLimitError:
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    headers = {} if retry_after is None else {"retry-after": str(retry_after)}
    return RateLimitError(
        f"Rate limit reached for model {model}",
        response=httpx.Response(429, request=req, headers=headers),
        body=None,
    )


def _service(limited: set[str], fallbacks: list[str], used: list):
    calls: list[str] = []

    async def create(**params):
        calls.append(params["model"])
        if params["model"] in limited:
            raise _rate_limited(params["model"])
        return f"stream from {params['model']}"

    svc = GroqFallbackLLMService(
        api_key="test-key",
        fallback_models=fallbacks,
        on_fallback=lambda primary, model: used.append(model),
        settings=GroqLLMService.Settings(
            model="openai/gpt-oss-120b", system_instruction="Be brief."
        ),
    )
    svc._fast_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    svc._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return svc, calls


def _context() -> LLMContext:
    return LLMContext(messages=[{"role": "user", "content": "Hello?"}])


def test_primary_answers_when_not_limited():
    used: list = []
    svc, calls = _service(set(), ["openai/gpt-oss-20b"], used)
    assert asyncio.run(svc.get_chat_completions(_context())) == "stream from openai/gpt-oss-120b"
    assert calls == ["openai/gpt-oss-120b"] and used == []


def test_rate_limited_turn_goes_to_fallback_in_the_same_turn():
    used: list = []
    svc, calls = _service({"openai/gpt-oss-120b"}, ["openai/gpt-oss-20b"], used)
    assert asyncio.run(svc.get_chat_completions(_context())) == "stream from openai/gpt-oss-20b"
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert used == ["openai/gpt-oss-20b"]


def test_when_all_are_limited_it_waits_for_the_model_that_frees_up_first(monkeypatch):
    """Seen on demo calls: the primary had hit its daily cap (retry in minutes), the fallback
    its per-minute limit (retry in seconds), and the agent waited on the primary."""
    sleeps: list[float] = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr("lumen.llm.asyncio.sleep", fake_sleep)
    calls: list[str] = []
    told: list[bool] = []
    told_to_wait: list[bool] = []

    async def create(**params):
        calls.append(params["model"])
        if params["model"] == "openai/gpt-oss-120b":
            raise _rate_limited(params["model"], retry_after=600)
        if not told_to_wait:
            told_to_wait.append(True)
            raise _rate_limited(params["model"], retry_after=4)
        return "stream from openai/gpt-oss-20b"

    async def on_all_limited():
        told.append(True)

    svc = GroqFallbackLLMService(
        api_key="test-key",
        fallback_models=["openai/gpt-oss-20b"],
        on_all_limited=on_all_limited,
        settings=GroqLLMService.Settings(
            model="openai/gpt-oss-120b", system_instruction="Be brief."
        ),
    )
    svc._fast_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    assert asyncio.run(svc.get_chat_completions(_context())) == "stream from openai/gpt-oss-20b"
    assert sleeps == [4] and told == [True]
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-20b"]

    # The primary said to wait ten minutes, so the next turn doesn't try it at all.
    calls.clear()
    asyncio.run(svc.get_chat_completions(_context()))
    assert calls == ["openai/gpt-oss-20b"]
