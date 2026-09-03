import ast
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
from typing import Any

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
from database.db_models import ModelRecord
from database.evaluation_set_db import (
    get_evaluation_set_cases_all,
    materialize_virtual_evaluation_set_for_run,
)
from database.evaluator_db import get_evaluator
from management.services.agent.service import prepare_agent_run
from services.evaluation_set_service import resolve_latest_published_version_no
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import get_prompt_template
from utils.thread_utils import pool


_QUERY_FORMAT_ERR_MSG = "AI returned invalid format for test queries"

logger = logging.getLogger(__name__)

# Loaded lazily when an evaluation case starts.  Several pure-logic tests
# intentionally stub the SDK dependency graph and do not provide the runtime
# agent manager package.
agent_run_manager = None


def _dispatch_agent_evaluation_run(
    agent_evaluation_id: int,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Lazily import the config-to-runtime proxy to keep service imports light."""
    from services.runtime_proxy_service import dispatch_agent_evaluation_run

    return dispatch_agent_evaluation_run(
        agent_evaluation_id=agent_evaluation_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )


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


def _scan_evaluator_introspection(code: str) -> list[str]:
    """AST scan rejecting dunder attribute/name access used by sandbox escapes.

    The whitelisted-builtins exec (see ``ALLOWED_BUILTINS``) cannot import
    modules or reference ``open`` directly, but a whitelisted object (``json``,
    ``str``, ``Exception``, ...) is still reachable; every classic escape chain
    starts from a double-underscore attribute or name::

        json.JSONDecoder.__init__.__globals__['__builtins__']
        ().__class__.__base__.__subclasses__()

    Rejecting ``__``-prefixed attributes/names statically closes those chains
    while ordinary pure-python evaluators (which never touch dunders) pass.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            violations.append(f"dunder attribute access .{node.attr}")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            violations.append(f"dunder name {node.id!r}")
    return violations


# Filename shown in syntax errors / tracebacks for evaluator code. Kept in one
# constant so SonarCloud S1192 does not flag the literal as duplicated.
_EVALUATOR_FILENAME = "<evaluator>"


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
        compile(code, _EVALUATOR_FILENAME, "exec")
    except SyntaxError as e:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            f"Code syntax error at line {e.lineno}: {e.msg}",
        )

    # Stage 2: static AST scan for forbidden operations — runs BEFORE any
    # code executes so we never even sandbox-compile a dangerous AST.
    # ``_scan_shell_calls`` blocks literal os./subprocess. shell calls;
    # ``_scan_evaluator_introspection`` additionally rejects ``__``-prefixed
    # attribute/name access, closing object-introspection sandbox escapes.
    violations = _scan_shell_calls(code) + _scan_evaluator_introspection(code)
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
    #   2. _scan_shell_calls() + _scan_evaluator_introspection() AST scans
    #      (stage 2) — shell primitives and any ``__``-prefixed attribute/name
    #      (object-introspection escapes) are rejected statically before ANY
    #      code runs.
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
        # Defence-in-depth (compile syntax check, AST shell-call scan, dunder
        # introspection scan, ALLOWED_BUILTINS whitelist, evaluate() signature
        # check) is applied BEFORE the evaluator reaches this call — see
        # docstring.
        # Compile the source to a code object first so ``exec`` never receives
        # the raw, unvalidated user string directly (the same pure-syntax gate
        # as stage 1); runtime execution stays inside the ALLOWED_BUILTINS
        # sandbox.
        exec(  # nosec B102  # NOSONAR
            compile(code, _EVALUATOR_FILENAME, "exec"),
            {"__builtins__": ALLOWED_BUILTINS, "json": json},
            local_vars,
        )
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
    model_id: int | None = None,
    tenant_id: str | None = None,
    language: str = "zh",
) -> str:
    if not model_id or not _is_llm_related_error(exc):
        return default_msg
    try:
        template = get_prompt_template("evaluation_error_explain", language)
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
    tenant_id: str, user_id: str, agent_evaluation_id: int, language: str = "zh"
):
    def callback(future):
        exc = future.exception()
        if exc is not None:
            logger.exception(
                "Background evaluation run failed (id=%s): %r", agent_evaluation_id, exc
            )
            friendly_msg = _generate_friendly_error_message(
                exc, str(exc), language=language
            )
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
    history: list[dict[str, Any]] | None = None,
    conversation_id: int | None = None,
) -> tuple[str, list[dict]]:
    """Run agent once; return (final_answer_text, [all_observer_events])."""
    run_conversation_id = conversation_id if conversation_id is not None else 0
    agent_request = AgentRequest(
        query=query,
        conversation_id=run_conversation_id,
        history=history,
        minio_files=None,
        agent_id=agent_id,
        version_no=version_no,
        is_debug=True,
    )
    agent_run_info = None
    terminal_status = "failed"
    try:
        run_manager = agent_run_manager
        if run_manager is None:
            from agents.agent_run_manager import agent_run_manager as run_manager

        agent_run_info, _memory_context = await prepare_agent_run(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            allow_memory_search=False,
        )
        final_answer_parts: list[str] = []
        runtime_events: list[dict] = []
        async for chunk in agent_run(agent_run_info):
            try:
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
                data = json.loads(msg)
                if isinstance(data, dict):
                    runtime_events.append(data)
            except Exception:
                logger.debug("Failed to parse straggler observer message", exc_info=True)
        terminal_status = "completed"
        return "".join(final_answer_parts).strip(), runtime_events
    finally:
        if agent_run_info is not None:
            run_manager.unregister_agent_run(
                run_conversation_id,
                user_id,
                status=terminal_status,
                agent_run_info=agent_run_info,
            )


