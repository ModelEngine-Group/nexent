"""LLM-as-judge grading for LongMemEval (S*) free-text answers.

LongMemEval answers are free-text and cannot be scored by exact/F1 matching
reliably (e.g. "50 hours" vs "around 50 hours per week" are both correct).
The original benchmark uses GPT-4o as a judge with per-category prompts
(reported ~97% agreement with humans). We replicate that pattern, but allow
the judge to be either:

  * a dedicated model configured via ``JUDGE_API_KEY`` / ``JUDGE_MODEL_NAME``
    / ``JUDGE_API_URL`` env vars (recommended — avoids self-judging bias);
  * the same ``LLM_*`` model used as the agent (fallback when JUDGE_* is
    unset — keeps "no extra credentials" as the default).

The judge is called via an OpenAI-compatible chat-completions endpoint, which
covers the production DeepSeek / GLM / OpenAI / OpenRouter / Anthropic-proxy
endpoints we use elsewhere in nexent.
"""
import os
import re
from dataclasses import dataclass
from typing import Optional

# ============ Per-category judge prompts ============
# Modeled on LongMemEval's evaluate_qa.py. Each prompt frames the task slightly
# differently to match the ability being tested:
#   - single-session-*: substantive containment of the key fact
#   - multi-session:    aggregation / comparison must match
#   - knowledge-update: must reflect the LATEST value the user stated
#   - temporal-reasoning: must match the time/date implied by the gold
#
# The judge returns "yes" or "no" as the very first token of its reply, which
# we then regex-extract. Any reasoning AFTER "yes"/"no" is allowed but ignored.

_JUDGE_HEADER = (
    "You are an evaluator judging whether a model's answer correctly responds "
    "to a question about a long multi-session chat conversation. You will be "
    "given the question, the gold (reference) answer, and the model's "
    "hypothesis answer. Return a single word — 'yes' if the hypothesis is "
    "correct, 'no' otherwise — followed (optionally) by a one-line reason."
)

_PROMPT_DEFAULT = _JUDGE_HEADER + (
    "\n\nCriterion: the hypothesis is correct if it conveys the same factual "
    "content as the gold answer. Minor wording / unit differences are fine. "
    "Extra correct context is fine; extra contradictions or hallucinated facts "
    "make it wrong."
)

_PROMPT_KNOWLEDGE_UPDATE = _JUDGE_HEADER + (
    "\n\nThis is a KNOWLEDGE-UPDATE question. The user revised their stated "
    "information at some point during the conversation. The hypothesis is "
    "correct ONLY if it reflects the MOST RECENT value, matching the gold. "
    "An answer that gives the older, superseded value is WRONG even if that "
    "older value was once true."
)

_PROMPT_TEMPORAL = _JUDGE_HEADER + (
    "\n\nThis is a TEMPORAL-REASONING question. The hypothesis is correct only "
    "if the time / date / duration it states matches the gold. Different "
    "phrasings of the same time are fine ('Friday' == '2023/05/26 (Fri)'); "
    "answering with the wrong day/week/month is wrong."
)

_PROMPT_MULTI_SESSION = _JUDGE_HEADER + (
    "\n\nThis is a MULTI-SESSION question. The gold answer combines facts "
    "stated across several different sessions. The hypothesis is correct only "
    "if the aggregated / compared result matches the gold; mentioning only "
    "one of the underlying facts is NOT enough."
)

# Single-session variants share the default contract.
_PROMPT_BY_TYPE = {
    "knowledge-update":         _PROMPT_KNOWLEDGE_UPDATE,
    "temporal-reasoning":       _PROMPT_TEMPORAL,
    "multi-session":            _PROMPT_MULTI_SESSION,
    "single-session-user":      _PROMPT_DEFAULT,
    "single-session-assistant": _PROMPT_DEFAULT,
    "single-session-preference":_PROMPT_DEFAULT,
}


@dataclass
class JudgeResult:
    correct: bool
    score: float         # 1.0 if correct else 0.0
    judge_label: str     # normalized "yes" / "no" / "error"
    judge_raw: str       # raw judge output (for debugging)


