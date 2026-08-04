"""Export a ctx_debugger JSONL trace into Langfuse for visual analysis.

This is the "option 1" adapter: instead of building a custom web UI, map the
trace onto a self-hosted Langfuse instance and get nested traces, drill-down,
token/cost views and session grouping for free.

Mapping:
    each agent turn (an `agent_init` event)  -> one Langfuse trace
    llm_call_begin/end                       -> a generation
    compress_begin/end                       -> a span wrapping its
                                                 compression generations
    tool_call_begin/end                      -> a tool observation
    code_execute_begin/end                   -> a span
    the whole file                           -> one Langfuse session

Usage (from sdk/):
    python -m ctx_debugger.langfuse_export <trace.jsonl> [options]

Options:
    --session-id ID   Langfuse session id (default: <file stem>-<timestamp>)
    --dry-run         Print the mapped trace tree; do not contact Langfuse
    --host URL        Langfuse host (else $LANGFUSE_HOST)

Langfuse credentials are read from the environment, the standard way:
    LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

Known limitation: observations are created at export time, so each one's
duration is faithful but absolute placement on the Langfuse timeline is the
export moment, not the original wall-clock time.
"""

import argparse
import contextlib
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

# Begin event -> its matching end event. Everything else is standalone.
BEGIN_TO_END = {
    "compress_begin": "compress_end",
    "llm_call_begin": "llm_call_end",
    "code_execute_begin": "code_execute_end",
    "tool_call_begin": "tool_call_end",
}
END_EVENTS = set(BEGIN_TO_END.values())


class Obs:
    """One Langfuse observation built from a begin/end event pair."""

    __slots__ = ("as_type", "name", "input", "output", "metadata",
                 "usage", "duration_ms", "children")

    def __init__(self, as_type: str, name: str):
        self.as_type = as_type
        self.name = name
        self.input: Any = None
        self.output: Any = None
        self.metadata: Dict[str, Any] = {}
        self.usage: Optional[Dict[str, int]] = None
        self.duration_ms: Optional[float] = None
        self.children: List["Obs"] = []


# ============================================================
#  Trace file -> per-turn segments
# ============================================================

def _load(path: str) -> List[dict]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# ============================================================
#  Benchmark probe-score helpers (optional --benchmarkqa-outputs)
# ============================================================
# When the caller points us at a benchmark outputs/<book_id>/ directory
# (currently eventqa_eval; longmemeval & others can plug in later as long as
# they emit a compatible predictions.jsonl), we read its predictions.jsonl
# and attach Langfuse Scores to each probe trace:
#   * name=correctness (NUMERIC 0/1) + name=match_type (CATEGORICAL),
#     with arm/schema in score metadata
# AND session-level aggregates (read from summary.json) pushed directly
# to the session_id:
#   * baseline_accuracy / compressed_accuracy_<schema> /
#     memory_retention_<schema> / token_reduction_<schema>
# These show up in the Langfuse project session list as per-session
# aggregates — visible alongside session name without drilling into traces.

def _qnum(qid: Optional[str]) -> int:
    m = re.search(r"no(\d+)$", qid or "")
    return int(m.group(1)) if m else -1


