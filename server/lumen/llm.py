"""Groq LLM with an instant fallback model, to live inside the free tier's rate limit.

Groq's free tier allows 8,000 tokens a minute per model, and cached prompt tokens still
count. Each agent turn sends about 2,000 tokens (system prompt, tool schemas, history), so
a lively call runs out within a minute. The stock client then backs off and retries
silently; in the first eval run that showed up as 13-17 s of dead air per turn.

Each Groq model has its own allowance. So instead of waiting, a rate-limited request is
sent again at once to the next model in the list (same prompt, same tools). Only if every
model is limited does it wait, for whichever model the API says will free up first, and
before that wait starts the caller is told ("one moment"), so the wait is never silent.
A model that has hit its daily cap is skipped for the rest of that period.

Text-mode evals need one more thing. A simulated caller answers in a fraction of a
second, so a text conversation sends a request about every second, ten times the rate of
a spoken call, and both models' allowances are gone by the fourth turn. ``min_interval_secs``
spaces requests out to the rate of speech, so evals meet the rate limit about as often as
a real call does. It is off (0) for voice calls.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from loguru import logger
from openai import AsyncStream, RateLimitError
from openai.types.chat import ChatCompletionChunk
from pipecat.frames.frames import Frame, LLMTextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.groq.llm import GroqLLMService
from pipecat.utils.types import assert_given

# With no retry-after header, wait this long before trying a limited model again.
DEFAULT_RETRY_SECS = 5.0
# A model that says to wait longer than this is skipped for that long.
BENCH_IF_OVER_SECS = 60.0
# When every model is limited: wait at most this long per try, this many times.
MAX_WAIT_SECS = 20.0
MAX_WAITS = 3


class GroqFallbackLLMService(GroqLLMService):
    def __init__(
        self,
        *,
        fallback_models: list[str],
        on_fallback: Callable[[str, str], None] | None = None,
        on_request: Callable[[str], None] | None = None,
        on_all_limited: Callable[[], Awaitable[None]] | None = None,
        min_interval_secs: float = 0.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._fallback_models = fallback_models
        self._on_fallback = on_fallback
        self._on_request = on_request
        self._on_all_limited = on_all_limited
        self._min_interval_secs = min_interval_secs
        self._last_request_at = 0.0
        # Models whose limit won't lift for a while (the daily cap): skipped until then, so
        # a turn doesn't spend a round trip on a request that is sure to be refused.
        self._benched_until: dict[str, float] = {}
        # Fail fast on 429 so the fallback model answers instead of the caller hearing silence.
        self._fast_client = self._client.with_options(max_retries=0)
        # Whether the response being generated has said anything aloud yet. end_call reads
        # it: gpt-oss sometimes calls end_call with no goodbye, and the caller hears nothing.
        self.spoke_in_current_response = False

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, LLMTextFrame) and frame.text.strip():
            self.spoke_in_current_response = True
        await super().push_frame(frame, direction)

    async def get_chat_completions(self, context: LLMContext) -> AsyncStream[ChatCompletionChunk]:
        self.spoke_in_current_response = False
        adapter = self.get_llm_adapter()
        self._log_llm_response(context)
        params_from_context = await adapter.get_llm_invocation_params(
            context,
            system_instruction=assert_given(self._settings.system_instruction),
            convert_developer_to_user=not self.supports_developer_role,
        )
        params = self.build_chat_completion_params(params_from_context)

        if self._min_interval_secs:
            wait = self._last_request_at + self._min_interval_secs - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

        primary = params["model"]
        models = [primary, *self._fallback_models]
        now = time.monotonic()
        # Leave out models known to be limited for a long time (the daily cap), unless
        # that would leave nothing to try.
        open_models = [m for m in models if self._benched_until.get(m, 0) <= now] or models
        retry_after: dict[str, float] = {}
        for model in open_models:
            try:
                return await self._request(params, model, primary)
            except RateLimitError as e:
                retry_after[model] = self._note_limit(model, e)

        # Every model is limited. Tell the caller, then wait for whichever model frees up
        # first. That is usually the fallback's per-minute limit (seconds), not the
        # primary's daily cap (minutes): waiting on the primary left demo calls silent
        # until the idle timer hung up.
        if self._on_all_limited:
            await self._on_all_limited()
        error: RateLimitError | None = None
        for _ in range(MAX_WAITS):
            model = min(retry_after, key=lambda m: retry_after[m])
            wait = min(retry_after[model], MAX_WAIT_SECS)
            logger.warning(f"{self}: all models rate-limited; retrying {model} in {wait:.1f}s")
            await asyncio.sleep(wait)
            try:
                return await self._request(params, model, primary)
            except RateLimitError as e:
                error = e
                retry_after[model] = self._note_limit(model, e)
        assert error is not None
        raise error

    async def _request(self, params: dict, model: str, primary: str):
        stream = await self._fast_client.chat.completions.create(**{**params, "model": model})
        if self._on_request:
            self._on_request(model)
        if model != primary:
            logger.info(f"{self}: answered by fallback {model}")
            if self._on_fallback:
                self._on_fallback(primary, model)
        return stream

    def _note_limit(self, model: str, e: RateLimitError) -> float:
        """Log a 429 and return how long the API says to wait, in seconds."""
        try:
            secs = float(e.response.headers.get("retry-after", DEFAULT_RETRY_SECS))
        except (TypeError, ValueError):
            secs = DEFAULT_RETRY_SECS
        logger.warning(f"{self}: {model} rate-limited for {secs:.0f}s ({e.message[:120]})")
        if secs > BENCH_IF_OVER_SECS:
            self._benched_until[model] = time.monotonic() + secs
        return secs