# ============ Judge configuration ============
# JUDGE_* takes precedence; fall back to LLM_* so the script runs with whatever
# credentials are already in .env.

def _judge_config() -> tuple[str, str, str]:
    """Return (api_key, model_name, base_url) for the judge model.

    Self-hosted vLLM/sglang endpoints commonly accept any api_key (or none).
    When the env value is empty but ``model`` + ``url`` are set, fall back to
    the placeholder ``"EMPTY"`` so the OpenAI client still constructs.
    """
    # Use explicit precedence: JUDGE_* keys override LLM_* keys.
    api_key = (os.getenv("JUDGE_API_KEY")
               or os.getenv("LLM_API_KEY") or "").strip()
    model = (os.getenv("JUDGE_MODEL_NAME")
             or os.getenv("LLM_MODEL_NAME") or "").strip()
    url = (os.getenv("JUDGE_API_URL")
           or os.getenv("LLM_API_URL") or "").strip()
    if not api_key and model and url:
        api_key = "EMPTY"
    return api_key, model, url


_YES_RE = re.compile(r"^\s*(yes|correct|true)\b", re.IGNORECASE)
_NO_RE = re.compile(r"^\s*(no|incorrect|false|wrong)\b", re.IGNORECASE)


def _parse_judge(raw: str) -> str:
    """Map the judge's free-text reply to 'yes' / 'no' / 'unknown'."""
    if not raw:
        return "unknown"
    if _YES_RE.match(raw):
        return "yes"
    if _NO_RE.match(raw):
        return "no"
    # last-chance scan: a 'yes' / 'no' anywhere near the start
    head = raw[:64].lower()
    if "yes" in head and "no" not in head[:head.find("yes")]:
        return "yes"
    if "no" in head:
        return "no"
    return "unknown"


def judge_answer(question: str, gold: str, hypothesis: str,
                 question_type: str) -> JudgeResult:
    """Grade a single answer with an LLM judge.

    Falls back to a string-containment check if the judge endpoint is not
    configured — better a noisy signal than a crash. The fallback is logged
    via the ``judge_label`` field ("fallback_match" / "fallback_miss").
    """
    api_key, model, url = _judge_config()

    if not (api_key and model and url):
        # Fallback: case-insensitive substring containment. Coarse but works
        # as a sanity baseline when no LLM judge is configured.
        gold_norm = (gold or "").strip().lower()
        hyp_norm = (hypothesis or "").strip().lower()
        correct = bool(gold_norm) and gold_norm in hyp_norm
        return JudgeResult(
            correct=correct,
            score=1.0 if correct else 0.0,
            judge_label="fallback_match" if correct else "fallback_miss",
            judge_raw="(no judge model configured; used substring fallback)",
        )

    system_prompt = _PROMPT_BY_TYPE.get(question_type, _PROMPT_DEFAULT)
    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Gold answer:\n{gold}\n\n"
        f"Hypothesis answer:\n{hypothesis}\n\n"
        f"Is the hypothesis correct? Answer 'yes' or 'no' first, then "
        f"(optionally) a brief reason."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=url)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            # Generous budget — Qwen3-style thinking models route reasoning
            # into the same token budget, so 128 was too tight (content came
            # back empty). The actual "yes"/"no" reply is still short.
            max_tokens=1024,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        return JudgeResult(
            correct=False, score=0.0, judge_label="error",
            judge_raw=f"{type(exc).__name__}: {exc}",
        )

    label = _parse_judge(raw)
    correct = label == "yes"
    return JudgeResult(
        correct=correct,
        score=1.0 if correct else 0.0,
        judge_label=label,
        judge_raw=raw,
    )


def judge_configured() -> bool:
    """True iff a dedicated JUDGE_* model is set (not the LLM_* fallback)."""
    return bool(os.getenv("JUDGE_API_KEY") and os.getenv("JUDGE_MODEL_NAME")
                and os.getenv("JUDGE_API_URL"))
