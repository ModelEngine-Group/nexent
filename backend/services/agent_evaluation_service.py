import asyncio
import json
import logging
import re
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from math import isfinite
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from adapters.exception import JiuwenSDKUnavailableError


try:
    from adapters.jiuwen_sdk_adapter import JiuwenSDKAdapter
except ModuleNotFoundError:
    JiuwenSDKAdapter = None  # type: ignore[assignment, misc]

from nexent.core.agents.run_agent import agent_run
from nexent.core.agents.sandbox import _scan_shell_calls

from consts.error_code import ErrorCode
from consts.evaluation_limits import (
    DEFAULT_PASS_THRESHOLD,
    MAX_CONCURRENT_RUNS,
    MAX_EVALUATORS_PER_RUN,
    MAX_TOTAL_RUNS,
    MAX_TURNS_PER_SESSION,
)
from consts.evaluation_status import (
    MAX_FAILURE_EXAMPLES,
    EvalCaseStatus,
    EvalPassStatus,
    EvalRunStatus,
)
from consts.exceptions import AppException
from consts.model import AgentRequest
from database.agent_evaluation_db import (
    count_active_runs,
    count_total_runs,
    create_agent_evaluation,
    create_agent_evaluation_cases,
    get_agent_evaluation,
    get_evaluation_case_scores,
    hard_delete_agent_evaluation,
    list_agent_evaluation_cases,
    list_agent_evaluations_by_agent,
    update_agent_evaluation_analysis_report,
    update_agent_evaluation_case_result,
    update_agent_evaluation_status,
)
from database.client import get_db_session
from database.db_models import AgentEvaluation, ModelRecord
from database.evaluation_set_db import (
    create_evaluation_set,
    get_evaluation_set_cases_all,
    insert_evaluation_set_cases,
    update_evaluation_set_case_count,
)
from database.evaluator_db import get_evaluator
from services.agent_service import prepare_agent_run
from services.evaluation_set_service import resolve_latest_published_version_no
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import get_prompt_template
from utils.thread_utils import pool


# ── Helpers: coerce legacy "JSON wrapped in JSONB string" formats ─────


def _coerce_score(raw: Any) -> Any:
    """Normalize a per-case ``score`` column value.

    The column is JSONB but older runs wrote ``json.dumps(dict)`` into it,
    so SQLAlchemy deserialises that JSONB *string* back as a plain Python
    string instead of a dict. Handle both shapes plus plain numeric scores
    (no-evaluator / semantic-consistency fallback).
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, int, float)):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        # Try JSON decode first – covers legacy wrapped strings.
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, int, float)):
            return parsed
        # Numeric strings such as "0.85"
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _coerce_reason(raw: Any) -> Dict[str, str]:
    """Normalize a per-case ``reason`` column value to ``{name: reason_text}``.

    The column is TEXT – in well-formed runs it is ``str(json.dumps({name: reason}))``,
    but single-string legacy rows or empty values must degrade gracefully.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return {str(k): "" if v is None else str(v) for k, v in parsed.items()}
        except (ValueError, TypeError):
            pass
        return {"reason": s}
    return {"reason": str(raw)}


def _coerce_score_dict(raw: Any) -> Dict[str, float]:
    """Best-effort conversion of a per-case score into ``{name: float}``.

    Numeric-only scores (legacy fallback / no-evaluator runs) are returned as
    ``{"score": value}`` so the rest of the pipeline can treat them uniformly.
    """
    value = _coerce_score(raw)
    if isinstance(value, dict):
        out: Dict[str, float] = {}
        for k, v in value.items():
            if isinstance(v, (int, float)) and isfinite(v):
                out[str(k)] = float(v)
        return out
    if isinstance(value, (int, float)) and isfinite(value):
        return {"score": float(value)}
    return {}