def _evaluation_conversation_id(agent_evaluation_id: int, case_id: int) -> int:
    """Return a stable, evaluation-only conversation key for run management."""
    # Evaluation runs do not represent user conversations.  A reserved
    # negative integer keeps each case isolated while preserving the existing
    # integer AgentRequest contract.
    return -((int(agent_evaluation_id) << 64) | int(case_id))


# ══════════════════════════════════════════════════════════════════════
# Scoring
# ══════════════════════════════════════════════════════════════════════


def _is_all_pass(
    scores: dict,
    thresholds: dict[str, float] | None = None,
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
    runtime_events: list[dict], actual: str, max_tokens: int = 4096
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
    steps = _group_events_by_step(runtime_events)
    actual_section = _truncate_actual_answer(actual)

    STATIC_OVERHEAD_EST = 200
    budget = max_tokens - STATIC_OVERHEAD_EST
    total_steps = len(steps)
    per_step = max(budget // total_steps, 15) if total_steps else budget
    remaining = budget

    step_outputs: list[str] = []
    for step_idx, step_events in enumerate(steps):
        available = min(per_step, remaining)
        if available <= 0:
            break
        remaining -= available
        step_text = _format_step_text(step_events, available)
        if step_text.strip():
            step_outputs.append(f"Step {step_idx + 1}:\n{step_text}")

    parts = ["## Agent Execution Log"]
    parts.extend(step_outputs)
    parts.append(_format_stats_summary(stats))
    parts.append(f"\n─ Final Answer ─\n{actual_section}")
    return "\n".join(parts)


def _group_events_by_step(runtime_events: list[dict]) -> list[list[dict]]:
    """Split runtime events into per-step groups on ``step_count`` boundaries."""
    steps: list[list[dict]] = []
    current_step: list[dict] = []
    for e in runtime_events:
        if e.get("type") == "step_count" and current_step:
            steps.append(current_step)
            current_step = []
        current_step.append(e)
    if current_step:
        steps.append(current_step)
    return steps


def _truncate_actual_answer(
    actual: str, head: int = 120, tail: int = 200
) -> str:
    """Truncate the agent's final answer to a head+tail preview when too long."""
    actual_str = str(actual or "")
    if len(actual_str) <= head + tail:
        return actual_str
    return actual_str[:head] + "\n…\n" + actual_str[-tail:]


# Map of event type → (label prefix, is_trimmable_content).
# Tool events emit a fixed argument line first, then their content is trimmable.
# Final-answer / token-count events are skipped entirely.
_EVENT_LABELS: dict[str, str] = {
    "tool": "  → ",
    "kb": "  [KB] ",
    "log": "    ",
    "artifact": "  [Artifact] ",
    "file": "  [File created] ",
    "error": "  [ERROR] ",
}

# Event types whose ``content`` field is subject to per-step budget trimming.
# Maps raw event type → label key used in ``_EVENT_LABELS``.
_TRIMMABLE_TYPES: dict[str, str] = {
    "tool": "tool",
    "execution_logs": "log",
    "search_content": "kb",
    "skill_artifact": "artifact",
    "file_created": "file",
    "error": "error",
}

# Event types that are skipped entirely (no output line).
_SKIP_TYPES = frozenset({"step_count", "final_answer", "token_count"})


def _classify_step_event(e: dict) -> tuple[str, str, str] | None:
    """Classify one runtime event within a step.

    Returns ``(category, content_str, fixed_line)`` where:

      * ``category``   — label key (used for trimming); empty string when
                         the event has no trimmable content.
      * ``content_str``— the raw ``content`` text (may be empty).
      * ``fixed_line`` — a non-trimmable line to emit as-is (e.g. the tool
                         call signature); empty when the event only has
                         trimmable content.

    Returns ``None`` for events that should be skipped entirely
    (``step_count``, ``final_answer``, ``token_count``).
    """
    t = e.get("type", "")
    if t in _SKIP_TYPES:
        return None

    # Tool events emit a fixed argument line first, then their content is trimmable.
    if t == "tool":
        name = e.get("tool_name", "")
        args = e.get("tool_arguments") or {}
        arg_str = ", ".join(f"{k}={v}" for k, v in args.items())
        fixed_line = f"  → {name}({arg_str})"
        content = str(e.get("content") or "")
        cat = "tool" if content.strip() else ""
        return (cat, content, fixed_line)

    # All other trimmable event types: content-only, no fixed line.
    label_key = _TRIMMABLE_TYPES.get(t)
    if label_key is not None:
        content = str(e.get("content") or "")
        cat = label_key if content.strip() else ""
        return (cat, content, "") if cat else ("", content, "")

    # Fallback for any other event type with content.
    content = str(e.get("content") or "")
    return ("", content, "") if content.strip() else ("", "", "")


def _trim_content(raw: str, budget: int) -> str:
    """Trim ``raw`` to ``budget`` characters, keeping head 60% + tail 40%."""
    rlen = len(raw)
    if rlen <= budget or budget < 10:
        return raw
    head = budget * 60 // 100
    tail = budget - head
    # budget >= 10 is guaranteed here, so head >= 6 and tail >= 4 are always
    # positive — the dead `if head > 0` branch is intentionally omitted.
    return raw[:head] + "\n…\n" + raw[-tail:]


def _distribute_budget_and_trim(
    trimmable_events: list[tuple[str, dict]], available: int
) -> list[str]:
    """Distribute ``available`` chars across trimmable events and trim each.

    Unused budget from one event carries forward to the next.  Returns one
    labeled output line per input event.
    """
    count = len(trimmable_events)
    if count == 0:
        return []
    base_per_event = (available - count * 2) // count
    carry = 0
    results: list[str] = []
    for evt_type, evt in trimmable_events:
        event_budget = base_per_event + carry
        carry = 0
        raw = str(evt.get("content", ""))
        trimmed = _trim_content(raw, event_budget)
        label = _EVENT_LABELS.get(evt_type, "")
        results.append(f"{label}{trimmed}")
        saved = max(0, event_budget - len(trimmed))
        carry += saved
    return results


def _format_step_text(step_events: list[dict], available: int) -> str:
    """Format one step's events into a text block within the budget.

    Fixed lines (tool signatures) are emitted as-is; trimmable content
    fields share the step's character budget with carry-forward.
    """
    fixed_lines: list[str] = []
    trimmable_events: list[tuple[str, dict]] = []
    for e in step_events:
        classified = _classify_step_event(e)
        if classified is None:
            continue
        cat, content, fixed_line = classified
        if fixed_line:
            fixed_lines.append(fixed_line)
        if cat:
            trimmable_events.append((cat, e))
        elif content and not fixed_line:
            # Non-trimmable content with no fixed line — emit as-is.
            fixed_lines.append(content)

    trimmed_results = _distribute_budget_and_trim(trimmable_events, available)
    if not trimmed_results:
        return "\n".join(fixed_lines)

    # Rebuild step with fixed lines + trimmed content in correct position.
    step_lines: list[str] = []
    trim_idx = 0
    for fl in fixed_lines:
        if fl:
            step_lines.append(fl)
        elif trim_idx < len(trimmed_results):
            step_lines.append(trimmed_results[trim_idx])
            trim_idx += 1
    # Append any remaining trimmed results that didn't get a placeholder slot.
    step_lines.extend(trimmed_results[trim_idx:])
    return "\n".join(step_lines)


def _format_stats_summary(stats: dict) -> str:
    """Format the runtime stats block appended after the step log."""
    return (
        f"\n─ Stats ─\n"
        f"Steps: {stats['steps']} | Tool calls: {stats['tool_calls']} | "
        f"Output tokens: {stats['output_tokens']} | Errors: {stats['errors']}\n"
        f"Max steps reached: {stats['max_steps_reached']} | "
        f"Has final answer: {stats['has_final_answer']}"
    )


def _extract_token_count(evt: dict) -> int | None:
    """Extract ``total_output_tokens`` from a ``token_count`` runtime event.

    Returns ``None`` when the content cannot be parsed or the token field is
    absent.  The ``content`` field may arrive as a JSON string or a dict.
    """
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
            return None
    if isinstance(content, dict):
        tok = content.get("total_output_tokens")
        if tok is not None and isinstance(tok, (int, float)):
            return int(tok)
    return None


def _extract_runtime_stats(runtime_events: list[dict]) -> dict:
    stats: dict[str, Any] = {
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
            tok = _extract_token_count(evt)
            if tok is not None:
                stats["output_tokens"] = max(stats["output_tokens"], tok)
    return stats


def _format_conversation_history(
    conversation_history: list[dict[str, Any]] | None,
) -> str:
    """Format multi-turn conversation history as a prompt prefix.

    Returns an empty string when there is no history.
    """
    if not conversation_history:
        return ""
    lines = ["## Previous Conversation Turns"]
    for msg in conversation_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Agent: {content}")
    return "\n".join(lines) + "\n\n"


def _build_evaluator_prompt(
    ev: dict[str, Any],
    query: str,
    expected: str,
    actual: str,
    runtime_events: list[dict] | None,
    context_window: int,
    conversation_history: list[dict[str, Any]] | None,
) -> str:
    """Build the final user prompt for an LLM evaluator.

    The evaluator's own ``prompt`` is used verbatim (single-field; builtin
    prompts carry their own language instruction). Prepends multi-turn
    conversation history, then substitutes ``{{query}}``, ``{{expected}}``,
    ``{{actual}}`` and ``{{runtime_stats}}`` placeholders.
    """
    prompt = ev["prompt"]
    history = _format_conversation_history(conversation_history)
    if history:
        prompt = history + prompt
    prompt = prompt.replace("{{query}}", str(query))
    prompt = prompt.replace("{{expected}}", str(expected))
    prompt = prompt.replace("{{actual}}", str(actual))
    if runtime_events and "{{runtime_stats}}" in prompt:
        ctx = _format_runtime_context(
            runtime_events, str(actual), max_tokens=context_window
        )
        prompt = prompt.replace("{{runtime_stats}}", ctx)
    return prompt


def _call_one_llm_evaluator(
    eid: int,
    ev: dict[str, Any],
    judge_system_prompt: str,
    tenant_id: str,
    query: str,
    expected: str,
    actual: str,
    judge_model_id: int,
    runtime_events: list[dict] | None,
    context_window: int,
    conversation_history: list[dict[str, Any]] | None,
) -> tuple:
    """Call a single LLM evaluator — submitted to the thread pool.

    Returns ``(eid, name, score, reason)``.
    """
    prompt = _build_evaluator_prompt(
        ev, query, expected, actual,
        runtime_events, context_window, conversation_history,
    )
    response = call_llm_for_system_prompt(
        model_id=judge_model_id,
        user_prompt=prompt,
        system_prompt=judge_system_prompt,
        tenant_id=tenant_id,
    )
    # Defensive parsing: judge models occasionally return empty or non-JSON
    # content (e.g. all output inside <think> tags is filtered out). Treat
    # these as a 0-score evaluator result with an explicit reason instead of
    # letting json.loads blow up the whole case run.
    if not isinstance(response, str) or not response.strip():
        return eid, ev["name"], 0.0, "Judge model returned empty response"
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError) as exc:
        return eid, ev["name"], 0.0, f"Judge model returned invalid JSON: {exc}"
    if not isinstance(data, dict):
        return eid, ev["name"], 0.0, "Judge model response was not a JSON object"
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    return eid, ev["name"], score, str(data.get("reason", ""))


def _run_code_evaluators(
    code_evals: dict[int, dict[str, Any]],
    query: str,
    expected: str,
    actual: str,
    runtime_events: list[dict] | None,
) -> tuple[dict, dict]:
    """Run code-type evaluators serially (pure Python, no I/O).

    Each evaluator code snippet has already been validated at authoring
    time by ``validate_code_evaluator()`` (4-stage pipeline: compile syntax →
    AST shell-call scan → sandboxed trial exec → signature inspection).
    The same ``ALLOWED_BUILTINS`` whitelist is re-applied here for runtime
    parity with the authoring-validation environment.
    """
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for eid, ev in code_evals.items():
        name = ev["name"]
        try:
            local_vars = {}
            # Compile first so ``exec`` never receives the raw stored string
            # directly; authoring-time validation already gated the same source.
            exec(  # nosec B102  # NOSONAR
                compile(ev["code"], _EVALUATOR_FILENAME, "exec"),
                {"__builtins__": ALLOWED_BUILTINS, "json": json},
                local_vars,
            )
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
    return scores, reasons


def _collect_llm_results(
    futures: dict,
    llm_evals: dict[int, dict[str, Any]],
) -> tuple[dict, dict]:
    """Collect LLM evaluator results from completed futures.

    On per-future failure, records a zero score with the error message.
    """
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
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


def _score_with_evaluators(
    evaluators: dict[int, dict[str, Any]],
    judge_system_prompt: str,
    tenant_id: str,
    query: str,
    expected: str,
    actual: str,
    judge_model_id: int,
    runtime_events: list[dict] | None = None,
    context_window: int = 4096,
    conversation_history: list[dict[str, Any]] | None = None,
) -> tuple:
    """Score one case with all evaluators. Code evaluators run serially (fast);
    LLM evaluators run in parallel via ThreadPoolExecutor (I/O-bound)."""
    code_evals = {
        eid: ev for eid, ev in evaluators.items() if ev.get("evaluator_type") == "code"
    }
    llm_evals = {
        eid: ev for eid, ev in evaluators.items() if ev.get("evaluator_type") != "code"
    }

    scores, reasons = _run_code_evaluators(
        code_evals, query, expected, actual, runtime_events
    )

    if not llm_evals:
        return scores, reasons

    futures = {
        _LLM_EVAL_EXECUTOR.submit(
            _call_one_llm_evaluator,
            eid, ev, judge_system_prompt, tenant_id,
            query, expected, actual, judge_model_id,
            runtime_events, context_window, conversation_history,
        ): eid
        for eid, ev in llm_evals.items()
    }
    llm_scores, llm_reasons = _collect_llm_results(futures, llm_evals)
    scores.update(llm_scores)
    reasons.update(llm_reasons)
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


def _run_in_background(
    fn, *fn_args, tenant_id, user_id, agent_evaluation_id, language="zh"
):
    """Submit fn to the thread pool and attach a failure-cleanup callback."""
    future = pool.submit(fn, *fn_args)
    future.add_done_callback(
        _make_background_done_callback(
            tenant_id, user_id, agent_evaluation_id, language
        )
    )


def _validate_and_freeze_evaluators(
    evaluator_ids: list | None,
    tenant_id: str,
    field_mappings: dict | None,
    language: str,
) -> dict[str, Any] | None:
    """Validate evaluators and freeze their config into an immutable snapshot.

    Returns ``None`` when no evaluator_ids are provided.
    Raises ``AppException`` when evaluators exceed the count limit, are not
    found, or are not in PUBLISHED status.
    """
    if not evaluator_ids:
        return None
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
    return {
        "evaluator_ids": evaluator_ids,
        "field_mappings": field_mappings or {},
        "language": language,
    }


def _create_no_set_mode_run(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    judge_model_id: int,
    evaluator_ids: list | None,
    field_mappings: dict | None,
    query_count: int,
    language: str,
    evaluator_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create a placeholder evaluation run with no pre-built case set.

    AI query generation runs in the background via
    :func:`_setup_no_set_and_execute`.
    """
    if query_count < 1 or query_count > 50:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_COUNT_RANGE,
            "Query count must be between 1 and 50",
        )

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
        language=language,
    )
    return run


def create_agent_evaluation_run_impl(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    judge_model_id: int,
    evaluation_set_id: int | None = None,
    agent_version_no: int | None = None,
    evaluator_ids: list | None = None,
    field_mappings: dict | None = None,
    query_count: int = 10,
    language: str = "zh",
) -> dict[str, Any]:
    _check_run_limits(tenant_id)

    evaluator_config = _validate_and_freeze_evaluators(
        evaluator_ids, tenant_id, field_mappings, language
    )

    # Resolve the agent version once — both branches need it. Safe to hoist
    # before the set_id branch: resolve_* only reads agent_id/tenant_id and
    # surfaces a clearer error if the agent has no published version.
    if agent_version_no is None:
        agent_version_no = resolve_latest_published_version_no(
            agent_id=agent_id, tenant_id=tenant_id
        )

    if not evaluation_set_id:
        return _create_no_set_mode_run(
            tenant_id,
            user_id,
            agent_id,
            agent_version_no,
            judge_model_id,
            evaluator_ids,
            field_mappings,
            query_count,
            language,
            evaluator_config,
        )

    set_cases = get_evaluation_set_cases_all(
        evaluation_set_id=evaluation_set_id, tenant_id=tenant_id
    )
    if not set_cases:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_SET_EMPTY, "Evaluation set has no cases"
        )

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
        _dispatch_agent_evaluation_run,
        run["agent_evaluation_id"],
        user_id,
        tenant_id,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_evaluation_id=run["agent_evaluation_id"],
        language=language,
    )
    return run


def _build_agent_profile_parts(profile: dict) -> list:
    """Build the agent profile section for the query-generation prompt.

    Conditionally includes each populated profile field so empty fields
    don't pollute the prompt.
    """
    parts = [f"## Agent Profile\n- Name: {profile['name']}"]
    if profile["description"]:
        parts.append(f"- Description: {profile['description']}")
    if profile["duty_prompt"]:
        parts.append(f"- Duty: {profile['duty_prompt']}")
    if profile["constraint_prompt"]:
        parts.append(f"- Constraints: {profile['constraint_prompt']}")
    if profile["business_description"]:
        parts.append(f"- Business Context: {profile['business_description']}")
    return parts


def _extract_cases_from_markdown_fence(response: Any) -> list:
    """Extract a cases list from a markdown-fenced JSON string.

    The LLM occasionally wraps JSON in ```json ... ``` fences; this helper
    peels the fence and parses the inner JSON, raising the standard
    format-error if either step fails.
    """
    match = re.search(r"```(?:json)?\s*(\[.*?])\s*```", response, re.DOTALL)
    if not match:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
            _QUERY_FORMAT_ERR_MSG,
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
            _QUERY_FORMAT_ERR_MSG,
        ) from exc


def _parse_cases_from_llm_response(response: Any) -> list:
    """Parse the LLM response into a list of case dicts.

    Handles three response shapes:
    1. Already a list (passthrough)
    2. JSON string with embedded cases
    3. Markdown-fenced JSON string (e.g. ```json [...] ```)

    Raises ``AppException`` with ``AGENT_EVALUATION_QUERY_GENERATION_FORMAT``
    on any non-list / empty parse result.
    """
    try:
        cases: Any = json.loads(response) if isinstance(response, str) else response
    except json.JSONDecodeError:
        cases = _extract_cases_from_markdown_fence(response)
    if not isinstance(cases, list) or not cases:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_QUERY_GENERATION_FORMAT,
            _QUERY_FORMAT_ERR_MSG,
        )
    return cases


def _generate_test_queries(
    agent_id: int,
    tenant_id: str,
    model_id: int,
    query_count: int = 10,
    language: str = "zh",
) -> list[str]:
    """Generate test queries from agent config via LLM.

    Uses the same template as case generation; extracts only the query strings.
    """
    from utils.agent_profile_utils import fetch_agent_profile

    profile = fetch_agent_profile(agent_id, tenant_id)
    if not profile:
        raise AppException(
            ErrorCode.AGENT_EVALUATION_AGENT_NOT_FOUND, f"Agent not found: {agent_id}"
        )

    profile_parts = _build_agent_profile_parts(profile)
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

    cases = _parse_cases_from_llm_response(response)

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
    evaluators: dict[int, dict[str, Any]],
    judge_system_prompt: str,
    runtime_events: list[dict] | None = None,
    language: str = "zh",
    context_window: int = 4096,
    history: list[dict[str, Any]] | None = None,
    expected: str = "",
    conversation_id: int | None = None,
) -> tuple[str, list[dict] | None, dict, dict]:
    """Run agent + score with evaluators. Returns (answer, events, scores, reasons)."""
    answer_text, events = await _run_agent_to_final_answer(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        query=query,
        version_no=agent_version_no,
        history=history,
        conversation_id=conversation_id,
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


def _build_evaluator_thresholds(evaluators: dict) -> dict:
    """Build ``{name: pass_threshold}`` map from the per-run evaluator cache.

    Values are floats; non-numeric / blank entries are skipped so legacy
    evaluator rows with null thresholds fall through to the global DEFAULT
    inside ``_is_all_pass``.
    """
    return {
        str(ev["name"]): float(ev.get("pass_threshold", DEFAULT_PASS_THRESHOLD))
        for ev in evaluators.values()
        if isinstance(ev, dict) and ev.get("name")
    }


def _determine_case_pass_status(score: Any, thresholds: dict) -> str:
    """Map a per-case score to PASS / FAIL using the run's threshold map.

    Dict-score path delegates to ``_is_all_pass``; scalar legacy path
    (semantic_fallback returns score == 1 on success) treats scalar 1 as
    PASS; anything else → FAIL.
    """
    if not isinstance(score, dict):
        # Scalar legacy path (semantic_fallback returns score == 1 on
        # success).  Non-dict scalar 1 → PASS; anything else → FAIL.
        return EvalPassStatus.PASS if score == 1 else EvalPassStatus.FAIL
    if _is_all_pass(score, thresholds):
        return EvalPassStatus.PASS
    return EvalPassStatus.FAIL


def _compute_case_average_score(score: Any) -> float:
    """Compute the per-case average score for run-level aggregation.

    Dict scores: arithmetic mean of all numeric values (0.0 when empty).
    Scalar scores: pass through as float.
    """
    if not isinstance(score, dict):
        return float(score)
    vals = [v for v in score.values() if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else 0.0


def _execute_single_case(
    tenant_id: str,
    user_id: str,
    agent_id: int,
    agent_version_no: int,
    case: dict[str, Any],
    run: dict[str, Any],
    judge_model_id: int,
    adapter: Any,
    evaluators: dict[int, dict[str, Any]],
    judge_system_prompt: str,
    context_window: int = 4096,
    history: list[dict[str, Any]] | None = None,
) -> tuple[float, str, list[dict] | None]:
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
                conversation_id=_evaluation_conversation_id(
                    run["agent_evaluation_id"], case_id
                ),
            )
        )
        predict = {"answer": answer_text}
        # Threshold map: build from the per-run evaluator cache (delegated to
        # ``_build_evaluator_thresholds`` so the same map can be reused by the
        # analysis-report path).
        thresholds = _build_evaluator_thresholds(evaluators)

        # CRITICAL: do NOT json.dumps(score).  agent_evaluation_case_t.score
        # is JSONB and SQLAlchemy serialises Python dicts for us.  Pre-
        # serialising would create a JSON-string-inside-JSONB double-wrap.
        pass_status = _determine_case_pass_status(score, thresholds)
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
        avg = _compute_case_average_score(score)
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
            exc, str(exc), model_id=judge_model_id, tenant_id=tenant_id,
            language=run.get("language", "zh"),
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
        cases = [
            {"inputs": {"query": q.strip()}, "label": {"answer": ""}, "order_no": i}
            for i, q in enumerate(queries)
        ]
        evaluation_set_id = materialize_virtual_evaluation_set_for_run(
            tenant_id=tenant_id,
            name=set_name,
            cases=cases,
            created_by=user_id,
            agent_evaluation_id=agent_evaluation_id,
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

        # Execute in the runtime process, which owns the shared workspace
        # volume mounted by the sandbox container.
        _dispatch_agent_evaluation_run(
            agent_evaluation_id=agent_evaluation_id,
            user_id=user_id,
            tenant_id=tenant_id,
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


def _preload_evaluators_for_run(run: dict, tenant_id: str) -> dict[int, dict[str, Any]]:
    """Preload PUBLISHED evaluators from the run's evaluator_config."""
    evaluators: dict[int, dict[str, Any]] = {}
    raw_config = run.get("evaluator_config")
    if isinstance(raw_config, dict) and raw_config.get("evaluator_ids"):
        for eid in raw_config["evaluator_ids"]:
            ev = get_evaluator(eid, tenant_id)
            if ev and ev.get("status") == "PUBLISHED":
                evaluators[eid] = ev
    return evaluators


def _resolve_judge_context_window(judge_model_id: int, tenant_id: str) -> int:
    """Resolve judge model context window, defaulting to 4096."""
    context_window = 4096
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
    return context_window


def _load_all_evaluation_cases(agent_evaluation_id: int, tenant_id: str) -> list[dict]:
    """Load ALL evaluation cases with pagination (page size 200)."""
    all_cases: list[dict] = []
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
    return all_cases


def _group_cases_by_session(all_cases: list[dict]) -> dict[str, list[dict]]:
    """Group cases by session_id for multi-turn support."""
    sessions: dict[str, list[dict]] = defaultdict(list)
    for c in all_cases:
        sid = c.get("session_id") or f"__single__{c['agent_evaluation_case_id']}"
        sessions[sid].append(c)
    return sessions


def execute_agent_evaluation_run(
    tenant_id: str,
    user_id: str,
    agent_evaluation_id: int,
    judge_model_id: int | None = None,
):
    run: dict[str, Any] = {}
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
        evaluators = _preload_evaluators_for_run(run, tenant_id)
        judge_system_prompt = get_prompt_template(
            "evaluation_judge_system", run.get("language", "zh")
        )["SYSTEM_PROMPT"]

        # Resolve judge model context window once (used for runtime_events trimming)
        context_window = _resolve_judge_context_window(judge_model_id, tenant_id)

        # Load ALL cases first, then group by session_id for multi-turn support.
        # This avoids splitting sessions across pages (which would reset history).
        all_cases = _load_all_evaluation_cases(agent_evaluation_id, tenant_id)
        sessions = _group_cases_by_session(all_cases)

        scores: list[float] = []
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
            history: list[dict[str, Any]] = []
            for c in session_cases:
                case_score, answer_text, _events = _execute_single_case(
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
            exc, str(exc), model_id=judge_model_id, tenant_id=tenant_id,
            language=run.get("language", "zh"),
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


def _normalize_cases_response(cases: Any) -> list:
    """Normalize the ``list_agent_evaluation_cases`` response to a list.

    The DB helper returns either a list of case dicts or a paginated dict
    of shape ``{"items": [...]}``; this collapses both shapes (plus
    ``None``) into a plain list for downstream iteration.
    """
    if isinstance(cases, dict):
        return cases.get("items", [])
    return cases or []


def _load_evaluator_thresholds_from_config(raw_config: Any, tenant_id: str) -> dict:
    """Build ``{name: pass_threshold}`` map from the run's evaluator_config.

    Skips non-dict / blank entries so legacy evaluator rows with null
    thresholds fall through to the global DEFAULT inside ``_is_all_pass``.
    This is the same map consumed by ``_execute_single_case`` so the
    analysis's "why did this fail" logic matches the pass/fail decision
    recorded in the DB.
    """
    thresholds: dict[str, float] = {}
    if not (
        isinstance(raw_config, dict)
        and isinstance(raw_config.get("evaluator_ids"), list)
    ):
        return thresholds
    for eid in raw_config["evaluator_ids"]:
        try:
            ev = get_evaluator(int(eid), tenant_id)
        except (ValueError, TypeError):
            ev = None
        if isinstance(ev, dict) and ev.get("name"):
            thresholds[str(ev["name"])] = float(
                ev.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
            )
    return thresholds


def _parse_case_reason(reason_raw: str) -> dict:
    """Parse a case ``reason`` field into a dict.

    The field is TEXT storing a ``json.dumps`` string. When it cannot be
    parsed, the raw text is wrapped under the ``"reason"`` key.
    """
    if not reason_raw:
        return {}
    try:
        parsed = json.loads(reason_raw)
        return parsed if isinstance(parsed, dict) else {"reason": reason_raw}
    except (ValueError, TypeError):
        return {"reason": reason_raw}


def _extract_nested_str(c: dict, field: str, key: str) -> str:
    """Extract a string from a nested dict field (``c[field][key]``)."""
    nested = c.get(field) or {}
    if isinstance(nested, dict):
        return str(nested.get(key) or "")
    return ""


def _build_analysis_failure_example(c: dict) -> dict:
    """Build a compact failure-payload dict for the analysis LLM prompt.

    ``score`` is JSONB (already a dict); ``reason`` is TEXT storing a
    ``json.dumps`` string, decoded here so per-evaluator reasons can be
    joined.  Each value is clamped to 4000 chars for LLM context limits.
    """
    score = c.get("score")
    score_dict = score if isinstance(score, dict) else {}
    reason_dict = _parse_case_reason(c.get("reason") or "")
    predict_answer = _extract_nested_str(c, "predict", "answer")
    query_text = _extract_nested_str(c, "inputs", "query")

    # Compact score: single-evaluator score → scalar, multi-evaluator → keep dict
    if len(score_dict) == 1:
        _score_val = next(iter(score_dict.values()))
    else:
        _score_val = score_dict

    # Compact reason: multi-evaluator dict → joined string, scalar → keep string
    if reason_dict:
        _reason_str = " | ".join(f"{k}: {v}" for k, v in reason_dict.items())
    else:
        _reason_str = ""

    return {
        "case_id": c.get("agent_evaluation_case_id"),
        "query": query_text,
        "answer": predict_answer[:4000],
        "score": _score_val,
        "reason": _reason_str[:4000],
    }


def _render_analysis_stats_block(total: int, passed: int, thresholds: dict) -> str:
    """Render the one-line stats header for the analysis prompt.

    Includes the evaluator threshold map when present so the LLM knows the
    pass/fail rules for every score column.
    """
    stats_block = f"Total cases: {total}, Passed: {passed}, Failed: {total - passed}, Pass rate: {passed}/{total}"
    if thresholds:
        stats_block += (
            f"\nEvaluator pass thresholds: {json.dumps(thresholds, ensure_ascii=False)}"
        )
    return stats_block


def _render_analysis_failures_block(failure_examples: list) -> str:
    """Render the per-case failure details section for the analysis prompt.

    Clamps to ``MAX_FAILURE_EXAMPLES`` entries (SDK constant, typically
    ~20).  Each case is compacted onto one readable line per block so
    token counts stay low and the model can parse cleanly.
    """
    if not failure_examples:
        return "\nNo failed cases."
    failures_block = ""
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
    return failures_block


def _call_analysis_llm_and_parse(
    run: dict, language: str, user_prompt: str, tenant_id: str
) -> dict:
    """Call the analysis LLM and parse the JSON response.

    Raises ``AppException`` with ``AGENT_EVALUATION_ANALYSIS_FAILED`` if the
    parsed response is not a dict; the caller is responsible for catching
    and logging the underlying ``Exception`` for observability.
    """
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
    return data


def generate_analysis_report_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    language: str = "zh",
    force: bool = False,
) -> dict[str, Any]:
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
    cases = _normalize_cases_response(cases)

    raw_config = run.get("evaluator_config") or {}
    thresholds = _load_evaluator_thresholds_from_config(raw_config, tenant_id)

    # ── Basic run stats ──────────────────────────────────────────────────
    total = len(cases)
    passed = sum(1 for c in cases if c.get("pass_status") == EvalPassStatus.PASS)
    failed_cases = [c for c in cases if c.get("pass_status") == EvalPassStatus.FAIL]

    # ── Collect failure details for the LLM prompt ──────────────────────
    failure_examples = [_build_analysis_failure_example(c) for c in failed_cases]

    # ── Render prompt blocks ─────────────────────────────────────────────
    stats_block = _render_analysis_stats_block(total, passed, thresholds)
    failures_block = _render_analysis_failures_block(failure_examples)

    user_prompt = f"{stats_block}\n\nFailed case details (up to {MAX_FAILURE_EXAMPLES} examples):{failures_block}"
    prompt_chars = len(user_prompt)

    # ── LLM call + cache write ───────────────────────────────────────────
    try:
        data = _call_analysis_llm_and_parse(run, language, user_prompt, tenant_id)
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
) -> dict[str, Any]:
    return get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )


def list_agent_evaluations_by_agent_impl(
    agent_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
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
    session_id: str | None = None,
) -> dict[str, Any]:
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
        session_id=session_id,
    )


