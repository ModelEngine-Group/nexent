"""External trace emitter for Nexent ContextManager and agent runtime.

Wraps a Nexent agent (or a bare ContextManager) without modifying SDK source.
Layers can be selectively enabled:

    compression  - wrap ContextManager.compress_if_needed (Phase 1)
    model        - wrap agent.model __call__ (tagged: main vs compression)
    observer     - tap agent.observer.add_message
    tools        - wrap each agent.tools[name].forward
    executor     - wrap agent.python_executor __call__

Events are written as JSONL to a trace file. SDK source is untouched; the
debugger only reads public APIs and a handful of de-facto-stable internals
(_step_local_log, _effective_*_tokens) that the benchmark already uses.
"""

import contextvars
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

# Set inside the compression wrapper so the model wrapper can tag calls.
_compression_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "compression_active", default=False
)

DEFAULT_LAYERS: Set[str] = {"compression", "model", "observer", "tools", "executor"}


# ============================================================
#  Bounded serialization helpers
# ============================================================

def _truncate_text(s: Optional[str], head: int = 500, tail: int = 500) -> Optional[str]:
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    if len(s) <= head + tail + 50:
        return s
    return s[:head] + f"\n...[{len(s) - head - tail} chars elided]...\n" + s[-tail:]


def _messages_digest(messages: Any, full: bool = False) -> List[dict]:
    out = []
    for m in messages or []:
        role = getattr(m, "role", None)
        if hasattr(role, "value"):
            role = role.value
        content = getattr(m, "content", None)
        if isinstance(content, list):
            text = "".join(
                seg.get("text", "") if isinstance(seg, dict) else str(seg)
                for seg in content
            )
        else:
            text = str(content) if content is not None else ""
        entry = {
            "role": str(role),
            "chars": len(text),
            "preview": _truncate_text(text, head=200, tail=200),
        }
        # full=True keeps the verbatim message text (no truncation), so the
        # exact prompt is recoverable. Used for compression LLM calls.
        if full:
            entry["text"] = text
        out.append(entry)
    return out


def _safe_repr(value: Any, head: int = 300, tail: int = 200) -> str:
    try:
        return _truncate_text(repr(value), head=head, tail=tail)
    except Exception as exc:
        return f"<unrepr-able: {exc}>"


def _digest_call_args(args: tuple, kwargs: dict) -> dict:
    return {
        "args": [_safe_repr(a, head=200, tail=100) for a in args],
        "kwargs": {k: _safe_repr(v, head=200, tail=100) for k, v in kwargs.items()},
    }


# ============================================================
#  Core debugger
# ============================================================

