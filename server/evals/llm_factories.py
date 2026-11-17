"""Free LLM services for the Pipecat eval harness (simulated borrower + judge).

Referenced from scenario YAML as ``factory: evals.llm_factories.<name>``.

Default: Groq free tier, qwen/qwen3.8-27b for both roles. Groq rate-limits each model
separately, so keeping these off the agent's models (gpt-oss-120b, fallback gpt-oss-20b)
means the eval never takes the agent's quota mid-call; it also keeps the judge from
grading its own model's habits.

qwen is not a reliable caller. In about a third of runs it hangs up after one turn ("the
tool requires a single final action, so I end here") or writes a malformed hang-up call
that crashes the run. The runner retries both (evals/run_evals.py). gpt-oss-20b was tried
as the simulator instead and was worse: it hung up within one turn in 7 runs out of 7.

Set EVAL_JUDGE_PROVIDER=ollama to judge with a local Ollama model instead (no rate
limit, slower; needs `ollama serve` and `ollama pull <model>`).
"""

import os

from dotenv import load_dotenv
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import LLMService
from pipecat.services.ollama.llm import OLLamaLLMService

load_dotenv(override=True)

SIMULATOR_MODEL = os.getenv("EVAL_SIMULATOR_MODEL", "qwen/qwen3.8-27b")
JUDGE_PROVIDER = os.getenv("EVAL_JUDGE_PROVIDER", "groq")
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "qwen/qwen3.8-27b")


def _groq(model: str) -> GroqLLMService:
    # Qwen 3 thinks out loud unless told not to; gpt-oss can't turn reasoning off, only down.
    effort = "none" if model.startswith("qwen/") else "low" if model.startswith("openai/") else None
    return GroqLLMService(
        api_key=os.getenv("GROQ_API_KEY"),
        settings=GroqLLMService.Settings(
            model=model, **({"reasoning_effort": effort} if effort else {})
        ),
    )


def simulator(config: dict) -> LLMService:
    return _groq(config.get("model") or SIMULATOR_MODEL)


def judge(config: dict) -> LLMService:
    model = config.get("model") or JUDGE_MODEL
    if JUDGE_PROVIDER == "ollama":
        return OLLamaLLMService(settings=OLLamaLLMService.Settings(model=model))
    return _groq(model)