def get_evaluation_stats_impl(
    agent_evaluation_id: int,
    tenant_id: str,
) -> dict[str, Any]:
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
    columns so payload stays tight).  ``score`` is JSONB and reads back
    as a Python dict, so per-evaluator aggregation iterates it directly.

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
    for cs in case_scores:
        if cs["pass_status"] == EvalPassStatus.PASS:
            pass_count += 1
        elif cs["pass_status"] == EvalPassStatus.FAIL:
            fail_count += 1

        score_dict = cs.get("score")
        if not isinstance(score_dict, dict):
            continue
        for name, v in score_dict.items():
            if not isinstance(v, (int, float)) or not isfinite(v):
                continue
            eval_scores[name].append(v)
            # bucket = floor(value * 5), saturate at bucket index 4.
            # Scores > 1.0 (from custom ranges that are NOT yet normalised
            # in the DB layer) still bucket to the top-green slot so the
            # page never displays negative/overflow counts.
            bucket_idx = min(4, max(0, int(v * 5)))
            histogram_buckets[bucket_idx] += 1

    per_evaluator = []
    for name, scores in sorted(eval_scores.items()):
        avg = sum(scores) / len(scores)
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
        "pass_count=%s fail_count=%s evaluator_count=%s "
        "histogram_buckets=%s",
        agent_evaluation_id,
        tenant_id,
        total,
        pass_count,
        fail_count,
        len(per_evaluator),
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
        except Exception as exc:  # noqa: BLE001
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
    evaluator_ids: list | None = None,
    language: str = "zh",
) -> dict:
    # Preload evaluators
    evaluators: dict[int, dict[str, Any]] = {}
    if evaluator_ids:
        for eid in evaluator_ids:
            ev = get_evaluator(eid, tenant_id)
            if ev and ev.get("status") == "PUBLISHED":
                evaluators[eid] = ev
    judge_system_prompt = get_prompt_template(
        "evaluation_judge_system", language
    )["SYSTEM_PROMPT"]

    if JiuwenSDKAdapter is None:
        raise JiuwenSDKUnavailableError("Jiuwen SDK adapter is unavailable")
    adapter = JiuwenSDKAdapter(model_id=judge_model_id, tenant_id=tenant_id)

    answer_text, _runtime_events, score, reason = await _evaluate_query(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        agent_version_no=agent_version_no,
        query=query,
        judge_model_id=judge_model_id,
        adapter=adapter,
        evaluators=evaluators,
        judge_system_prompt=judge_system_prompt,
        language=language,
    )
    return {"query": query, "answer": answer_text, "scores": score, "reasons": reason}