class ContextDebugger:
    """Trace emitter. Writes events to a JSONL file."""

    def __init__(
        self,
        trace_path: str,
        run_id: Optional[str] = None,
        capture_full_summary: bool = True,
        capture_full_messages: bool = False,
        append: bool = False,
    ):
        self.trace_path = os.path.abspath(trace_path)
        self.run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        self.capture_full_summary = capture_full_summary
        self.capture_full_messages = capture_full_messages

        self._lock = threading.Lock()
        self._seq = 0
        self._current_step: Optional[int] = None  # tracked via observer STEP_COUNT
        self._compression_step_counter = 0
        self._prev_summary_cache: Optional[str] = None
        self._curr_summary_cache: Optional[str] = None

        parent = os.path.dirname(self.trace_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not append:
            open(self.trace_path, "w", encoding="utf-8").close()

        self._emit(
            "run_begin",
            {
                "capture_full_summary": capture_full_summary,
                "capture_full_messages": capture_full_messages,
                "pid": os.getpid(),
            },
        )

    def _emit(self, event: str, data: dict) -> None:
        # The debugger must never crash the agent it observes: a failed trace
        # write is swallowed rather than propagated.
        try:
            with self._lock:
                self._seq += 1
                record = {
                    "seq": self._seq,
                    "ts": time.time(),
                    "run_id": self.run_id,
                    "agent_step": self._current_step,
                    "event": event,
                    "data": data,
                }
                line = json.dumps(record, ensure_ascii=False, default=str)
                # errors="replace": lone surrogates (e.g. from text decoded
                # with surrogateescape, such as some terminal stdin) cannot be
                # UTF-8 encoded; replacing them keeps the write from raising.
                with open(self.trace_path, "a", encoding="utf-8",
                          errors="replace") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    # ------------------------------------------------------------
    #  Compression-layer hooks (Phase 1)
    # ------------------------------------------------------------

    def on_compress_begin(
        self, cm, memory, original_messages, current_run_start_idx
    ) -> None:
        self._compression_step_counter += 1

        config_snapshot = {
            "enabled": cm.config.enabled,
            "token_threshold": cm.config.token_threshold,
            "keep_recent_pairs": cm.config.keep_recent_pairs,
            "keep_recent_steps": cm.config.keep_recent_steps,
        }

        effective = prev_tokens = curr_tokens = None
        try:
            effective = cm._effective_tokens(memory, current_run_start_idx)
            prev_steps = memory.steps[:current_run_start_idx]
            curr_steps = memory.steps[current_run_start_idx:]
            prev_tokens = cm._effective_prev_tokens(prev_steps)
            curr_tokens = cm._effective_curr_tokens(curr_steps)
        except Exception as exc:
            self._emit("debug_error", {"phase": "compress_begin_est", "error": str(exc)})

        predicted = self._predict_branch(cm.config, effective, prev_tokens, curr_tokens)

        summary_before = None
        try:
            summary_before = cm.export_summary()
            self._prev_summary_cache = summary_before.get("previous_summary")
            self._curr_summary_cache = summary_before.get("current_summary")
        except Exception as exc:
            self._emit("debug_error", {"phase": "compress_begin_summary", "error": str(exc)})

        self._emit(
            "compress_begin",
            {
                "compression_step": self._compression_step_counter,
                "current_run_start_idx": current_run_start_idx,
                "memory_step_count": len(memory.steps),
                "original_messages": _messages_digest(original_messages),
                "estimated_tokens": {
                    "effective": effective,
                    "prev": prev_tokens,
                    "curr": curr_tokens,
                    "threshold": cm.config.token_threshold,
                },
                "config": config_snapshot,
                "predicted_decision": predicted,
                "summary_before": summary_before if self.capture_full_summary else None,
            },
        )

    def on_compress_end(
        self, cm, result_messages, success: bool, error: Optional[str] = None
    ) -> None:
        if not success:
            self._emit("compress_end", {"success": False, "error": error})
            return

        try:
            records = list(getattr(cm, "_step_local_log", []) or [])
            for i, rec in enumerate(records):
                self._emit(
                    "compression_call",
                    {
                        "call_index": i,
                        "call_type": rec.call_type,
                        "cache_hit": rec.cache_hit,
                        "input_tokens": rec.input_tokens,
                        "output_tokens": rec.output_tokens,
                        "input_chars": rec.input_chars,
                        "output_chars": rec.output_chars,
                        "details": rec.details,
                    },
                )
        except Exception as exc:
            self._emit("debug_error", {"phase": "compression_calls", "error": str(exc)})

        step_stats = token_counts = summary_after = None
        try:
            step_stats = cm.get_step_compression_stats()
        except Exception as exc:
            self._emit("debug_error", {"phase": "step_stats", "error": str(exc)})
        try:
            token_counts = cm.get_token_counts()
        except Exception as exc:
            self._emit("debug_error", {"phase": "token_counts", "error": str(exc)})
        try:
            summary_after = cm.export_summary()
        except Exception as exc:
            self._emit("debug_error", {"phase": "end_summary", "error": str(exc)})

        prev_after = (summary_after or {}).get("previous_summary")
        curr_after = (summary_after or {}).get("current_summary")
        summary_changed = {
            "previous_changed": prev_after != self._prev_summary_cache,
            "current_changed": curr_after != self._curr_summary_cache,
        }

        self._emit(
            "compress_end",
            {
                "success": True,
                "result_messages": _messages_digest(result_messages),
                "step_stats": step_stats,
                "token_counts": token_counts,
                "summary_after": summary_after if self.capture_full_summary else None,
                "summary_changed": summary_changed,
            },
        )

    # ------------------------------------------------------------
    #  Observer tap helper — also updates current_step
    # ------------------------------------------------------------

    def update_step_from_observer(self, process_type_value: str, content: Any) -> None:
        """Track agent.step_number from observer STEP_COUNT events."""
        if process_type_value == "step_count":
            try:
                self._current_step = int(content)
            except (ValueError, TypeError):
                pass

    @staticmethod
    def _predict_branch(config, effective, prev_tokens, curr_tokens) -> dict:
        if not config.enabled:
            return {"branch": "disabled"}
        if effective is None:
            return {"branch": "unknown_estimation_failed"}
        threshold = config.token_threshold
        if effective <= threshold:
            return {
                "branch": "stable_or_noop",
                "effective": effective,
                "threshold": threshold,
            }
        return {
            "branch": "full_compression_path",
            "compress_prev": (prev_tokens or 0) > threshold * 0.6,
            "compress_curr": (curr_tokens or 0) > threshold * 0.4,
            "prev_token_share": (prev_tokens or 0) / threshold if threshold else None,
            "curr_token_share": (curr_tokens or 0) / threshold if threshold else None,
        }


# ============================================================
#  Proxy objects (model, tool, python_executor)
# ============================================================

class _ModelProxy:
    """Wraps a smolagents-compatible model object; logs every __call__.

    Forwards every other attribute to the underlying model so the agent
    still sees the same interface.
    """

    def __init__(self, real_model, debugger: ContextDebugger):
        object.__setattr__(self, "_real", real_model)
        object.__setattr__(self, "_debugger", debugger)

    def __call__(self, *args, **kwargs):
        debugger: ContextDebugger = object.__getattribute__(self, "_debugger")
        real = object.__getattribute__(self, "_real")
        tag = "compression" if _compression_active.get() else "main"
        # Compression calls are this tool's primary subject: always capture
        # the verbatim prompt and output. Main calls follow
        # capture_full_messages so the trace stays lean by default.
        full = tag == "compression" or debugger.capture_full_messages

        # Extract messages from first arg (smolagents calling convention)
        input_messages = args[0] if args else kwargs.get("messages")
        debugger._emit(
            "llm_call_begin",
            {
                "tag": tag,
                "input_messages": _messages_digest(input_messages, full=full),
                "stop_sequences": kwargs.get("stop_sequences"),
            },
        )

        start = time.time()
        try:
            result = real(*args, **kwargs)
            elapsed_ms = int((time.time() - start) * 1000)

            output_content = getattr(result, "content", None)
            output_text = (
                output_content
                if isinstance(output_content, str)
                else (str(output_content) if output_content is not None else "")
            )
            token_usage = getattr(result, "token_usage", None)
            end_data = {
                "tag": tag,
                "duration_ms": elapsed_ms,
                "output_preview": _truncate_text(output_text, head=600, tail=400),
                "output_chars": len(output_text),
                "input_tokens": getattr(token_usage, "input_tokens", None) if token_usage else None,
                "output_tokens": getattr(token_usage, "output_tokens", None) if token_usage else None,
            }
            # full=True keeps the verbatim output (no truncation), so the
            # exact compression summary is recoverable.
            if full:
                end_data["output_full"] = output_text
            debugger._emit("llm_call_end", end_data)
            return result
        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            debugger._emit(
                "llm_call_end",
                {
                    "tag": tag,
                    "duration_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            raise

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_real"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_real"), name, value)


class _PyExecutorProxy:
    """Wraps python_executor; logs each code execution call."""

    def __init__(self, real_executor, debugger: ContextDebugger):
        object.__setattr__(self, "_real", real_executor)
        object.__setattr__(self, "_debugger", debugger)

    def __call__(self, code, *args, **kwargs):
        debugger: ContextDebugger = object.__getattribute__(self, "_debugger")
        real = object.__getattribute__(self, "_real")

        code_str = code if isinstance(code, str) else str(code)
        debugger._emit(
            "code_execute_begin",
            {
                "code_preview": _truncate_text(code_str, head=400, tail=400),
                "code_chars": len(code_str),
            },
        )

        start = time.time()
        try:
            result = real(code, *args, **kwargs)
            elapsed_ms = int((time.time() - start) * 1000)
            output = getattr(result, "output", None)
            logs = getattr(result, "logs", None)
            debugger._emit(
                "code_execute_end",
                {
                    "duration_ms": elapsed_ms,
                    "output_preview": _truncate_text(
                        str(output) if output is not None else "",
                        head=400,
                        tail=200,
                    ),
                    "logs_preview": _truncate_text(
                        str(logs) if logs is not None else "",
                        head=400,
                        tail=200,
                    ),
                    "is_final_answer": getattr(result, "is_final_answer", None),
                },
            )
            return result
        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            debugger._emit(
                "code_execute_end",
                {
                    "duration_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            raise

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_real"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_real"), name, value)


# ============================================================
#  Attachment functions
# ============================================================

def _wrap_compress_if_needed(cm, debugger: ContextDebugger) -> None:
    """Wrap cm.compress_if_needed with begin/end hooks + compression contextvar."""
    if getattr(cm, "_debugger", None) is debugger:
        return  # already wrapped by this debugger
    original_compress = cm.compress_if_needed

    def wrapped(model, memory, original_messages, current_run_start_idx):
        debugger.on_compress_begin(cm, memory, original_messages, current_run_start_idx)
        token = _compression_active.set(True)
        try:
            result = original_compress(
                model, memory, original_messages, current_run_start_idx
            )
            debugger.on_compress_end(cm, result, success=True)
            return result
        except Exception as exc:
            debugger.on_compress_end(cm, None, success=False, error=str(exc))
            raise
        finally:
            _compression_active.reset(token)

    cm.compress_if_needed = wrapped
    cm._debugger = debugger


def _wrap_tool_forward(tool, name: str, debugger: ContextDebugger) -> None:
    """Wrap a single tool's forward method on the instance.

    Tool.__call__ -> self.forward(...), so instance-level wrap of forward
    intercepts every actual call without breaking isinstance checks.
    """
    original_forward = getattr(tool, "forward", None)
    if original_forward is None:
        return

    def wrapped_forward(*args, **kwargs):
        debugger._emit(
            "tool_call_begin",
            {"tool": name, **_digest_call_args(args, kwargs)},
        )
        start = time.time()
        try:
            result = original_forward(*args, **kwargs)
            elapsed_ms = int((time.time() - start) * 1000)
            debugger._emit(
                "tool_call_end",
                {
                    "tool": name,
                    "duration_ms": elapsed_ms,
                    "return_preview": _safe_repr(result, head=400, tail=200),
                    "return_type": type(result).__name__,
                },
            )
            return result
        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            debugger._emit(
                "tool_call_end",
                {
                    "tool": name,
                    "duration_ms": elapsed_ms,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            raise

    tool.forward = wrapped_forward


def _tap_observer(observer, debugger: ContextDebugger) -> None:
    """Mirror every observer.add_message call into the debugger trace.

    Original add_message is still called, so the front-end stream is
    untouched.
    """
    if getattr(observer, "_debugger_tapped", False):
        return
    original_add_message = observer.add_message

    def wrapped_add_message(agent_name, process_type, content, **kwargs):
        # All debugger-side work is guarded so the observed agent's
        # add_message call always runs, even if trace emission fails.
        try:
            pt_value = (
                process_type.value if hasattr(process_type, "value")
                else str(process_type)
            )
            debugger.update_step_from_observer(pt_value, content)
            debugger._emit(
                "observer_event",
                {
                    "agent_name": agent_name,
                    "process_type": pt_value,
                    "content_preview": _truncate_text(
                        str(content) if content is not None else "",
                        head=600,
                        tail=300,
                    ),
                    "content_chars": len(str(content)) if content is not None else 0,
                    "extra_kwargs": list(kwargs.keys()) if kwargs else [],
                },
            )
        except Exception:
            pass
        return original_add_message(agent_name, process_type, content, **kwargs)

    observer.add_message = wrapped_add_message
    observer._debugger_tapped = True


def _snapshot_agent_static(agent, debugger: ContextDebugger) -> None:
    """Emit a one-shot agent_init event with system prompt + tools + config."""
    agent_name = (
        getattr(agent, "name", None)
        or getattr(agent, "agent_name", None)
        or type(agent).__name__
    )
    system_prompt = getattr(agent, "system_prompt", None)
    system_prompt_chars = len(system_prompt) if isinstance(system_prompt, str) else 0

    tools_info: List[dict] = []
    tools = getattr(agent, "tools", None) or {}
    for tname, tool in tools.items():
        tools_info.append(
            {
                "name": tname,
                "description": _truncate_text(
                    getattr(tool, "description", None), head=400, tail=200
                ),
                "inputs": getattr(tool, "inputs", None),
            }
        )

    cm = getattr(agent, "context_manager", None)
    cm_config = None
    if cm is not None and getattr(cm, "config", None) is not None:
        cfg = cm.config
        cm_config = {
            "enabled": getattr(cfg, "enabled", None),
            "token_threshold": getattr(cfg, "token_threshold", None),
            "keep_recent_pairs": getattr(cfg, "keep_recent_pairs", None),
            "keep_recent_steps": getattr(cfg, "keep_recent_steps", None),
            "max_observation_length": getattr(cfg, "max_observation_length", None),
        }

    debugger._emit(
        "agent_init",
        {
            "agent_name": agent_name,
            "agent_class": type(agent).__name__,
            "max_steps": getattr(agent, "max_steps", None),
            "system_prompt": _truncate_text(system_prompt, head=2000, tail=500),
            "system_prompt_chars": system_prompt_chars,
            "tools": tools_info,
            "context_manager_config": cm_config,
        },
    )


def _resolve_target(target) -> tuple:
    """Return (agent, cm) given either an agent or a ContextManager."""
    if hasattr(target, "compress_if_needed"):
        return None, target
    cm = getattr(target, "context_manager", None)
    return target, cm


def attach_debugger(
    target,
    trace_path: Optional[str] = None,
    run_id: Optional[str] = None,
    capture_full_summary: bool = True,
    capture_full_messages: bool = False,
    layers: Optional[Iterable[str]] = None,
    append: bool = False,
    existing: Optional[ContextDebugger] = None,
) -> Optional[ContextDebugger]:
    """Attach the debugger to an agent or a ContextManager.

    Args:
        target: Either a Nexent agent (CoreAgent/NexentAgent) or a ContextManager.
        trace_path: Output JSONL path. Falls back to env var NEXENT_CONTEXT_DEBUG.
        run_id: Optional explicit run id (auto-generated otherwise).
        capture_full_summary: Include full summary text in compression events.
        capture_full_messages: Also store verbatim message text for main LLM
            calls. Compression LLM calls are always captured verbatim
            regardless of this flag.
        layers: Subset of {"compression", "model", "observer", "tools", "executor"}.
            Default: all available layers.
        append: Append to an existing trace file instead of truncating.
        existing: Reuse this ContextDebugger instead of creating a new one.
            Lets an interactive session share one trace/run_id across many
            agent instances (one per conversation turn).

    Returns:
        The ContextDebugger, or None if no trace path resolved.
    """
    agent, cm = _resolve_target(target)
    enabled_layers = set(layers) if layers is not None else set(DEFAULT_LAYERS)

    if existing is not None:
        debugger = existing
    else:
        resolved_path = trace_path or os.environ.get("NEXENT_CONTEXT_DEBUG")
        if not resolved_path:
            return None
        debugger = ContextDebugger(
            trace_path=resolved_path,
            run_id=run_id,
            capture_full_summary=capture_full_summary,
            capture_full_messages=capture_full_messages,
            append=append,
        )

    if agent is not None:
        try:
            _snapshot_agent_static(agent, debugger)
        except Exception as exc:
            debugger._emit("debug_error", {"phase": "agent_init", "error": str(exc)})

    if cm is not None and "compression" in enabled_layers:
        try:
            _wrap_compress_if_needed(cm, debugger)
        except Exception as exc:
            debugger._emit("debug_error", {"phase": "wrap_compress", "error": str(exc)})

    if agent is not None and "model" in enabled_layers:
        model = getattr(agent, "model", None)
        if model is not None and not isinstance(model, _ModelProxy):
            try:
                agent.model = _ModelProxy(model, debugger)
            except Exception as exc:
                debugger._emit("debug_error", {"phase": "wrap_model", "error": str(exc)})

    if agent is not None and "observer" in enabled_layers:
        observer = getattr(agent, "observer", None)
        if observer is not None:
            try:
                _tap_observer(observer, debugger)
            except Exception as exc:
                debugger._emit("debug_error", {"phase": "tap_observer", "error": str(exc)})

    if agent is not None and "tools" in enabled_layers:
        tools = getattr(agent, "tools", None) or {}
        for tname, tool in list(tools.items()):
            try:
                _wrap_tool_forward(tool, tname, debugger)
            except Exception as exc:
                debugger._emit(
                    "debug_error",
                    {"phase": "wrap_tool", "tool": tname, "error": str(exc)},
                )

    if agent is not None and "executor" in enabled_layers:
        executor = getattr(agent, "python_executor", None)
        if executor is not None and not isinstance(executor, _PyExecutorProxy):
            try:
                agent.python_executor = _PyExecutorProxy(executor, debugger)
            except Exception as exc:
                debugger._emit(
                    "debug_error", {"phase": "wrap_executor", "error": str(exc)}
                )

    agent_or_cm = agent if agent is not None else cm
    if agent_or_cm is not None:
        try:
            agent_or_cm._debugger = debugger
        except Exception:
            pass

    return debugger