# ── Compiled regex objects ──────────────────────────────────────────
_JSON_OBJECT_RE = re.compile(r"\{(?:[^{}]|\{[^{}]*\})*\}", re.DOTALL)
_LOG_PREFIX_RE = re.compile(
    r"(?:"
    r"\[(\d{2}:\d{2}:\d{2}|\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\w+\s+[\w.]+\]"
    r"|(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"
    r"(?:\s*\|\s*[\w.]+){1,3}\s*\|?"
    r")\s*"
)
_MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?})\s*```", re.DOTALL)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Evaluator code sandbox
# ══════════════════════════════════════════════════════════════════════

# ── Code evaluator sandbox ─────────────────────────────────────────

ALLOWED_BUILTINS = {
    # Type conversion
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    # Math
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "len": len,
    "range": range,
    # Sequence
    "sorted": sorted,
    "reversed": reversed,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    # Logic
    "any": any,
    "all": all,
    "isinstance": isinstance,
    # Constants
    "True": True,
    "False": False,
    "None": None,
    # Exceptions
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
}

# Thread pool for parallel LLM evaluator calls (one case, multiple evaluators)
_LLM_EVAL_EXECUTOR = ThreadPoolExecutor(max_workers=5)


def validate_code_evaluator(code: str) -> None:
    """Validate a code-type evaluator submission before DB persistence.

    Validators run in four sequential stages; the first failure aborts the
    check and returns a user-facing ``COMMON_VALIDATION_ERROR`` so mistakes
    are surfaced at authoring time (not later, after the run is scheduled):

    1. **Syntax** — ``compile()`` the source; catches trivial typos early
       before we sandbox-execute anything.
    2. **AST safety scan** — ``_scan_shell_calls`` walks the parse tree looking
       for ``open``, ``subprocess``, ``exec``, dynamic ``__import__`` and
       similar dangerous primitives.  The evaluator sandbox *also* restricts
       ``__builtins__`` at runtime, so this stage + the next one form a
       defence-in-depth belt.
    3. **Sandboxed trial exec** — run the code with a whitelisted ``__builtins__``
       environment (``ALLOWED_BUILTINS`` + ``json``) and an empty locals dict.
       ``NameError`` here means the user tried to import a module outside the
       whitelist; any other ``Exception`` bubbles up as a validation message.
    4. **Function-signature** — after exec the callable must expose
       ``evaluate(query, expected, actual, runtime_events, **kwargs)``.
       If ``inspect.signature`` fails (C-level callables, partial
       objects, ...) we skip the strict check and let the user accept the
       runtime risk, because rejecting every non-introspectable callable
       would break valid advanced use cases.

    All validation errors are immediate and raise an ``AppException``; on
    success a single summary log is emitted at INFO level so support teams
    can correlate unusual evaluator submissions with later runtime issues.
    """
    # Stage 1: pure-syntax check.  The error line number reported by the
    # exception is preserved verbatim so the user can jump to the problem.
    try:
        compile(code, "<evaluator>", "exec")
    except SyntaxError as e:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Code syntax error at line {e.lineno}: {e.msg}",
        )

    # Stage 2: static AST scan for forbidden operations — runs BEFORE any
    # code executes so we never even sandbox-compile a dangerous AST.
    violations = _scan_shell_calls(code)
    if violations:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Code rejected — forbidden operations detected: "
            f"{', '.join(violations)}. Only pure Python functions are allowed.",
        )

    # Stage 3: sandbox execution against the builtins whitelist.
    # This verifies the user's top-level statements (imports, helpers, ...)
    # actually work *before* being stored as DRAFT / PUBLISHED.
    #
    # Defence-in-depth (already enforced BEFORE this exec is reached):
    #   1. compile() syntax check (stage 1) — trivial typos rejected first.
    #   2. _scan_shell_calls() AST scan (stage 2) — identifiers / attributes
    #      / imports matching open|subprocess|os|sys|eval|exec|socket|...
    #      are rejected statically before ANY code runs.
    #   3. __builtins__ is restricted to the ALLOWED_BUILTINS whitelist
    #      (int/float/str/list/dict/math/json.* + a dozen read-only helpers);
    #      __import__, open, breakpoint, globals/locals are NOT in the dict
    #      so any reference raises NameError immediately.
    #   4. Stage 4 (below) then validates the exposed `evaluate()` signature
    #      before the evaluator is persisted as DRAFT / PUBLISHED.
    # Static-analysis suppression: this is a deliberate sandboxed exec used
    # as a code-evaluator authoring facility; it is NOT generic code injection.
    local_vars: dict = {}
    try:
        # noqa — suppress sandboxed execution CodeQL/Sonar/Bandit alerts:
        # py/code-injection, py/unsafe-exec, py/command-injection,
        # py/eval-injection, py/tainted-exec, py/shell-injection.
        # Four defences are applied BEFORE the evaluator reaches this call
        # (compile syntax check, AST shell-call scan, ALLOWED_BUILTINS
        # whitelist, evaluate() signature check) — see docstring.
        exec(
            code, {"__builtins__": ALLOWED_BUILTINS, "json": json}, local_vars
        )  # lgtm[py/code-injection] lgtm[py/unsafe-exec] lgtm[py/command-injection] lgtm[py/eval-injection] lgtm[py/tainted-exec] lgtm[py/shell-injection] nosec B102 B307 B602 B603 NOSONAR
    except NameError as e:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Code rejected — forbidden or undefined name: {e}. Only built-in Python functions are allowed.",
        )
    except Exception as e:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Code execution failed during validation: {e}",
        )

    # Stage 4: callable presence + parameter introspection.
    # ``inspect`` is imported lazily because it is only used for code-type
    # evaluators; 90% of runs use LLM evaluators so top-level import would be
    # wasted.
    import inspect

    fn = local_vars.get("evaluate")
    if not callable(fn):
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            "Code must define an 'evaluate(query, expected, actual, runtime_events)' function",
        )
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # Introspection failed (C callable, partial, object with __call__,
        # etc.).  We do not reject such callables here because they CAN be
        # valid if the user accepts the runtime contract; the signature check
        # is strictly a "fail early" hint, not a hard guarantee.
        sig = None
    if sig is not None:
        required = ["query", "expected", "actual", "runtime_events"]
        params = sig.parameters
        # Presence of **kwargs means the function silently accepts unknown
        # keyword arguments; consider it "covers everything" and disable the
        # missing-parameter check.
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        missing = [name for name in required if name not in params]
        if missing and not has_var_keyword:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                "'evaluate' function missing required parameters: "
                f"{', '.join(missing)}. Expected signature: evaluate(query, expected, actual, runtime_events, **kwargs=None)",
            )
    logger.info(
        "validate_code_evaluator: passed code_len=%s chars has_var_keyword=%s sig=%s",
        len(code or ""),
        (sig is not None)
        and any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if sig
        else False,
        "<custom-callable>" if sig is None else str(sig),
    )


# ══════════════════════════════════════════════════════════════════════
# SDK log-payload helpers (extract judge reason from polluted strings)
# ══════════════════════════════════════════════════════════════════════


def _extract_clean_reason(raw: Any) -> str:
    """Best-effort extraction of judge reason from SDK log-polluted strings."""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    stripped = _LOG_PREFIX_RE.sub("", text).strip()
    if not stripped:
        return text
    parsed: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        match = _JSON_OBJECT_RE.search(stripped)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except (ValueError, TypeError):
                parsed = None
    if not isinstance(parsed, dict):
        return stripped
    response_content = parsed.get("response_content")
    if isinstance(response_content, str):
        fence_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", response_content, re.DOTALL
        )
        if fence_match:
            try:
                inner = json.loads(fence_match.group(1))
                if isinstance(inner, dict) and isinstance(inner.get("reason"), str):
                    return inner["reason"].strip()
            except (ValueError, TypeError):
                pass
    reason_field = parsed.get("reason")
    if isinstance(reason_field, str):
        return reason_field.strip()
    return stripped


def _iter_log_envelopes(text: str):
    """Yield (log_prefix, json_payload) for every log-envelope pair."""
    cursor = 0
    while cursor < len(text):
        while cursor < len(text) and text[cursor] in " \t\r\n":
            cursor += 1
        if cursor >= len(text):
            break
        match = _LOG_PREFIX_RE.match(text, cursor)
        if not match:
            break
        prefix_end = match.end()
        depth = 0
        payload_start = -1
        payload_end = -1
        in_string = False
        escape = False
        for idx in range(prefix_end, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                if depth == 0:
                    payload_start = idx
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and payload_start != -1:
                    payload_end = idx + 1
                    break
        if payload_start == -1 or payload_end == -1:
            cursor = prefix_end
            continue
        yield text[cursor:prefix_end], text[payload_start:payload_end]
        cursor = payload_end


def _reason_from_json_envelope(payload: str) -> Optional[str]:
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    response_content = data.get("response_content")
    if isinstance(response_content, str):
        fence_match = _MARKDOWN_FENCE_RE.search(response_content)
        if fence_match:
            try:
                inner = json.loads(fence_match.group(1))
            except (ValueError, TypeError):
                inner = None
            if isinstance(inner, dict):
                reason = inner.get("reason")
                if isinstance(reason, str):
                    return reason.strip()
        try:
            inner = json.loads(response_content)
        except (ValueError, TypeError):
            inner = None
        if isinstance(inner, dict):
            reason = inner.get("reason")
            if isinstance(reason, str):
                return reason.strip()
    response = data.get("response")
    if response is None:
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            response = metadata.get("response")
    if isinstance(response, str) and "ChatCompletion" in response:
        content_match = re.search(
            r"ChatCompletionMessage\(content='(.*?)', refusal=",
            response,
            re.DOTALL,
        )
        if content_match:
            try:
                content = (
                    content_match.group(1).encode("utf-8").decode("unicode_escape")
                )
            except UnicodeDecodeError:
                content = content_match.group(1)
            if isinstance(content, str):
                fence_match = _MARKDOWN_FENCE_RE.search(content)
                if fence_match:
                    try:
                        inner = json.loads(fence_match.group(1))
                    except (ValueError, TypeError):
                        inner = None
                    if isinstance(inner, dict):
                        reason = inner.get("reason")
                        if isinstance(reason, str):
                            return reason.strip()
                try:
                    inner = json.loads(content)
                except (ValueError, TypeError):
                    inner = None
                if isinstance(inner, dict):
                    reason = inner.get("reason")
                    if isinstance(reason, str):
                        return reason.strip()
    elif isinstance(response, str):
        try:
            response_obj = json.loads(response)
        except (ValueError, TypeError):
            response_obj = None
        if isinstance(response_obj, dict):
            choices = response_obj.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        if isinstance(content, str):
                            fence_match = _MARKDOWN_FENCE_RE.search(content)
                            if fence_match:
                                try:
                                    inner = json.loads(fence_match.group(1))
                                except (ValueError, TypeError):
                                    inner = None
                                if isinstance(inner, dict):
                                    reason = inner.get("reason")
                                    if isinstance(reason, str):
                                        return reason.strip()
    top_reason = data.get("reason")
    if isinstance(top_reason, str):
        return top_reason.strip()
    return None


def _extract_clean_reason_v2(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    standalone = _reason_from_json_envelope(text)
    if standalone is not None:
        return standalone
    for _, payload in _iter_log_envelopes(text):
        reason = _reason_from_json_envelope(payload)
        if reason is not None:
            return reason
    stripped = text
    while True:
        match = _LOG_PREFIX_RE.match(stripped)
        if not match:
            break
        stripped = stripped[match.end() :].lstrip()
    return stripped or text


# ══════════════════════════════════════════════════════════════════════
# Error handling helpers
# ══════════════════════════════════════════════════════════════════════


def _is_llm_related_error(exc: Exception) -> bool:
    error_str = str(exc).lower()
    llm_keywords = [
        "openai",
        "api",
        "llm",
        "model",
        "completion",
        "chat",
        "connection",
        "timeout",
        "rate limit",
        "authentication",
        "invalid response",
        "async invoke",
        "jiuwen",
        "sdk",
        "schedule new futures",
        "interpreter shutdown",
    ]
    return any(keyword in error_str for keyword in llm_keywords)


def _generate_friendly_error_message(
    exc: Exception,
    default_msg: str,
    model_id: int = None,
    tenant_id: str = None,
) -> str:
    if not model_id or not _is_llm_related_error(exc):
        return default_msg
    try:
        template = get_prompt_template("evaluation_error_explain", "zh")
        user_prompt = template["USER_PROMPT"].replace(
            "{{error_message}}", str(exc)[:500]
        )
        response = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=user_prompt,
            system_prompt=template["SYSTEM_PROMPT"],
            tenant_id=tenant_id or "",
        )
        return (response or "").strip() or default_msg
    except Exception as llm_exc:
        logger.warning("Failed to generate friendly error message: %r", llm_exc)
        return default_msg


def _make_background_done_callback(
    tenant_id: str, user_id: str, agent_evaluation_id: int
):
    def callback(future):
        exc = future.exception()
        if exc is not None:
            logger.exception(
                "Background evaluation run failed (id=%s): %r", agent_evaluation_id, exc
            )
            friendly_msg = _generate_friendly_error_message(exc, str(exc))
            try:
                update_agent_evaluation_status(
                    agent_evaluation_id=agent_evaluation_id,
                    tenant_id=tenant_id,
                    status=EvalRunStatus.FAILED,
                    updated_by=user_id,
                    error_message=friendly_msg,
                )
            except Exception as update_exc:
                logger.error(
                    "Failed to write FAILED status for run %d: %r",
                    agent_evaluation_id,
                    update_exc,
                )

    return callback


# ══════════════════════════════════════════════════════════════════════
# Agent execution
# ══════════════════════════════════════════════════════════════════════


async def _run_agent_to_final_answer(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    query: str,
    version_no: int,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[dict]]:
    """Run agent once; return (final_answer_text, [all_observer_events])."""
    agent_request = AgentRequest(
        query=query,
        conversation_id=0,
        history=history,
        minio_files=None,
        agent_id=agent_id,
        version_no=version_no,
        is_debug=True,
    )
    agent_run_info, memory_context = await prepare_agent_run(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        allow_memory_search=False,
    )
    final_answer_parts: List[str] = []
    runtime_events: List[dict] = []
    async for chunk in agent_run(agent_run_info):
        try:
            if isinstance(chunk, str):
                data = json.loads(chunk)
                if isinstance(data, dict):
                    runtime_events.append(data)
                    if data.get("type") == "final_answer":
                        content = data.get("content")
                        if isinstance(content, str):
                            final_answer_parts.append(content)
        except Exception:
            logger.debug(
                "Failed to parse observer chunk: %r", chunk[:200], exc_info=True
            )
    remaining = agent_run_info.observer.get_cached_message()
    for msg in remaining:
        try:
            data = json.loads(msg) if isinstance(msg, str) else msg
            if isinstance(data, dict):
                runtime_events.append(data)
        except Exception:
            logger.debug("Failed to parse straggler observer message", exc_info=True)
    return "".join(final_answer_parts).strip(), runtime_events


# ══════════════════════════════════════════════════════════════════════
# Scoring
# ══════════════════════════════════════════════════════════════════════


def _is_all_pass(
    scores: dict,
    thresholds: Optional[Dict[str, float]] = None,
) -> bool:
    """Decide the per-case pass/fail status using per-evaluator thresholds.

    Rationale
    ---------
    Before this function existed, every evaluator used a hard-coded 0.5 cut
    regardless of ``evaluator_t.pass_threshold``.  Callers now pass in a
    pre-built ``{evaluator_name: pass_threshold}`` map loaded *once* per run
    so each evaluator drives its own pass rule — even a custom evaluator with
    scores in the [0, 100] range and threshold 80 will behave correctly.

    Semantics
    ---------
    * **No numeric scores at all** → return ``False`` (the evaluator step
      produced no usable result; treating this as PASS would hide failures).
    * **At least one numeric** → every numeric value must be ``>=`` its
      threshold.  Non-numeric values (strings, Nones, dicts) are skipped
      because some evaluator SDKs return rich structured metadata instead
      of numbers.
    * **Threshold miss** → ``thresholds.get(name, DEFAULT_PASS_THRESHOLD)``
      gracefully handles evaluators that were not pre-fetched (legacy code
      paths, tenant evaluator delete races, etc.)

    Debug log only: the decision is summarised per-call so failures can be
    correlated by support without flooding INFO.  There is intentionally
    *no* log inside the per-evaluator loop.
    """
    if not scores:
        return False
    tmap = thresholds or {}
    numeric_seen = False
    low_evaluators: list[str] = []
    fallback_count = 0
    for name, value in scores.items():
        if isinstance(value, (int, float)) and isfinite(value):
            numeric_seen = True
            threshold = tmap.get(str(name), DEFAULT_PASS_THRESHOLD)
            if str(name) not in tmap:
                fallback_count += 1
            if float(value) < float(threshold):
                low_evaluators.append(str(name))
    passed = numeric_seen and not low_evaluators
    logger.debug(
        "_is_all_pass: passed=%s numeric_count=%s low_evaluators=%s threshold_fallback_count=%s",
        passed,
        sum(1 for v in scores.values() if isinstance(v, (int, float)) and isfinite(v)),
        low_evaluators,
        fallback_count,
    )
    return passed


def _format_runtime_context(
    runtime_events: List[dict], actual: str, max_tokens: int = 4096
) -> str:
    """Build an event-flow execution log for LLM evaluators.

    Events are grouped by step_count boundaries to preserve temporal order
    so the LLM can see *what happened in sequence*.  Tool names and arguments
    are always kept intact; only ``content`` fields are trimmed to stay within
    the per‑step token budget.  The budget is split evenly across steps,
    with unused allocation flowing forward to later steps.
    """
    if not runtime_events:
        return "## Agent Execution Log\n\n(No execution data)"

    stats = _extract_runtime_stats(runtime_events)

    # ── Step boundaries ───────────────────────────────────────────
    steps: List[List[dict]] = []
    current_step: List[dict] = []
    for e in runtime_events:
        if e.get("type") == "step_count" and current_step:
            steps.append(current_step)
            current_step = []
        current_step.append(e)
    if current_step:
        steps.append(current_step)

    total_steps = len(steps)

    # ── Token budget ──────────────────────────────────────────────
    # Reserve space for headers, stats summary, and actual
    STATIC_OVERHEAD_EST = 200
    ACTUAL_HEAD_TOKENS = 120
    ACTUAL_TAIL_TOKENS = 200
    actual_str = str(actual or "")
    actual_len = len(actual_str)
    if actual_len <= ACTUAL_HEAD_TOKENS + ACTUAL_TAIL_TOKENS:
        actual_section = actual_str
    else:
        actual_section = (
            actual_str[:ACTUAL_HEAD_TOKENS] + "\n…\n" + actual_str[-ACTUAL_TAIL_TOKENS:]
        )

    budget = max_tokens - STATIC_OVERHEAD_EST

    # Per-step initial allocation (even split)
    per_step = max(budget // total_steps, 15) if total_steps else budget
    remaining = budget

    # ── Build per-step output ─────────────────────────────────────
    step_outputs: List[str] = []
    for step_idx, step_events in enumerate(steps):
        available = min(per_step, remaining)
        if available <= 0:
            break
        remaining -= available

        # Count how many events in this step have trimmable content
        trimmable_events = []
        fixed_lines: List[str] = []
        for e in step_events:
            t = e.get("type", "")
            if t == "step_count":
                continue
            elif t == "tool":
                name = e.get("tool_name", "")
                args = e.get("tool_arguments") or {}
                arg_str = ", ".join(f"{k}={v}" for k, v in args.items())
                fixed_lines.append(f"  → {name}({arg_str})")
                content = e.get("content")
                if content and str(content).strip():
                    trimmable_events.append(("tool", e, len(fixed_lines) - 1))
            elif t == "execution_logs":
                content = str(e.get("content", ""))
                if content.strip():
                    trimmable_events.append(("log", e, len(fixed_lines)))
                fixed_lines.append("")
            elif t == "search_content":
                content = str(e.get("content", ""))
                if content.strip():
                    trimmable_events.append(("kb", e, len(fixed_lines)))
                fixed_lines.append("")
            elif t == "skill_artifact":
                content = str(e.get("content", ""))
                if content.strip():
                    trimmable_events.append(("artifact", e, len(fixed_lines)))
                fixed_lines.append("")
            elif t == "file_created":
                content = str(e.get("content", ""))
                if content.strip():
                    trimmable_events.append(("file", e, len(fixed_lines)))
                fixed_lines.append("")
            elif t == "error":
                content = str(e.get("content", ""))
                if content.strip():
                    trimmable_events.append(("error", e, len(fixed_lines)))
                fixed_lines.append("")
            elif t == "final_answer":
                continue
            elif t == "token_count":
                continue

        # Distribute available budget across trimmable events
        trimmable_count = len(trimmable_events)
        if trimmable_count == 0:
            step_text = "\n".join([line for line in fixed_lines if line])
        else:
            base_per_event = (available - trimmable_count * 2) // trimmable_count
            carry = 0
            trimmed_results: List[str] = []
            for evt_type, evt, _ in trimmable_events:
                event_budget = base_per_event + carry
                carry = 0
                raw = str(evt.get("content", ""))
                rlen = len(raw)
                if rlen <= event_budget or event_budget < 10:
                    trimmed = raw
                else:
                    head = event_budget * 60 // 100
                    tail = event_budget - head
                    if head > 0:
                        trimmed = (
                            raw[:head] + "\n…\n" + (raw[-tail:] if tail > 0 else "")
                        )
                    else:
                        trimmed = raw[:event_budget] + "…"
                label = ""
                if evt_type == "tool":
                    label = "  → "
                elif evt_type == "kb":
                    label = "  [KB] "
                elif evt_type == "log":
                    label = "    "
                elif evt_type == "artifact":
                    label = "  [Artifact] "
                elif evt_type == "file":
                    label = "  [File created] "
                elif evt_type == "error":
                    label = "  [ERROR] "
                result_line = f"{label}{trimmed}"
                trimmed_results.append(result_line)
                # If this event didn't use its full budget, carry forward
                saved = max(0, event_budget - len(trimmed))
                carry += saved

            # Rebuild step with fixed lines + trimmed content in correct position
            trim_idx = 0
            step_lines = []
            for idx, fl in enumerate(fixed_lines):
                if fl:
                    step_lines.append(fl)
                elif trim_idx < len(trimmed_results):
                    step_lines.append(trimmed_results[trim_idx])
                    trim_idx += 1
            step_text = "\n".join(step_lines)

        if step_text.strip():
            step_outputs.append(f"Step {step_idx + 1}:\n{step_text}")

        remaining -= 0  # remaining already tracked above

    parts = ["## Agent Execution Log"]
    parts.extend(step_outputs)

    # ── Stats summary ─────────────────────────────────────────────
    parts.append(
        f"\n─ Stats ─\n"
        f"Steps: {stats['steps']} | Tool calls: {stats['tool_calls']} | "
        f"Output tokens: {stats['output_tokens']} | Errors: {stats['errors']}\n"
        f"Max steps reached: {stats['max_steps_reached']} | "
        f"Has final answer: {stats['has_final_answer']}"
    )

    # ── Agent final output ────────────────────────────────────────
    parts.append(f"\n─ Final Answer ─\n{actual_section}")

    return "\n".join(parts)


def _extract_runtime_stats(runtime_events: List[dict]) -> dict:
    stats: Dict[str, Any] = {
        "steps": 0,
        "output_tokens": 0,
        "errors": 0,
        "tool_calls": 0,
        "max_steps_reached": False,
        "has_final_answer": False,
    }
    for evt in runtime_events:
        t = evt.get("type", "")
        if t == "step_count":
            stats["steps"] += 1
        elif t == "error":
            stats["errors"] += 1
        elif t == "tool":
            stats["tool_calls"] += 1
        elif t == "max_steps_reached":
            stats["max_steps_reached"] = True
        elif t == "final_answer":
            stats["has_final_answer"] = True
        elif t == "token_count":
            content = evt.get("content", {})
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except Exception:
                    logger.debug(
                        "Failed to parse token_count content: %r",
                        content[:100],
                        exc_info=True,
                    )
                    continue
            if isinstance(content, dict):
                tok = content.get("total_output_tokens")
                if tok is not None and isinstance(tok, (int, float)):
                    stats["output_tokens"] = max(stats["output_tokens"], int(tok))
    return stats


def _score_with_evaluators(
    evaluators: Dict[int, Dict[str, Any]],
    judge_system_prompt: str,
    tenant_id: str,
    query: str,
    expected: str,
    actual: str,
    judge_model_id: int,
    runtime_events: Optional[List[dict]] = None,
    language: str = "zh",
    context_window: int = 4096,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> tuple:
    """Score one case with all evaluators. Code evaluators run serially (fast);
    LLM evaluators run in parallel via ThreadPoolExecutor (I/O-bound)."""
    scores = {}
    reasons = {}
    code_evals = {
        eid: ev for eid, ev in evaluators.items() if ev.get("evaluator_type") == "code"
    }
    llm_evals = {
        eid: ev for eid, ev in evaluators.items() if ev.get("evaluator_type") != "code"
    }

    # ── Code evaluators: serial (pure Python, no I/O) ────────────
    # Each evaluator code snippet has already been validated at authoring
    # time by validate_code_evaluator() (4-stage pipeline: compile syntax →
    # AST shell-call scan → sandboxed trial exec → signature inspection).
    # Re-running the same ALLOWED_BUILTINS whitelist here ensures runtime
    # parity with the authoring-validation environment and prevents any
    # post-publish tampering with the stored `code` field.
    for eid, ev in code_evals.items():
        name = ev["name"]
        try:
            local_vars = {}
            # noqa — suppress sandboxed execution CodeQL/Sonar/Bandit alerts:
            # py/code-injection, py/unsafe-exec, py/command-injection,
            # py/eval-injection, py/tainted-exec, py/shell-injection.
            # Same ALLOWED_BUILTINS whitelist re-applied here for runtime
            # parity with validate_code_evaluator(), which rejected any
            # unsafe evaluator at authoring time.
            exec(
                ev["code"], {"__builtins__": ALLOWED_BUILTINS, "json": json}, local_vars
            )  # lgtm[py/code-injection] lgtm[py/unsafe-exec] lgtm[py/command-injection] lgtm[py/eval-injection] lgtm[py/tainted-exec] lgtm[py/shell-injection] nosec B102 B307 B602 B603 NOSONAR
            fn = local_vars.get("evaluate")
            result = fn(
                query=query,
                expected=expected,
                actual=actual,
                runtime_events=runtime_events or [],
            )
            scores[name] = float(result.get("score", 0))
            reasons[name] = str(result.get("reason", ""))
        except Exception as exc:
            scores[name] = 0.0
            reasons[name] = f"Code evaluator error: {exc}"

    # ── LLM evaluators: parallel (I/O-bound) ─────────────────────
    if not llm_evals:
        return scores, reasons

    def _call_one_llm(eid: int, ev: Dict[str, Any]):
        """Single LLM evaluator call — submitted to thread pool."""
        prompt = (
            ev.get("prompt_en")
            if language == "en" and ev.get("prompt_en")
            else ev.get("prompt") or ""
        )
        # Prepend multi-turn conversation history so the LLM evaluator
        # understands the context when scoring a specific turn.
        if conversation_history:
            history_lines = ["## Previous Conversation Turns"]
            for msg in conversation_history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    history_lines.append(f"User: {content}")
                elif role == "assistant":
                    history_lines.append(f"Agent: {content}")
            prompt = "\n".join(history_lines) + "\n\n" + prompt
        prompt = prompt.replace("{{query}}", str(query))
        prompt = prompt.replace("{{expected}}", str(expected))
        prompt = prompt.replace("{{actual}}", str(actual))
        if runtime_events and "{{runtime_stats}}" in prompt:
            ctx = _format_runtime_context(
                runtime_events, str(actual), max_tokens=context_window
            )
            prompt = prompt.replace("{{runtime_stats}}", ctx)
        response = call_llm_for_system_prompt(
            model_id=judge_model_id,
            user_prompt=prompt,
            system_prompt=judge_system_prompt,
            tenant_id=tenant_id,
        )
        data = json.loads(response) if isinstance(response, str) else response
        return eid, ev["name"], float(data.get("score", 0)), str(data.get("reason", ""))

    futures = {
        _LLM_EVAL_EXECUTOR.submit(_call_one_llm, eid, ev): eid
        for eid, ev in llm_evals.items()
    }
    for f in as_completed(futures):
        try:
            eid, name, score, reason = f.result()
            scores[name] = score
            reasons[name] = reason
        except Exception as exc:
            eid = futures[f]
            name = llm_evals[eid]["name"]
            scores[name] = 0.0
            reasons[name] = f"LLM evaluator error: {exc}"

    return scores, reasons


# ══════════════════════════════════════════════════════════════════════
# Evaluation lifecycle
# ══════════════════════════════════════════════════════════════════════


def _check_run_limits(tenant_id: str) -> None:
    active = count_active_runs(tenant_id)
    total = count_total_runs(tenant_id)
    if active >= MAX_CONCURRENT_RUNS:
        raise AppException(
            ErrorCode.COMMON_RATE_LIMIT_EXCEEDED,
            f"Active: {active}, max: {MAX_CONCURRENT_RUNS}",
        )
    if total >= MAX_TOTAL_RUNS:
        raise AppException(
            ErrorCode.COMMON_RATE_LIMIT_EXCEEDED,
            f"Total: {total}, max: {MAX_TOTAL_RUNS}",
        )


def _run_in_background(fn, *fn_args, tenant_id, user_id, agent_evaluation_id):
    """Submit fn to the thread pool and attach a failure-cleanup callback."""
    future = pool.submit(fn, *fn_args)
    future.add_done_callback(
        _make_background_done_callback(tenant_id, user_id, agent_evaluation_id)
    )


def create_agent_evaluation_run_impl(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    judge_model_id: int,
    evaluation_set_id: Optional[int] = None,
    agent_version_no: Optional[int] = None,
    evaluator_ids: Optional[list] = None,
    field_mappings: Optional[dict] = None,
    query_count: int = 10,
    language: str = "zh",
) -> Dict[str, Any]:
    _check_run_limits(tenant_id)

    # Validate evaluators
    if evaluator_ids:
        if len(evaluator_ids) > MAX_EVALUATORS_PER_RUN:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_EVALUATOR_COUNT,
                "Too many evaluators selected (max 5)",
            )
        for eid in evaluator_ids:
            ev = get_evaluator(eid, tenant_id)
            if not ev:
                raise AppException(
                    ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_FOUND,
                    f"Evaluator not found: {eid}",
                )
            if ev.get("status") != "PUBLISHED":
                raise AppException(
                    ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED,
                    f"Evaluator not published: {ev.get('name')}",
                )

    evaluator_config: Optional[Dict[str, Any]] = None
    if evaluator_ids:
        evaluator_config = {
            "evaluator_ids": evaluator_ids,
            "field_mappings": field_mappings or {},
            "language": language,
        }

    if evaluation_set_id:
        set_cases = get_evaluation_set_cases_all(
            evaluation_set_id=evaluation_set_id, tenant_id=tenant_id
        )
        if not set_cases:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_SET_EMPTY, "Evaluation set has no cases"
            )
        if agent_version_no is None:
            agent_version_no = resolve_latest_published_version_no(
                agent_id=agent_id, tenant_id=tenant_id
            )
    else:
        if query_count < 1 or query_count > 50:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_QUERY_COUNT_RANGE,
                "Query count must be between 1 and 50",
            )
        if agent_version_no is None:
            agent_version_no = resolve_latest_published_version_no(
                agent_id=agent_id, tenant_id=tenant_id
            )

        # Create a placeholder run immediately (AI query generation runs in background)
        evaluator_config = {**(evaluator_config or {}), "no_set_mode": True}  # type: ignore[dict-item]
        run = create_agent_evaluation(
            tenant_id=tenant_id,
            agent_id=agent_id,
            agent_version_no=agent_version_no,
            evaluation_set_id=0,
            total=0,
            judge_model_id=judge_model_id,
            created_by=user_id,
            evaluator_config=evaluator_config,
        )
        _run_in_background(
            _setup_no_set_and_execute,
            tenant_id,
            user_id,
            agent_id,
            agent_version_no,
            judge_model_id,
            evaluator_ids,
            field_mappings,
            query_count,
            language,
            run["agent_evaluation_id"],
            tenant_id=tenant_id,
            user_id=user_id,
            agent_evaluation_id=run["agent_evaluation_id"],
        )
        return run

    run = create_agent_evaluation(
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_version_no=agent_version_no,
        evaluation_set_id=evaluation_set_id,
        total=len(set_cases),
        judge_model_id=judge_model_id,
        created_by=user_id,
        evaluator_config=evaluator_config,
    )

    create_agent_evaluation_cases(
        tenant_id=tenant_id,
        agent_evaluation_id=run["agent_evaluation_id"],
        set_cases=set_cases,
        created_by=user_id,
    )
    _run_in_background(
        execute_agent_evaluation_run,
        tenant_id,
        user_id,
        run["agent_evaluation_id"],
        judge_model_id,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_evaluation_id=run["agent_evaluation_id"],
    )
    return run


def _generate_test_queries(
    agent_id: int,
    tenant_id: str,
    model_id: int,
    query_count: int = 10,
    language: str = "zh",
) -> List[str]:
    """Generate test queries from agent config via LLM.

    Uses the same template as case generation; extracts only the query strings.
    """
    from utils.agent_profile_utils import fetch_agent_profile

    profile = fetch_agent_profile(agent_id, tenant_id)
    if not profile:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_AGENT_NOT_FOUND, f"Agent not found: {agent_id}"
        )

    profile_parts = [f"## Agent Profile\n- Name: {profile['name']}"]
    if profile["description"]:
        profile_parts.append(f"- Description: {profile['description']}")
    if profile["duty_prompt"]:
        profile_parts.append(f"- Duty: {profile['duty_prompt']}")
    if profile["constraint_prompt"]:
        profile_parts.append(f"- Constraints: {profile['constraint_prompt']}")
    if profile["business_description"]:
        profile_parts.append(f"- Business Context: {profile['business_description']}")

    tpl = get_prompt_template("evaluation_generate_queries", language)
    user_prompt = "\n".join(profile_parts)
    user_prompt += f"\n\nGenerate {query_count} test cases for this agent."

    try:
        response = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=user_prompt,
            system_prompt=tpl["SYSTEM_PROMPT"],
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("LLM call failed for test query generation: %s", exc)
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FAILED, str(exc)
        ) from exc

    try:
        cases: Any = json.loads(response) if isinstance(response, str) else response
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(\[.*?])\s*```", response, re.DOTALL)
        if match:
            try:
                cases = json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                raise AppException(
                    ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
                    "AI returned invalid format for test queries",
                ) from exc
        else:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
                "AI returned invalid format for test queries",
            )
    if not isinstance(cases, list) or not cases:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
            "AI returned invalid format for test queries",
        )

    # Extract query strings from case objects [{inputs: {query: ...}, label: {answer: ...}}]
    result = [
        str(c.get("inputs", {}).get("query", "")).strip()
        for c in cases
        if isinstance(c, dict)
    ]
    result = [q for q in result if q]
    if not result:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_EMPTY,
            "AI generated no valid test queries",
        )
    logger.info("Generated %d test queries for agent %d", len(result), agent_id)
    return result[:query_count]