def _load_benchmark_outputs(out_dir: Optional[str]) -> Optional[dict]:
    if not out_dir:
        return None
    pred_p = os.path.join(out_dir, "predictions.jsonl")
    sum_p = os.path.join(out_dir, "summary.json")
    if not os.path.exists(pred_p):
        return None
    preds = []
    with open(pred_p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                preds.append(json.loads(line))
    preds.sort(key=lambda p: _qnum(p.get("qid")))
    summary = None
    if os.path.exists(sum_p):
        with open(sum_p, encoding="utf-8") as f:
            summary = json.load(f)
    return {"predictions": preds, "summary": summary}


def _push_session_aggregates(client, session_id: str, summary: dict) -> int:
    """Push session-level aggregates (baseline_accuracy / compressed_accuracy_<schema>
    / memory_retention_<schema> / token_reduction_<schema>) directly to the
    session — no host trace required. Despite my earlier failed API queries,
    these scores DO persist in Langfuse v4 and show up in the project session
    list as per-session aggregates (visible in the UI alongside the session
    name, no need to drill into a trace).
    """
    if not summary:
        return 0
    pushed = 0

    def _push(name, value):
        nonlocal pushed
        if value is None:
            return
        try:
            client.create_score(session_id=session_id, name=name,
                                value=float(value), data_type="NUMERIC")
            pushed += 1
        except Exception as e:
            print(f"  warn: failed to push {name}={value}: {e}", file=sys.stderr)

    _push("baseline_accuracy", (summary.get("baseline") or {}).get("accuracy"))
    for schema, c in (summary.get("compressed") or {}).items():
        _push(f"compressed_accuracy_{schema}", c.get("accuracy"))
        _push(f"memory_retention_{schema}", c.get("memory_retention"))
        _push(f"token_reduction_{schema}", c.get("token_reduction"))
    return pushed


def _classify_probe_arm(events: List[dict]) -> str:
    """compressed vs baseline — detect by the 'Here is the novel' marker."""
    for ev in events:
        if ev.get("event") != "llm_call_begin":
            continue
        for m in ev.get("data", {}).get("input_messages", []) or []:
            txt = m.get("text") or m.get("preview") or ""
            if "Here is the novel" in txt:
                return "baseline"
        break
    return "compressed"


def _split_turns(events: List[dict]) -> List[dict]:
    """Split a flat event list into per-turn segments, one per agent_init."""
    turns: List[dict] = []
    current: Optional[dict] = None
    orphan: List[dict] = []
    for e in events:
        ev = e["event"]
        if ev == "run_begin":
            continue
        if ev == "agent_init":
            if current is not None:
                turns.append(current)
            current = {"init": e, "events": []}
        elif current is None:
            orphan.append(e)
        else:
            current["events"].append(e)
    if current is not None:
        turns.append(current)
    if orphan:
        if turns:
            turns[0]["events"] = orphan + turns[0]["events"]
        else:
            turns.append({"init": None, "events": orphan})
    return turns


# ============================================================
#  Events -> intermediate observation tree
# ============================================================

def _chat(input_messages: Any) -> List[dict]:
    """Render captured input_messages as a chat list for Langfuse."""
    out = []
    for m in input_messages or []:
        out.append({
            "role": m.get("role"),
            "content": m.get("text") or m.get("preview") or "",
        })
    return out


def _begin_obs(begin_ev: str, data: dict) -> Obs:
    if begin_ev == "llm_call_begin":
        tag = data.get("tag", "?")
        o = Obs("generation", f"{tag} LLM call")
        o.input = _chat(data.get("input_messages"))
        o.metadata = {"tag": tag, "stop_sequences": data.get("stop_sequences")}
        return o
    if begin_ev == "compress_begin":
        o = Obs("span", "compression")
        o.input = {
            "predicted_decision": data.get("predicted_decision"),
            "estimated_tokens": data.get("estimated_tokens"),
        }
        o.metadata = {
            "compression_step": data.get("compression_step"),
            "config": data.get("config"),
            "summary_before": data.get("summary_before"),
        }
        return o
    if begin_ev == "code_execute_begin":
        o = Obs("span", "code execution")
        o.input = data.get("code_preview")
        o.metadata = {"code_chars": data.get("code_chars")}
        return o
    if begin_ev == "tool_call_begin":
        o = Obs("tool", f"tool: {data.get('tool', '?')}")
        o.input = {"args": data.get("args"), "kwargs": data.get("kwargs")}
        return o
    return Obs("span", begin_ev)


def _finish_obs(obs: Obs, begin_ev: str, begin_e: dict, end_e: dict) -> None:
    d = end_e["data"]
    obs.duration_ms = round((end_e["ts"] - begin_e["ts"]) * 1000, 1)
    if begin_ev == "llm_call_begin":
        obs.output = d.get("output_full") or d.get("output_preview")
        it, ot = d.get("input_tokens"), d.get("output_tokens")
        if it is not None or ot is not None:
            obs.usage = {"input": it or 0, "output": ot or 0}
        if d.get("error"):
            obs.metadata["error"] = d["error"]
    elif begin_ev == "compress_begin":
        obs.output = {
            "token_counts": d.get("token_counts"),
            "summary_changed": d.get("summary_changed"),
            "summary_after": d.get("summary_after"),
        }
        obs.metadata["success"] = d.get("success")
        obs.metadata["step_stats"] = d.get("step_stats")
    elif begin_ev == "code_execute_begin":
        obs.output = {
            "output": d.get("output_preview"),
            "logs": d.get("logs_preview"),
        }
        obs.metadata["is_final_answer"] = d.get("is_final_answer")
    elif begin_ev == "tool_call_begin":
        obs.output = d.get("return_preview")
        obs.metadata["return_type"] = d.get("return_type")


def _build_tree(events: List[dict]) -> List[Obs]:
    """Pair begin/end events into a nested observation tree."""
    roots: List[Obs] = []
    stack: List[tuple] = []  # (obs, begin_event, begin_ev_name)
    for e in events:
        ev = e["event"]
        if ev in BEGIN_TO_END:
            obs = _begin_obs(ev, e["data"])
            (stack[-1][0].children if stack else roots).append(obs)
            stack.append((obs, e, ev))
        elif ev in END_EVENTS:
            for i in range(len(stack) - 1, -1, -1):
                obs, begin_e, begin_ev = stack[i]
                if BEGIN_TO_END[begin_ev] == ev:
                    _finish_obs(obs, begin_ev, begin_e, e)
                    del stack[i:]  # close it (and any left wrongly open)
                    break
        elif ev == "compression_call":
            for obs, _be, begin_ev in reversed(stack):
                if begin_ev == "compress_begin":
                    obs.metadata.setdefault("compression_calls", []).append(e["data"])
                    break
        elif ev == "debug_error":
            target = stack[-1][0].metadata if stack else None
            if target is not None:
                target.setdefault("debug_errors", []).append(e["data"])
        # observer_event and others are intentionally skipped (noise).
    return roots


def _init_payload(init: Optional[dict]):
    if not init:
        return None, {}
    d = init["data"]
    inp = {
        "agent": d.get("agent_name"),
        "agent_class": d.get("agent_class"),
        "tools": [t.get("name") for t in d.get("tools", [])],
    }
    meta = {
        "system_prompt": d.get("system_prompt"),
        "system_prompt_chars": d.get("system_prompt_chars"),
        "max_steps": d.get("max_steps"),
        "context_manager_config": d.get("context_manager_config"),
    }
    return inp, meta


# ============================================================
#  Dry-run printer
# ============================================================

def _print_turns(turns: List[dict]) -> None:
    for i, turn in enumerate(turns, 1):
        roots = _build_tree(turn["events"])
        init = turn["init"]
        agent = (init["data"].get("agent_name") if init else None) or "agent"
        print(f"\n● trace: turn {i} · {agent}")
        for o in roots:
            _print_obs(o, 1)


def _print_obs(o: Obs, depth: int) -> None:
    pad = "  " * depth
    dur = f"{o.duration_ms / 1000:.1f}s" if o.duration_ms else "-"
    extra = ""
    if o.usage:
        extra = f"   in={o.usage['input']} out={o.usage['output']} tok"
    print(f"{pad}{o.name}  [{o.as_type}]  {dur}{extra}")
    for c in o.children:
        _print_obs(c, depth + 1)


# ============================================================
#  Langfuse push
# ============================================================

def _clean(d: Optional[dict]) -> dict:
    return {k: v for k, v in (d or {}).items() if v is not None}


def _emit(parent, o: Obs) -> None:
    """Recursively create a Langfuse observation and its children."""
    start_ns = time.time_ns()
    kwargs: Dict[str, Any] = {"name": o.name, "as_type": o.as_type}
    if o.input is not None:
        kwargs["input"] = o.input
    md = _clean(o.metadata)
    if md:
        kwargs["metadata"] = md
    if o.usage and o.as_type == "generation":
        kwargs["usage_details"] = o.usage
    child = parent.start_observation(**kwargs)
    for c in o.children:
        _emit(child, c)
    if o.output is not None:
        child.update(output=o.output)
    # Explicit end_time so the displayed duration matches the recorded one.
    child.end(end_time=start_ns + int((o.duration_ms or 0) * 1e6))


def _push_probe_score(client, turn: dict, trace_id: str, benchmark_data: dict,
                      comp_idx: int, base_idx: int) -> tuple:
    """If this turn is a benchmark probe agent, attach correctness + match_type
    scores to the just-created trace. Returns updated (comp_idx, base_idx)."""
    init = turn.get("init") or {}
    agent_name = (init.get("data") or {}).get("agent_name") or ""
    # Currently recognises eventqa_answerer; longmemeval / other benchmarks
    # can plug in here once their probe agent uses an *_answerer name.
    if "answerer" not in agent_name:
        return comp_idx, base_idx
    if not trace_id:
        return comp_idx, base_idx

    arm = _classify_probe_arm(turn["events"])
    preds = benchmark_data["predictions"]
    idx = comp_idx if arm == "compressed" else base_idx
    if idx >= len(preds):
        return comp_idx, base_idx  # out of probes — skip silently

    row = preds[idx]
    if arm == "compressed":
        compressed_block = row.get("compressed") or {}
        # First schema present (single-schema case) — for multi-schema use the
        # session-level score breakdown to disambiguate.
        if not compressed_block:
            return comp_idx + 1, base_idx
        schema = next(iter(compressed_block.keys()))
        arm_pred = compressed_block[schema]
        meta = {"arm": "compressed", "schema": schema,
                "qid": row.get("qid"), "match_type": arm_pred.get("match_type")}
    else:
        arm_pred = row.get("baseline") or {}
        if not arm_pred:
            return comp_idx, base_idx + 1
        meta = {"arm": "baseline", "qid": row.get("qid"),
                "match_type": arm_pred.get("match_type")}

    client.create_score(
        trace_id=trace_id,
        name="correctness",
        value=1.0 if arm_pred.get("correct") else 0.0,
        data_type="NUMERIC",
        metadata=meta,
    )
    if arm_pred.get("match_type"):
        client.create_score(
            trace_id=trace_id,
            name="match_type",
            value=arm_pred["match_type"],
            data_type="CATEGORICAL",
            metadata={"arm": arm},
        )

    return (comp_idx + 1, base_idx) if arm == "compressed" else (comp_idx, base_idx + 1)


def _export(turns: List[dict], session_id: str,
            benchmark_data: Optional[dict] = None) -> None:
    from langfuse import Langfuse
    try:
        from langfuse import propagate_attributes
    except Exception:  # pragma: no cover - older/newer SDK layout
        propagate_attributes = None

    client = Langfuse()
    comp_idx = 0
    base_idx = 0

    for i, turn in enumerate(turns, 1):
        roots = _build_tree(turn["events"])
        init = turn["init"]
        agent = (init["data"].get("agent_name") if init else None) or "agent"
        inp, meta = _init_payload(init)

        all_ev = turn["events"] + ([init] if init else [])
        t0 = min((e["ts"] for e in all_ev), default=time.time())
        t1 = max((e["ts"] for e in all_ev), default=t0)

        ctx = (propagate_attributes(session_id=session_id, trace_name=f"turn-{i}")
               if propagate_attributes else contextlib.nullcontext())
        with ctx:
            start_ns = time.time_ns()
            root = client.start_observation(
                name=f"turn {i}: {agent}", as_type="span",
                input=inp, metadata=_clean(meta),
            )
            for o in roots:
                _emit(root, o)

            # Attach per-probe correctness scores using the explicit trace_id
            # of the just-created root observation. Doesn't depend on
            # OTEL "current span" context (start_observation does NOT make
            # the span current — would need start_as_current_observation).
            if benchmark_data is not None:
                comp_idx, base_idx = _push_probe_score(
                    client, turn, getattr(root, "trace_id", None),
                    benchmark_data, comp_idx, base_idx,
                )

            root.end(end_time=start_ns + int((t1 - t0) * 1e9))

    if benchmark_data is not None:
        # Per-probe scores attached above. Now push session-level aggregates
        # (baseline_accuracy / compressed_accuracy_<schema> / memory_retention
        # / token_reduction) directly to the session_id — these show up in
        # the Langfuse project session list as per-session aggregates without
        # needing a phantom 'session-summary' trace.
        n = _push_session_aggregates(client, session_id,
                                     benchmark_data.get("summary") or {})
        print(f"  scores: {comp_idx} compressed + {base_idx} baseline "
              f"correctness on probe traces + {n} session aggregates")

    client.flush()


# ============================================================
#  CLI
# ============================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="ctx-langfuse-export",
        description="Export a ctx_debugger JSONL trace into Langfuse.",
    )
    ap.add_argument("trace", help="Path to a ctx_debugger JSONL trace file.")
    ap.add_argument("--session-id", help="Langfuse session id to group turns.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the mapped trace tree; do not contact Langfuse.")
    ap.add_argument("--host", help="Langfuse host (else $LANGFUSE_HOST).")
    ap.add_argument(
        "--benchmarkqa-outputs", default=None,
        help=("Optional path to a benchmark outputs/<book_id>/ directory "
              "(e.g. eventqa_eval/outputs/eventqa_full_book0). When set, the "
              "export attaches per-probe Langfuse Scores: name=correctness "
              "(NUMERIC 0/1) + name=match_type (CATEGORICAL), with arm/schema "
              "in score metadata. Langfuse UI rolls these up into per-session "
              "averages automatically (filter by metadata.arm). When NOT set, "
              "the export does plain trace upload — identical to before."),
    )
    args = ap.parse_args()

    events = _load(args.trace)
    turns = _split_turns(events)
    if not turns:
        sys.exit("No turns (agent_init events) found in this trace.")

    stem = os.path.splitext(os.path.basename(args.trace))[0]
    session_id = args.session_id or f"{stem}-{time.strftime('%m%d-%H%M%S')}"

    if args.dry_run:
        print(f"DRY RUN — {len(turns)} turn(s), session_id={session_id}")
        _print_turns(turns)
        return

    if args.host:
        os.environ["LANGFUSE_HOST"] = args.host
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY")
            and os.environ.get("LANGFUSE_SECRET_KEY")):
        sys.exit("ERROR: set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY "
                 "(and LANGFUSE_HOST), or use --dry-run.")

    benchmark_data = _load_benchmark_outputs(args.benchmarkqa_outputs)
    if args.benchmarkqa_outputs and not benchmark_data:
        print(f"  warn: --benchmarkqa-outputs={args.benchmarkqa_outputs} did not "
              f"yield predictions.jsonl; skipping score upload.",
              file=sys.stderr)

    _export(turns, session_id, benchmark_data=benchmark_data)
    print(f"Exported {len(turns)} turn(s) to Langfuse — session_id={session_id}")


if __name__ == "__main__":
    main()
