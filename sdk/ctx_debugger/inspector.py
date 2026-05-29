"""CLI inspector for ctx_debugger JSONL traces.

Usage:
    python -m ctx_debugger.inspector summary  <trace.jsonl>
    python -m ctx_debugger.inspector runs     <trace.jsonl>
    python -m ctx_debugger.inspector timeline <trace.jsonl> [--run RUN_ID]
    python -m ctx_debugger.inspector compress <trace.jsonl>
    python -m ctx_debugger.inspector llm      <trace.jsonl> [--tag main|compression]
    python -m ctx_debugger.inspector step     <trace.jsonl> --step N [--run RUN_ID]

Requires `rich` (already a transitive dep of smolagents/Nexent).
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError:
    sys.stderr.write("ERROR: rich is required.  pip install rich\n")
    sys.exit(1)


class Trace:
    """Indexed view over a JSONL trace file."""

    def __init__(self, path: str):
        self.path = path
        self.events: List[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                self.events.append(json.loads(line))

    def runs(self) -> List[str]:
        seen, order = set(), []
        for e in self.events:
            r = e["run_id"]
            if r not in seen:
                seen.add(r)
                order.append(r)
        return order


# ============================================================
#  Per-event one-line detail formatters
# ============================================================

def _fmt_detail(event: str, d: dict) -> str:
    if event == "agent_init":
        return f"agent={d.get('agent_name')}, tools={len(d.get('tools', []))}"
    if event == "observer_event":
        pt = d.get("process_type", "")
        cp = (d.get("content_preview") or "").replace("\n", " ")[:55]
        return f"[{pt}] {cp}"
    if event == "llm_call_begin":
        return f"tag={d.get('tag')}  msgs={len(d.get('input_messages', []))}"
    if event == "llm_call_end":
        if d.get("error"):
            return f"tag={d.get('tag')}  ERROR: {d['error'][:60]}"
        return (
            f"tag={d.get('tag')}  dur={d.get('duration_ms')}ms  "
            f"in={d.get('input_tokens')} out={d.get('output_tokens')}"
        )
    if event == "compress_begin":
        pd = d.get("predicted_decision", {})
        et = d.get("estimated_tokens", {})
        return (
            f"branch={pd.get('branch')}  "
            f"eff={et.get('effective')}/{et.get('threshold')}  "
            f"P={pd.get('compress_prev')} C={pd.get('compress_curr')}"
        )
    if event == "compression_call":
        return (
            f"type={d.get('call_type')}  cache={d.get('cache_hit')}  "
            f"in={d.get('input_tokens')} out={d.get('output_tokens')}"
        )
    if event == "compress_end":
        tc = d.get("token_counts") or {}
        sc = d.get("summary_changed") or {}
        return (
            f"unc={tc.get('last_uncompressed')}→comp={tc.get('last_compressed')}  "
            f"prev_changed={sc.get('previous_changed')}"
        )
    if event == "code_execute_begin":
        return f"code_chars={d.get('code_chars')}"
    if event == "code_execute_end":
        return f"dur={d.get('duration_ms')}ms  final_answer={d.get('is_final_answer')}"
    if event == "tool_call_begin":
        return f"tool={d.get('tool')}"
    if event == "tool_call_end":
        return f"tool={d.get('tool')}  dur={d.get('duration_ms')}ms"
    if event == "run_begin":
        return f"pid={d.get('pid')}"
    if event == "debug_error":
        return f"phase={d.get('phase')}: {d.get('error')}"
    return ""


# ============================================================
#  Commands
# ============================================================

def cmd_summary(trace: Trace, args) -> None:
    console = Console()
    events = Counter(e["event"] for e in trace.events)

    main_calls = [e for e in trace.events
                  if e["event"] == "llm_call_end" and e["data"].get("tag") == "main"]
    comp_calls = [e for e in trace.events
                  if e["event"] == "llm_call_end" and e["data"].get("tag") == "compression"]

    def _sum(events_, key):
        return sum((e["data"].get(key) or 0) for e in events_)

    t = Table(title=f"Trace Summary — {trace.path}", box=box.SIMPLE_HEAD)
    t.add_column("Metric", style="cyan")
    t.add_column("Value", justify="right")
    t.add_row("Total events", str(len(trace.events)))
    t.add_row("Total runs", str(len(trace.runs())))
    t.add_row("Compression cycles", str(events.get("compress_begin", 0)))
    t.add_row("Main LLM calls", str(len(main_calls)))
    t.add_row("Compression LLM calls", str(len(comp_calls)))
    t.add_row(
        "Main tokens (in / out)",
        f"{_sum(main_calls, 'input_tokens'):,} / {_sum(main_calls, 'output_tokens'):,}",
    )
    t.add_row(
        "Compression tokens (in / out)",
        f"{_sum(comp_calls, 'input_tokens'):,} / {_sum(comp_calls, 'output_tokens'):,}",
    )
    t.add_row("Main LLM time", f"{_sum(main_calls, 'duration_ms')/1000:.1f}s")
    t.add_row("Compression LLM time", f"{_sum(comp_calls, 'duration_ms')/1000:.1f}s")
    if trace.events:
        span = trace.events[-1]["ts"] - trace.events[0]["ts"]
        t.add_row("Wall-clock span", f"{span:.1f}s")
    console.print(t)

    # Event histogram
    h = Table(title="Event histogram", box=box.SIMPLE)
    h.add_column("Event")
    h.add_column("Count", justify="right")
    for ev, n in events.most_common():
        h.add_row(ev, str(n))
    console.print(h)


def cmd_runs(trace: Trace, args) -> None:
    console = Console()
    by_run: Dict[str, List[dict]] = defaultdict(list)
    for e in trace.events:
        by_run[e["run_id"]].append(e)

    t = Table(title="Runs", box=box.SIMPLE_HEAD)
    t.add_column("Run ID")
    t.add_column("Start ts", justify="right")
    t.add_column("Events", justify="right")
    t.add_column("Compress?", justify="center")
    t.add_column("Agent?", justify="center")
    t.add_column("Agent name")

    for run_id, evts in sorted(by_run.items(), key=lambda x: x[1][0]["ts"]):
        has_compress = any(e["event"] == "compress_begin" for e in evts)
        agent_init = next((e for e in evts if e["event"] == "agent_init"), None)
        agent_name = (agent_init["data"].get("agent_name") if agent_init else "") or ""
        t.add_row(
            run_id,
            f"{evts[0]['ts']:.2f}",
            str(len(evts)),
            "✓" if has_compress else "",
            "✓" if agent_init else "",
            agent_name,
        )
    console.print(t)


def cmd_timeline(trace: Trace, args) -> None:
    console = Console()
    events = trace.events
    if args.run:
        events = [e for e in events if e["run_id"] == args.run]

    if not events:
        console.print(f"[red]No events for run={args.run}[/]")
        return

    title = f"Timeline {f'(run={args.run})' if args.run else '(all runs)'}"
    t = Table(title=title, box=box.SIMPLE)
    t.add_column("seq", justify="right")
    t.add_column("ts", justify="right")
    t.add_column("step", justify="right")
    if not args.run:
        t.add_column("run")
    t.add_column("event", style="cyan")
    t.add_column("detail")

    for e in events:
        detail = _fmt_detail(e["event"], e["data"])
        row = [
            str(e["seq"]),
            f"{e['ts']:.1f}",
            str(e.get("agent_step") if e.get("agent_step") is not None else "-"),
        ]
        if not args.run:
            row.append(e["run_id"][-8:])
        row.append(e["event"])
        row.append(detail)
        t.add_row(*row)
    console.print(t)


def cmd_compress(trace: Trace, args) -> None:
    """Group events into begin → compression_calls → end cycles."""
    console = Console()
    by_run: Dict[str, List[dict]] = defaultdict(list)
    for e in trace.events:
        by_run[e["run_id"]].append(e)

    t = Table(title="Compression Cycles", box=box.SIMPLE_HEAD)
    t.add_column("Run")
    t.add_column("Begin seq", justify="right")
    t.add_column("Step", justify="right")
    t.add_column("Branch")
    t.add_column("PC")
    t.add_column("Eff/Thr", justify="right")
    t.add_column("Calls", justify="right")
    t.add_column("Cache hits", justify="right")
    t.add_column("LLM in→out", justify="right")
    t.add_column("Unc→Comp", justify="right")
    t.add_column("Δ tok %", justify="right")

    any_row = False
    for run_id, evts in by_run.items():
        i = 0
        while i < len(evts):
            e = evts[i]
            if e["event"] != "compress_begin":
                i += 1
                continue
            j = i + 1
            calls, end = [], None
            while j < len(evts):
                if evts[j]["event"] == "compression_call":
                    calls.append(evts[j])
                elif evts[j]["event"] == "compress_end":
                    end = evts[j]
                    break
                j += 1

            pd = e["data"].get("predicted_decision") or {}
            et = e["data"].get("estimated_tokens") or {}
            tc = (end["data"].get("token_counts") if end else {}) or {}
            unc, comp = tc.get("last_uncompressed"), tc.get("last_compressed")
            # Signed delta: negative = shrank, positive = grew.
            ratio = ""
            if unc and comp:
                ratio = f"{(comp - unc) / unc * 100:+.0f}%"

            llm_io = ""
            if calls:
                in_sum = sum((c["data"].get("input_tokens") or 0) for c in calls)
                out_sum = sum((c["data"].get("output_tokens") or 0) for c in calls)
                llm_io = f"{in_sum}→{out_sum}"

            cache_hits = sum(1 for c in calls if c["data"].get("cache_hit"))
            pc_flag = (
                ("P" if pd.get("compress_prev") else "-")
                + ("C" if pd.get("compress_curr") else "-")
            )

            t.add_row(
                run_id[-8:],
                str(e["seq"]),
                str(e.get("agent_step") or "-"),
                pd.get("branch", "?"),
                pc_flag,
                f"{et.get('effective')}/{et.get('threshold')}",
                str(len(calls)),
                str(cache_hits),
                llm_io or "-",
                f"{unc}→{comp}" if unc else "-",
                ratio,
            )
            any_row = True
            i = j + 1 if end else j

    if not any_row:
        console.print("[yellow]No compression cycles in this trace.[/]")
        return
    console.print(t)


def cmd_llm(trace: Trace, args) -> None:
    console = Console()
    pending: Dict[str, dict] = {}
    rows = []
    for e in trace.events:
        run = e["run_id"]
        if e["event"] == "llm_call_begin":
            pending[run] = e
        elif e["event"] == "llm_call_end":
            begin = pending.pop(run, None)
            tag = e["data"].get("tag", "?")
            if args.tag and tag != args.tag:
                continue
            rows.append((begin, e))

    t = Table(title=f"LLM Calls {f'(tag={args.tag})' if args.tag else ''}",
              box=box.SIMPLE_HEAD)
    t.add_column("Run")
    t.add_column("Step", justify="right")
    t.add_column("Seq", justify="right")
    t.add_column("Tag")
    t.add_column("Dur(ms)", justify="right")
    t.add_column("In tok", justify="right")
    t.add_column("Out tok", justify="right")
    t.add_column("Input head", overflow="ellipsis", max_width=40)
    t.add_column("Output head", overflow="ellipsis", max_width=40)

    for begin, end in rows:
        in_msgs = (begin["data"].get("input_messages") or []) if begin else []
        first = (in_msgs[0]["preview"] if in_msgs else "").replace("\n", " ")[:40]
        last_user = ""
        for m in reversed(in_msgs):
            if m.get("role") == "user":
                last_user = (m.get("preview") or "").replace("\n", " ")[:40]
                break
        out = (end["data"].get("output_preview") or end["data"].get("error") or "")
        out = out.replace("\n", " ")[:40]
        d = end["data"]
        t.add_row(
            end["run_id"][-8:],
            str(end.get("agent_step") or "-"),
            str(end["seq"]),
            d.get("tag", "?"),
            str(d.get("duration_ms") or "-"),
            str(d.get("input_tokens") or "-"),
            str(d.get("output_tokens") or "-"),
            last_user or first,
            out,
        )
    console.print(t)


def cmd_step(trace: Trace, args) -> None:
    console = Console()
    events = trace.events
    if args.run:
        events = [e for e in events if e["run_id"] == args.run]
    events = [e for e in events if e.get("agent_step") == args.step]

    if not events:
        console.print(
            f"[red]No events match step={args.step}"
            f"{' run=' + args.run if args.run else ''}[/]"
        )
        return

    for e in events:
        title = (
            f"seq={e['seq']}  |  {e['event']}  |  "
            f"run={e['run_id'][-8:]}  |  step={e.get('agent_step')}"
        )
        content = json.dumps(e["data"], ensure_ascii=False, indent=2)
        if len(content) > 3500:
            content = content[:3500] + f"\n...[{len(content) - 3500} chars elided]..."
        console.print(Panel(content, title=title, expand=False, border_style="cyan"))


# ============================================================
#  Argparse
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctx-inspect",
        description="Inspect a ctx_debugger JSONL trace.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary", help="Overall stats and event histogram.")
    s.add_argument("trace")

    r = sub.add_parser("runs", help="List runs in the trace.")
    r.add_argument("trace")

    tl = sub.add_parser("timeline", help="Chronological event list.")
    tl.add_argument("trace")
    tl.add_argument("--run", help="Filter to one run_id (suffix match supported below).")

    c = sub.add_parser("compress", help="All compression cycles with stats.")
    c.add_argument("trace")

    l = sub.add_parser("llm", help="LLM calls with durations and tokens.")
    l.add_argument("trace")
    l.add_argument("--tag", choices=["main", "compression"])

    st = sub.add_parser("step", help="Dump every event for one agent step.")
    st.add_argument("trace")
    st.add_argument("--step", type=int, required=True)
    st.add_argument("--run")

    return p


def main() -> None:
    args = _build_parser().parse_args()
    trace = Trace(args.trace)

    # Allow --run to match by suffix (8-char short form)
    if getattr(args, "run", None):
        runs = trace.runs()
        if args.run not in runs:
            matches = [r for r in runs if r.endswith(args.run)]
            if len(matches) == 1:
                args.run = matches[0]
            elif len(matches) > 1:
                print(f"Ambiguous --run {args.run}: matches {matches}", file=sys.stderr)
                sys.exit(2)

    {
        "summary": cmd_summary,
        "runs": cmd_runs,
        "timeline": cmd_timeline,
        "compress": cmd_compress,
        "llm": cmd_llm,
        "step": cmd_step,
    }[args.cmd](trace, args)


if __name__ == "__main__":
    main()