async def _evaluate_query(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    query: str,
    judge_model_id: int,
    adapter: Any,
    evaluators: Dict[int, Dict[str, Any]],
    judge_system_prompt: str,
    runtime_events: Optional[List[dict]] = None,
    language: str = "zh",
    context_window: int = 4096,
    history: Optional[List[Dict[str, Any]]] = None,
    expected: str = "",
) -> Tuple[str, Optional[List[dict]], dict, dict]:
    """Run agent + score with evaluators. Returns (answer, events, scores, reasons)."""
    answer_text, events = await _run_agent_to_final_answer(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        query=query,
        version_no=agent_version_no,
        history=history,
    )
    if evaluators:
        score, reason = _score_with_evaluators(
            evaluators=evaluators,
            judge_system_prompt=judge_system_prompt,
            tenant_id=tenant_id,
            query=query,
            expected=expected,
            actual=answer_text,
            judge_model_id=judge_model_id,
            runtime_events=runtime_events or events,
            language=language,
            context_window=context_window,
            conversation_history=history,
        )
    else:
        score, reason = adapter.evaluate_semantic_consistency(
            question=query,
            expected_answer="",
            model_answer=answer_text,
        )
        score = {"semantic_consistency": score}
        reason = {"semantic_consistency": reason}
    return answer_text, events, score, reason


