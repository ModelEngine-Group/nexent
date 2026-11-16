# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import ast
import json
from concurrent.futures import as_completed
from math import isfinite
from typing import Any

from contracts.errors.codes import ErrorCode
from contracts.constants.constants import DEFAULT_PASS_THRESHOLD
from contracts.errors.exceptions import AppException
from infrastructure.concurrency import runtime_thread_manager
from management.services.evaluation.common import (
    _EVALUATOR_FILENAME,
    _EVENT_LABELS,
    _SKIP_TYPES,
    _TRIMMABLE_TYPES,
    ALLOWED_BUILTINS,
    logger,
)
from management.services.model.invocation import call_llm_for_system_prompt
from nexent.core.agents.prompt.evaluation import (
    compose_evaluator_run_prompt,
    render_evaluation_section,
)
from nexent.core.agents.sandbox import _scan_shell_calls
from nexent.core.concurrency import ManagedTaskSpec


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
        return render_evaluation_section("en", "runtime_empty")

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
            step_outputs.append(
                render_evaluation_section(
                    "en", "runtime_step", {"index": step_idx + 1, "content": step_text}
                )
            )

    parts = [render_evaluation_section("en", "runtime_header")]
    parts.extend(step_outputs)
    parts.append(_format_stats_summary(stats))
    parts.append(
        "\n"
        + render_evaluation_section("en", "runtime_final", {"content": actual_section})
    )
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


def _truncate_actual_answer(actual: str, head: int = 120, tail: int = 200) -> str:
    """Truncate the agent's final answer to a head+tail preview when too long."""
    actual_str = str(actual or "")
    if len(actual_str) <= head + tail:
        return actual_str
    return actual_str[:head] + "\n…\n" + actual_str[-tail:]


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
        fixed_line = render_evaluation_section(
            "en", "runtime_tool_call", {"name": name, "arguments": arg_str}
        )
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
        label_field = _EVENT_LABELS.get(evt_type)
        label = render_evaluation_section("en", label_field) if label_field else ""
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
    return "\n" + render_evaluation_section("en", "runtime_stats", stats)


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
    lines = [render_evaluation_section("en", "history_header")]
    for msg in conversation_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            lines.append(
                render_evaluation_section("en", "history_user", {"content": content})
            )
        elif role == "assistant":
            lines.append(
                render_evaluation_section("en", "history_agent", {"content": content})
            )
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
    runtime_context = None
    if runtime_events and "{{runtime_stats}}" in ev["prompt"]:
        runtime_context = _format_runtime_context(
            runtime_events, str(actual), max_tokens=context_window
        )
    return compose_evaluator_run_prompt(
        ev["prompt"],
        query=query,
        expected=expected,
        actual=actual,
        runtime_context=runtime_context,
        conversation_history=conversation_history,
    )


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
        ev,
        query,
        expected,
        actual,
        runtime_events,
        context_window,
        conversation_history,
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
    LLM evaluators run in parallel through the Runtime evaluation lane."""
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
        runtime_thread_manager.submit(
            "evaluation",
            ManagedTaskSpec(
                task_name="agent-evaluation-judge",
                owner="runtime",
            ),
            _call_one_llm_evaluator,
            eid,
            ev,
            judge_system_prompt,
            tenant_id,
            query,
            expected,
            actual,
            judge_model_id,
            runtime_events,
            context_window,
            conversation_history,
        ).future: eid
        for eid, ev in llm_evals.items()
    }
    llm_scores, llm_reasons = _collect_llm_results(futures, llm_evals)
    scores.update(llm_scores)
    reasons.update(llm_reasons)
    return scores, reasons