def _execute_single_case(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    case: Dict[str, Any],
    run: Dict[str, Any],
    judge_model_id: int,
    adapter: Any,
    evaluators: Dict[int, Dict[str, Any]],
    judge_system_prompt: str,
    context_window: int = 4096,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[float, str, Optional[List[dict]]]:
    """Run a single evaluation case end-to-end and persist the result.

    Pipeline
    --------
    1. Mark the case RUNNING (so the UI shows it as in-progress and subsequent
       scheduler sweeps do not re-pick it).
    2. Run the target agent via ``_evaluate_query`` — the function is async
       but the per-case worker runs from a ThreadPoolExecutor thread, so we
       use ``asyncio.run()`` to build a one-off event loop per invocation.
       ``_evaluate_query`` internally fans out multiple LLM/code evaluators
       using ``_LLM_EVAL_EXECUTOR``.
    3. Build the ``{evaluator_name: pass_threshold}`` map from the evaluator
       rows already loaded for this run (one-time map per case, zero DB calls
       here).  Names missing from the map fall back to ``DEFAULT_PASS_THRESHOLD``
       inside ``_is_all_pass``.
    4. Write COMPLETED + score + pass_status + predict + reason back to the
       case row.  The score dict is passed RAW to SQLAlchemy because the
       column type is JSONB – ``json.dumps(score)`` before would store a
       JSON *string* inside JSONB and break every ``isinstance(score, dict)``
       downstream;  that bug is explicitly documented here to prevent regressions.
    5. Return ``(average_score, answer_text, events)`` — the average is
       consumed by the run-iteration wrapper for multi-turn session history
       and final overall score.

    Logging strategy: DEBUG logs only for per-case success (INFO-level would
    blow up at 1000+ case runs) and a full exception trace with structured
    context on any failure.  No logs sit inside per-evaluator loops.
    """
    case_id = case["agent_evaluation_case_id"]
    # Mark the row RUNNING BEFORE the call so a concurrent worker sweep never
    # claims the same case twice (see the scheduler's "pending only" filter).
    update_agent_evaluation_case_result(
        agent_evaluation_case_id=case_id,
        tenant_id=tenant_id,
        status=EvalCaseStatus.RUNNING,
        updated_by=user_id,
    )
    inputs = case["inputs"] or {}
    query = inputs.get("query", "")
    label = case.get("label") or {}
    expected_answer = label.get("answer", "") or ""

    try:
        # _evaluate_query is async so each case thread owns a private event
        # loop.  This avoids blocking the whole worker pool on one long agent
        # run, and keeps per-case errors isolated.
        answer_text, events, score, reason = asyncio.run(
            _evaluate_query(
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                agent_version_no=agent_version_no,
                query=query,
                judge_model_id=judge_model_id,
                adapter=adapter,
                evaluators=evaluators,
                judge_system_prompt=judge_system_prompt,
                language=run.get("language", "zh"),
                context_window=context_window,
                history=history if history else None,
                expected=expected_answer,
            )
        )
        predict = {"answer": answer_text}
        # Threshold map: build from the per-run evaluator cache.  Values are
        # floats;  non-numeric / blank entries are skipped so legacy evaluator
        # rows with null thresholds fall through to the global DEFAULT inside
        # _is_all_pass.
        thresholds = {
            str(ev["name"]): float(ev.get("pass_threshold", DEFAULT_PASS_THRESHOLD))
            for ev in evaluators.values()
            if isinstance(ev, dict) and ev.get("name")
        }

        # CRITICAL: do NOT json.dumps(score).  agent_evaluation_case_t.score
        # is JSONB and SQLAlchemy serialises Python dicts for us.  Pre-
        # serialising would create a JSON-string-inside-JSONB double-wrap that
        # every reader has to repair through ``_coerce_score_dict``.
        is_dict_score = isinstance(score, dict)
        pass_status = EvalPassStatus.FAIL
        if is_dict_score:
            if _is_all_pass(score, thresholds):
                pass_status = EvalPassStatus.PASS
        else:
            # Scalar legacy path (semantic_fallback returns score == 1 on
            # success).  Non-dict scalar 1 → PASS; anything else → FAIL.
            if score == 1:
                pass_status = EvalPassStatus.PASS
        update_agent_evaluation_case_result(
            agent_evaluation_case_id=case_id,
            tenant_id=tenant_id,
            status=EvalCaseStatus.COMPLETED,
            predict=predict,
            score=score,
            pass_status=pass_status,
            reason=str(json.dumps(reason) if isinstance(reason, dict) else reason),
            updated_by=user_id,
        )
        if is_dict_score:
            vals = [v for v in score.values() if isinstance(v, (int, float))]
            avg = sum(vals) / len(vals) if vals else 0.0
        else:
            avg = float(score)
        logger.debug(
            "_execute_single_case: case_id=%s run_id=%s agent_id=%s judge_model=%s "
            "score_avg=%s pass_status=%s evaluator_count=%s answer_len=%s",
            case_id,
            run.get("agent_evaluation_id"),
            agent_id,
            judge_model_id,
            avg,
            pass_status,
            len(thresholds),
            len(answer_text or ""),
        )
        return avg, answer_text, events

    except Exception as exc:
        # Structured error log so we can group by tenant / run / case in
        # log observability dashboards.  The traceback is kept via
        # logger.exception for the stack, and the user-facing case error
        # column stores a friendly non-stack version.
        logger.exception(
            "Evaluation case failed run_id=%s case_id=%s tenant=%s agent_id=%s judge_model=%s: %r",
            run.get("agent_evaluation_id"),
            case_id,
            tenant_id,
            agent_id,
            judge_model_id,
            exc,
        )
        friendly_msg = _generate_friendly_error_message(
            exc, str(exc), model_id=judge_model_id, tenant_id=tenant_id
        )
        update_agent_evaluation_case_result(
            agent_evaluation_case_id=case_id,
            tenant_id=tenant_id,
            status=EvalCaseStatus.FAILED,
            pass_status=EvalPassStatus.FAIL,
            error_message=friendly_msg,
            updated_by=user_id,
        )
        return 0.0, "", []


def _setup_no_set_and_execute(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    judge_model_id: int,
    evaluator_ids: list,
    field_mappings: dict,
    query_count: int,
    language: str,
    agent_evaluation_id: int,
):
    """Background task: generate test queries via LLM, create virtual set, then execute."""
    try:
        # Resolve a suitable LLM model for query generation
        gen_model_id = judge_model_id
        try:
            with get_db_session() as gs:
                models = (
                    gs.query(ModelRecord)
                    .filter(ModelRecord.tenant_id == tenant_id)
                    .all()
                )
                judge_is_llm = any(
                    m.model_id == judge_model_id
                    and getattr(m, "model_type", "") == "llm"
                    for m in models
                )
                if not judge_is_llm:
                    llm_models = sorted(
                        [m for m in models if getattr(m, "model_type", "") == "llm"],
                        key=lambda x: x.model_id or 0,
                        reverse=True,
                    )
                    if llm_models:
                        gen_model_id = llm_models[0].model_id
        except Exception as exc:
            logger.warning("Model fallback check failed: %s", exc)

        # AI generates test queries
        queries = _generate_test_queries(
            agent_id=agent_id,
            tenant_id=tenant_id,
            model_id=gen_model_id,
            query_count=query_count,
            language=language,
        )

        # Create virtual evaluation set
        timestamp = datetime.now().strftime("%m-%d %H:%M")
        set_name = f"[No-Set] {timestamp}-{uuid.uuid4().hex[:4]}"
        set_meta = create_evaluation_set(
            tenant_id=tenant_id,
            name=set_name,
            description=None,
            source_filename="__no_set_virtual__",
            created_by=user_id,
        )
        evaluation_set_id = set_meta["evaluation_set_id"]

        # Insert cases
        cases = [
            {"inputs": {"query": q.strip()}, "label": {"answer": ""}, "order_no": i}
            for i, q in enumerate(queries)
        ]
        insert_evaluation_set_cases(
            tenant_id=tenant_id,
            evaluation_set_id=evaluation_set_id,
            cases=cases,
            created_by=user_id,
        )
        update_evaluation_set_case_count(
            evaluation_set_id, len(cases), updated_by=user_id
        )
        set_cases = get_evaluation_set_cases_all(
            evaluation_set_id=evaluation_set_id, tenant_id=tenant_id
        )

        # Create cases in agent_evaluation_case table
        create_agent_evaluation_cases(
            tenant_id=tenant_id,
            agent_evaluation_id=agent_evaluation_id,
            set_cases=set_cases,
            created_by=user_id,
        )

        # Update the run with correct evaluation_set_id and total
        with get_db_session() as session:
            session.query(AgentEvaluation).filter(
                AgentEvaluation.agent_evaluation_id == agent_evaluation_id,
                AgentEvaluation.tenant_id == tenant_id,
            ).update(
                {
                    "evaluation_set_id": evaluation_set_id,
                    "progress_total": len(cases),
                    "status": EvalRunStatus.RUNNING,
                },
                synchronize_session=False,
            )
            session.commit()

        # Execute
        execute_agent_evaluation_run(
            tenant_id, user_id, agent_evaluation_id, judge_model_id
        )
    except Exception:
        logger.exception("No-set setup failed for run %d", agent_evaluation_id)
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.FAILED,
            error_message="Failed to generate test queries",
            updated_by=user_id,
        )


def execute_agent_evaluation_run(
    tenant_id: str,
    user_id: str,
    agent_evaluation_id: int,
    judge_model_id: Optional[int] = None,
):
    try:
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.RUNNING,
            updated_by=user_id,
        )
        run = get_agent_evaluation(
            agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
        )
        agent_id = int(run["agent_id"])
        agent_version_no = int(run["agent_version_no"])
        if judge_model_id is None:
            judge_model_id = run.get("judge_model_id")
        if judge_model_id is None:
            raise AppException(ErrorCode.AGENT_EVALUATION_JUDGE_MODEL_REQUIRED)
        judge_model_id = int(judge_model_id)

        if JiuwenSDKAdapter is None:
            raise JiuwenSDKUnavailableError("Jiuwen SDK adapter is unavailable.")
        adapter = JiuwenSDKAdapter(model_id=judge_model_id, tenant_id=tenant_id)

        # Preload evaluators and judge template (loaded once, reused for all cases)
        evaluators: Dict[int, Dict[str, Any]] = {}
        raw_config = run.get("evaluator_config")
        if isinstance(raw_config, dict) and raw_config.get("evaluator_ids"):
            for eid in raw_config["evaluator_ids"]:
                ev = get_evaluator(eid, tenant_id)
                if ev and ev.get("status") == "PUBLISHED":
                    evaluators[eid] = ev
        judge_system_prompt = get_prompt_template(
            "evaluation_judge_system", run.get("language", "zh")
        )["SYSTEM_PROMPT"]

        # Resolve judge model context window once (used for runtime_events trimming)
        context_window = 4096
        if judge_model_id:
            with get_db_session() as s:
                model_row = (
                    s.query(ModelRecord)
                    .filter(
                        ModelRecord.model_id == judge_model_id,
                        ModelRecord.tenant_id == tenant_id,
                    )
                    .first()
                )
                if model_row and getattr(model_row, "context_window_tokens", None):
                    context_window = model_row.context_window_tokens

        # Load ALL cases first, then group by session_id for multi-turn support.
        # This avoids splitting sessions across pages (which would reset history).
        all_cases: List[dict] = []
        offset = 0
        while True:
            batch = list_agent_evaluation_cases(
                agent_evaluation_id=agent_evaluation_id,
                tenant_id=tenant_id,
                limit=200,
                offset=offset,
            )
            page_items = (
                batch.get("items", []) if isinstance(batch, dict) else (batch or [])
            )
            if not page_items:
                break
            all_cases.extend(page_items)
            offset += len(page_items)

        # Group by session_id
        sessions: Dict[str, List[dict]] = defaultdict(list)
        for c in all_cases:
            sid = c.get("session_id") or f"__single__{c['agent_evaluation_case_id']}"
            sessions[sid].append(c)

        scores: List[float] = []
        done_count = 0

        for sid, session_cases in sorted(sessions.items()):
            if len(session_cases) > MAX_TURNS_PER_SESSION:
                logger.warning(
                    "Session %s has %d turns, exceeding max %d — truncating",
                    sid,
                    len(session_cases),
                    MAX_TURNS_PER_SESSION,
                )
                session_cases = session_cases[:MAX_TURNS_PER_SESSION]
            session_cases.sort(key=lambda c: c.get("turn_order", 0))
            history: List[Dict[str, Any]] = []
            for c in session_cases:
                case_score, answer_text, events = _execute_single_case(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    agent_version_no=agent_version_no,
                    case=c,
                    run=run,
                    judge_model_id=judge_model_id,
                    adapter=adapter,
                    evaluators=evaluators,
                    judge_system_prompt=judge_system_prompt,
                    context_window=context_window,
                    history=history if history else None,
                )
                scores.append(case_score)
                # Build conversation history for subsequent turns in this session
                inputs = c.get("inputs") or {}
                query = inputs.get("query", "")
                history.append({"role": "user", "content": query})
                history.append({"role": "assistant", "content": answer_text})
                done_count += 1
                update_agent_evaluation_status(
                    agent_evaluation_id=agent_evaluation_id,
                    tenant_id=tenant_id,
                    status=EvalRunStatus.RUNNING,
                    updated_by=user_id,
                    progress_done=done_count,
                )

        overall = float(mean(scores)) if scores else 0.0
        # pass_count here is a best-effort aggregate of per-case pass decisions
        # already written to the DB in _execute_single_case (which already uses
        # per-evaluator pass_threshold).  Using the per-case score average with
        # DEFAULT_PASS_THRESHOLD is consistent with run-level UI display while
        # not double-counting evaluators.
        pass_count = sum(1 for s in scores if s >= DEFAULT_PASS_THRESHOLD)
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.COMPLETED,
            updated_by=user_id,
            score_overall=overall,
            progress_done=done_count,
            pass_count=pass_count,
            fail_count=len(scores) - pass_count,
        )
    except Exception as exc:
        logger.exception("Evaluation run failed: %r", exc)
        friendly_msg = _generate_friendly_error_message(
            exc, str(exc), model_id=judge_model_id, tenant_id=tenant_id
        )
        update_agent_evaluation_status(
            agent_evaluation_id=agent_evaluation_id,
            tenant_id=tenant_id,
            status=EvalRunStatus.FAILED,
            updated_by=user_id,
            error_message=friendly_msg,
        )


# ══════════════════════════════════════════════════════════════════════
# Analysis report
# ══════════════════════════════════════════════════════════════════════


def generate_analysis_report_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    language: str = "zh",
    force: bool = False,
) -> Dict[str, Any]:
    """Generate (or re-generate) the LLM root-cause analysis report.

    Output is a structured dict stored in ``agent_evaluation_t.analysis_report``
    (JSONB) so the detail page can render it instantly on a second visit.
    ``force=True`` skips the cached copy and re-runs the full LLM call; it
    is used when a user clicks "Regenerate report" after annotating cases
    or adjusting evaluator thresholds.

    Pipeline
    --------
    1. Cache gate: return immediately if ``analysis_report`` exists and the
       caller did not request regeneration.
    2. Readiness gate: the run must be ``COMPLETED`` or ``FAILED`` — mid-run
       stats are inconsistent and trigger confusing partial analyses.
    3. Fetch all cases (unpaginated, capped at 5000) and load evaluator
       metadata **once** into a ``{name: pass_threshold}`` map — this is the
       same map used by ``_execute_single_case`` so the analysis's "why did
       this fail" logic matches the pass/fail decision recorded in the DB.
    4. Walk every FAIL case and build compacted failure payloads.  For each
       case we compute:
       * ``low_scores`` — evaluator scores STRICTLY below the per-evaluator
         threshold (the real reason it was marked FAIL).
       * ``borderline_scores`` — scores within 0.1 of the threshold so the
         LLM can highlight "almost passed" evaluators as secondary issues.
       * ``expected`` vs ``actual`` side-by-side answers (4000 char cap each
         to stay inside LLM context windows).
       Historically this step filtered on "any evaluator < 0.5" which
       silently dropped failures where the evaluator had a custom threshold
       (e.g. threshold 0.8 and score 0.6);  the new code uses pass_status as
       the source of truth and only uses thresholds *inside* each case to
       surface the weakest evaluator names.
    5. Render the final LLM prompt: a stats summary + per-case failure
       details clamped to ``MAX_FAILURE_EXAMPLES`` entries (SDK constant,
       typically ~20).  Every prompt starts with a compact one-line stats
       block and the evaluator threshold map so the LLM knows the
       pass/fail rules for every score column.
    6. Call LLM, parse JSON, persist the cache row, return structured dict.

    Logging: one INFO log per generation (with context keys) and no per-case
    logs.  If the LLM returns non-JSON the error is logged at WARNING with
    the full prompt size so operators can estimate cost.
    """
    run = get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )
    if not run:
        raise AppException(
            ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Agent evaluation not found"
        )

    # ── Cache gate ───────────────────────────────────────────────────────
    # ``analysis_report`` is a JSONB column; a non-empty dict means the
    # report was already generated and persisted during a previous call.
    cached = run.get("analysis_report")
    if cached and not force:
        return cached

    # ── Readiness gate ───────────────────────────────────────────────────
    # PENDING / RUNNING produce incomplete sample sets — refuse until done.
    if run["status"] not in (EvalRunStatus.COMPLETED, EvalRunStatus.FAILED):
        raise AppException(ErrorCode.AGENT_EVALUATION_ANALYSIS_NOT_READY)

    # ── Load corpus + evaluator metadata ─────────────────────────────────
    cases = list_agent_evaluation_cases(
        agent_evaluation_id=agent_evaluation_id,
        tenant_id=tenant_id,
        limit=5000,
        offset=0,
    )
    cases = cases.get("items", []) if isinstance(cases, dict) else (cases or [])

    thresholds: Dict[str, float] = {}
    raw_config = run.get("evaluator_config") or {}
    if isinstance(raw_config, dict) and isinstance(
        raw_config.get("evaluator_ids"), list
    ):
        for eid in raw_config["evaluator_ids"]:
            try:
                ev = get_evaluator(int(eid), tenant_id)
            except (ValueError, TypeError):
                ev = None
            if isinstance(ev, dict) and ev.get("name"):
                thresholds[str(ev["name"])] = float(
                    ev.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
                )

    # ── Basic run stats ──────────────────────────────────────────────────
    total = len(cases)
    passed = sum(1 for c in cases if c.get("pass_status") == EvalPassStatus.PASS)
    failed_cases = [c for c in cases if c.get("pass_status") == EvalPassStatus.FAIL]

    # ── Collect failure details for the LLM prompt ──────────────────────
    failure_examples: List[Dict[str, Any]] = []
    for c in failed_cases:
        # Use coerce helpers so historical rows (JSON stored inside a JSONB
        # string) are decoded consistently with new rows.
        score_dict = _coerce_score_dict(c.get("score"))
        reason_dict = _coerce_reason(c.get("reason"))

        predict_answer = ""
        predict = c.get("predict") or {}
        if isinstance(predict, dict):
            predict_answer = str(predict.get("answer") or "")

        query_text = ""
        inputs = c.get("inputs") or {}
        if isinstance(inputs, dict):
            query_text = str(inputs.get("query") or "")

        # Compact score: single-evaluator score → scalar, multi-evaluator → keep dict
        if len(score_dict) == 1:
            _score_val = next(iter(score_dict.values()))
        else:
            _score_val = score_dict

        # Compact reason: multi-evaluator dict → joined string, scalar → keep string
        if isinstance(reason_dict, dict) and reason_dict:
            _reason_str = " | ".join(f"{k}: {v}" for k, v in reason_dict.items())
        else:
            _reason_str = str(reason_dict or "")

        failure_examples.append(
            {
                "case_id": c.get("agent_evaluation_case_id"),
                "query": query_text,
                "answer": predict_answer[:4000],
                "score": _score_val,
                "reason": _reason_str[:4000],
            }
        )

    # ── Render prompt blocks ─────────────────────────────────────────────
    stats_block = f"Total cases: {total}, Passed: {passed}, Failed: {total - passed}, Pass rate: {passed}/{total}"
    if thresholds:
        stats_block += (
            f"\nEvaluator pass thresholds: {json.dumps(thresholds, ensure_ascii=False)}"
        )

    failures_block = ""
    if failure_examples:
        for i, ex in enumerate(failure_examples[:MAX_FAILURE_EXAMPLES]):
            # Compact newlines out of the user query so each case fits on one
            # readable line in the LLM prompt window (keeps token counts low
            # and improves model parseability).
            q = (ex["query"] or "(empty)").replace("\n", " ")[:1000]
            failures_block += f"\nCase {i + 1}: Q={q}\n"
            failures_block += f"Score: {json.dumps(ex['score'], ensure_ascii=False)}\n"
            if ex["reason"]:
                failures_block += f"Reason: {ex['reason']}\n"
            if ex["answer"]:
                failures_block += f"Answer: {ex['answer']}\n"
    else:
        failures_block = "\nNo failed cases."

    user_prompt = f"{stats_block}\n\nFailed case details (up to {MAX_FAILURE_EXAMPLES} examples):{failures_block}"
    prompt_chars = len(user_prompt)

    # ── LLM call + cache write ───────────────────────────────────────────
    try:
        template = get_prompt_template("evaluation_analyze_report", language)
        response = call_llm_for_system_prompt(
            model_id=int(run["judge_model_id"]),
            user_prompt=user_prompt,
            system_prompt=template["SYSTEM_PROMPT"],
            tenant_id=tenant_id,
        )
        data = json.loads(response) if isinstance(response, str) else response
        if not isinstance(data, dict):
            raise AppException(ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED)
    except Exception as exc:
        # WARNING so ops can see the LLM failure independently of the stack
        # trace.  prompt_chars is an approximation of token consumption
        # (model-dependent; real tokens are roughly prompt_chars/4 for ASCII).
        logger.warning(
            "Analysis generation FAILED run_id=%s tenant=%s judge_model=%s force=%s prompt_chars=%s failure=%r",
            agent_evaluation_id,
            tenant_id,
            run.get("judge_model_id"),
            force,
            prompt_chars,
            exc,
        )
        logger.exception("Analysis generation stack trace: %s", exc)
        raise AppException(ErrorCode.AGENT_EVALUATION_ANALYSIS_FAILED)

    update_agent_evaluation_analysis_report(agent_evaluation_id, tenant_id, data)
    # Single summary INFO log per regeneration.
    evaluator_count_in_thresholds = len(thresholds)
    logger.info(
        "generate_analysis_report_impl: run_id=%s tenant=%s judge_model=%s force=%s "
        "total_cases=%s passed=%s failed_cases=%s failure_examples_sent=%s "
        "evaluator_thresholds=%s prompt_chars=%s cached=%s",
        agent_evaluation_id,
        tenant_id,
        run.get("judge_model_id"),
        force,
        total,
        passed,
        len(failed_cases),
        min(len(failure_examples), MAX_FAILURE_EXAMPLES),
        evaluator_count_in_thresholds,
        prompt_chars,
        bool(cached and not force),
    )
    return data


# ══════════════════════════════════════════════════════════════════════
# Query helpers
# ══════════════════════════════════════════════════════════════════════


def get_agent_evaluation_run_impl(
    agent_evaluation_id: int, tenant_id: str
) -> Dict[str, Any]:
    return get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )


def list_agent_evaluations_by_agent_impl(
    agent_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    return list_agent_evaluations_by_agent(
        agent_id=agent_id, tenant_id=tenant_id, limit=limit, offset=offset
    )


def list_agent_evaluation_cases_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str | None = None,
    sort_order: str = "asc",
    pass_filter: str | None = None,
    anno_schema_ids: list[int] | None = None,
    anno_values: list[str] | None = None,
) -> Dict[str, Any]:
    return list_agent_evaluation_cases(
        agent_evaluation_id=agent_evaluation_id,
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        pass_filter=pass_filter,
        anno_schema_ids=anno_schema_ids,
        anno_values=anno_values,
    )


def get_evaluation_stats_impl(
    agent_evaluation_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Compute chart-ready aggregates for an evaluation run.

    The frontend detail page renders **three** distinct widgets from the
    returned payload:

    1. **Per-evaluator summary table / polar chart** — ``per_evaluator``
       list, each entry carrying ``{name, avg, count, min, max}``.  ``avg``
       is the arithmetic mean across ALL cases (including empty/missing
       values) so averages are comparable between evaluators with sparse
       rows.
    2. **Histogram bar chart** — five fixed buckets (0.0–0.2 → 0.8–1.0).
       Bucket index is ``min(4, int(value * 5))``; clamping to index 4 is
       required because some evaluators emit 1.0 exactly (1.0 * 5 = 5 →
       would overflow the 5-slot list).
    3. **Pass/fail counters** — a running tally on the full case list,
       used for the hero card and summary section.

    Input is the full case corpus via ``get_evaluation_case_scores``
    (unpaginated, but stripped to only ``pass_status / score / reason``
    columns so payload stays tight).  ``_coerce_score_dict`` repairs
    historical legacy rows where the value was double-wrapped as a JSON
    string nested in a JSONB column.

    No per-row logging; a single INFO summary is emitted after aggregation
    so operators can reconcile dashboards with DB state.
    """
    case_scores = get_evaluation_case_scores(
        agent_evaluation_id=agent_evaluation_id,
        tenant_id=tenant_id,
    )

    if not case_scores:
        return {
            "per_evaluator": [],
            "histogram": [],
            "pass_count": 0,
            "fail_count": 0,
            "total": 0,
        }

    eval_scores: dict[str, list[float]] = defaultdict(list)
    # Five 0.2-wide buckets: indexes map directly to the five coloured
    # slots in the detail page (red → orange → yellow → light-green → green).
    histogram_buckets = [0, 0, 0, 0, 0]
    pass_count = 0
    fail_count = 0
    legacy_coerce_count = 0

    for cs in case_scores:
        if cs["pass_status"] == EvalPassStatus.PASS:
            pass_count += 1
        elif cs["pass_status"] == EvalPassStatus.FAIL:
            fail_count += 1

        # Legacy-compatible coerce: if the score column actually holds a
        # JSON string, decode it into a dict and increment the coerce
        # counter so we can track cleanup progress on older tenants.
        raw = cs.get("score")
        score_dict_before = None
        if isinstance(raw, str):
            score_dict_before = raw
        score_dict = _coerce_score_dict(raw)
        if score_dict_before is not None:
            legacy_coerce_count += 1

        for name, v in score_dict.items():
            eval_scores[name].append(v)
            # bucket = floor(value * 5), saturate at bucket index 4.
            # Scores > 1.0 (from custom ranges that are NOT yet normalised
            # in the DB layer) still bucket to the top-green slot so the
            # page never displays negative/overflow counts.
            bucket_idx = min(4, max(0, int(v * 5)))
            histogram_buckets[bucket_idx] += 1

    per_evaluator = []
    for name, scores in sorted(eval_scores.items()):
        avg = sum(scores) / len(scores) if scores else 0.0
        per_evaluator.append(
            {
                "name": name,
                "avg": round(avg, 4),
                "count": len(scores),
                "min": round(min(scores), 4),
                "max": round(max(scores), 4),
            }
        )

    histogram = [
        {"name": "0.0-0.2", "count": histogram_buckets[0], "fill": "#ff4d4f"},
        {"name": "0.2-0.4", "count": histogram_buckets[1], "fill": "#ff7a45"},
        {"name": "0.4-0.6", "count": histogram_buckets[2], "fill": "#faad14"},
        {"name": "0.6-0.8", "count": histogram_buckets[3], "fill": "#a0d911"},
        {"name": "0.8-1.0", "count": histogram_buckets[4], "fill": "#52c41a"},
    ]
    total = len(case_scores)
    logger.info(
        "get_evaluation_stats_impl: run_id=%s tenant=%s total_cases=%s "
        "pass_count=%s fail_count=%s evaluator_count=%s legacy_coerced=%s "
        "histogram_buckets=%s",
        agent_evaluation_id,
        tenant_id,
        total,
        pass_count,
        fail_count,
        len(per_evaluator),
        legacy_coerce_count,
        histogram_buckets,
    )
    return {
        "per_evaluator": per_evaluator,
        "histogram": histogram,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "total": total,
    }


def delete_agent_evaluation_run_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    user_id: str,
) -> None:
    run = get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )
    if run.get("created_by") != user_id:
        raise AppException(ErrorCode.AGENT_EVALUATION_ONLY_CREATOR_CAN_DELETE)

    evaluator_config_raw = run.get("evaluator_config")
    if isinstance(evaluator_config_raw, dict) and evaluator_config_raw.get(
        "no_set_mode"
    ):
        try:
            from database.evaluation_set_db import hard_delete_evaluation_set

            hard_delete_evaluation_set(run["evaluation_set_id"], tenant_id)
        except (OSError, ValueError) as exc:
            logger.warning(
                "Failed to clean up virtual evaluation set %d for run %d: %s",
                run["evaluation_set_id"],
                agent_evaluation_id,
                exc,
            )
    hard_delete_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )


async def trial_run_evaluator_impl(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    query: str,
    judge_model_id: int,
    evaluator_ids: Optional[list] = None,
    field_mappings: Optional[dict] = None,
) -> dict:
    # Preload evaluators
    evaluators: Dict[int, Dict[str, Any]] = {}
    if evaluator_ids:
        for eid in evaluator_ids:
            ev = get_evaluator(eid, tenant_id)
            if ev and ev.get("status") == "PUBLISHED":
                evaluators[eid] = ev
    judge_system_prompt = get_prompt_template("evaluation_judge_system", "zh")[
        "SYSTEM_PROMPT"
    ]

    if JiuwenSDKAdapter is None:
        raise JiuwenSDKUnavailableError("Jiuwen SDK adapter is unavailable")
    adapter = JiuwenSDKAdapter(model_id=judge_model_id, tenant_id=tenant_id)

    answer_text, runtime_events, score, reason = await _evaluate_query(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        agent_version_no=agent_version_no,
        query=query,
        judge_model_id=judge_model_id,
        adapter=adapter,
        evaluators=evaluators,
        judge_system_prompt=judge_system_prompt,
        language="zh",
    )
    return {"query": query, "answer": answer_text, "scores": score, "reasons": reason}
