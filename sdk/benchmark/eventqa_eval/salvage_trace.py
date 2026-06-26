#!/usr/bin/env python3
"""Salvage probe results from an interrupted ctx_debugger trace.

When an EventQA run dies mid-flight (network drop, OOM, …) the
``run_eventqa.py`` process never reaches the report-writing block, so
``outputs/<book_id>/summary.json`` is missing. The ctx_debugger trace however
has every probe's input and final_answer captured. This script walks the trace
and reconstructs per-probe results — compressed arm first, baseline arm second
— matching turns to items by their ORDER within each arm (probes run
sequentially through ``book.items`` with no retries).

It does NOT re-run any LLM call. It only reads the trace.

Usage:
    python salvage_trace.py <trace.jsonl> <book_index> [--out <dir>] [--schema default|narrative]

Default output dir: ``outputs/<book_id>_salvage/`` (sibling of the regular run
output dir). The merge script can combine this with a resumed run later.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: F401

from dataset import load_books
from eval_utils import score_mcq


def _load_events(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _split_turns(events):
    """Split flat events into one segment per eventqa_answerer agent_init."""
    turns = []
    current = None
    for e in events:
        if (e.get("event") == "agent_init"
                and e.get("data", {}).get("agent_name") == "eventqa_answerer"):
            if current is not None:
                turns.append(current)
            current = {"events": []}
        elif current is not None:
            current["events"].append(e)
    if current is not None:
        turns.append(current)
    return turns


def _classify_arm(turn) -> str:
    """compressed vs baseline — detect by the 'Here is the novel' marker."""
    for ev in turn["events"]:
        if ev.get("event") != "llm_call_begin":
            continue
        for m in ev.get("data", {}).get("input_messages", []) or []:
            text = m.get("text") or m.get("preview") or ""
            if "Here is the novel" in text:
                return "baseline"
        break
    return "compressed"


def _extract_answer(turn):
    """Return the last final_answer tool call's return_preview, or None."""
    ans = None
    for ev in turn["events"]:
        if (ev.get("event") == "tool_call_end"
                and ev.get("data", {}).get("tool") == "final_answer"):
            ans = ev.get("data", {}).get("return_preview")
    return ans


def _extract_final_summary(events):
    """Walk the trace for the LAST compress_end with a non-empty summary_after."""
    summary = None
    token_counts = None
    boundary = None
    num_chunks = None
    for e in events:
        if e.get("event") == "compress_end":
            d = e.get("data", {}) or {}
            s = d.get("summary_after")
            if s and "previous_summary" in (s or {}):
                ps = s.get("previous_summary")
                if ps:
                    summary = ps
                    boundary = s.get("compression_boundary")
            tc = d.get("token_counts")
            if tc:
                token_counts = tc
    # Count ingest rounds = eventqa_reader agent_init events
    num_chunks = sum(
        1 for e in events
        if e.get("event") == "agent_init"
        and e.get("data", {}).get("agent_name") == "eventqa_reader"
    )
    return {
        "previous_summary": summary,
        "compression_boundary": boundary,
        "token_counts": token_counts,
        "num_chunks": num_chunks,
    }


def salvage(trace_path: str, book_index: int, schema: str) -> dict:
    events = list(_load_events(trace_path))
    turns = _split_turns(events)

    # Detect arm boundary
    first_baseline = next(
        (i for i, t in enumerate(turns) if _classify_arm(t) == "baseline"),
        len(turns),
    )
    compressed_turns = turns[:first_baseline]
    baseline_turns = turns[first_baseline:]

    books = load_books(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
            "eventqa_full.jsonl",
        )
    )
    book = books[book_index]
    items = book.items

    def score_turns(arm_turns):
        out = []
        for k, t in enumerate(arm_turns):
            if k >= len(items):
                break
            it = items[k]
            ans = _extract_answer(t)
            if ans is None:
                out.append({
                    "qid": it.qid, "gold": it.gold, "answer": None,
                    "selected": "", "selected_index": -1,
                    "gold_index": it.options.index(it.gold) if it.gold in it.options else -1,
                    "correct": False, "score": 0.0, "match_type": "no_answer",
                })
            else:
                mcq = score_mcq(ans, it.options, it.gold)
                out.append({
                    "qid": it.qid, "gold": it.gold, "answer": ans,
                    "selected": mcq.selected, "selected_index": mcq.selected_index,
                    "gold_index": mcq.gold_index,
                    "correct": mcq.correct, "score": mcq.score,
                    "match_type": mcq.match_type,
                })
        return out

    compressed = score_turns(compressed_turns)
    baseline = score_turns(baseline_turns)

    comp_info = _extract_final_summary(events)

    def accuracy(rs):
        return sum(r["score"] for r in rs) / len(rs) if rs else 0.0

    bacc = accuracy(baseline)
    cacc = accuracy(compressed)
    retention = None
    if baseline and compressed:
        retention = cacc / bacc if bacc > 0 else 0.0
    token_reduction = None
    if comp_info["token_counts"]:
        tc = comp_info["token_counts"]
        unc = tc.get("last_uncompressed") or 0
        comp = tc.get("last_compressed") or 0
        if unc > 0:
            token_reduction = 1 - comp / unc

    return {
        "book_id": book.book_id,
        "book_title": book.book_title,
        "novel_chars": len(book.context),
        "num_questions": len(items),
        "schema_salvaged": schema,
        "compressed_turns": len(compressed_turns),
        "baseline_turns": len(baseline_turns),
        "baseline": {"accuracy": bacc, "n": len(baseline), "qid_range": [0, len(baseline) - 1] if baseline else None},
        "compressed": {
            schema: {
                "accuracy": cacc,
                "n": len(compressed),
                "memory_retention": retention,
                "token_reduction": token_reduction,
                "compression": comp_info,
            }
        },
        "predictions_compressed": compressed,
        "predictions_baseline": baseline,
    }


def main():
    ap = argparse.ArgumentParser(description="Salvage probe results from a ctx_debugger trace.")
    ap.add_argument("trace", help="Path to ctx_debugger JSONL trace.")
    ap.add_argument("--book_index", type=int, default=0)
    ap.add_argument("--schema", default="narrative",
                    help="Which schema this trace's compressed arm used (default/narrative).")
    ap.add_argument("--out_dir", default=None,
                    help="Output dir; default outputs/<book_id>_salvage/")
    args = ap.parse_args()

    report = salvage(args.trace, args.book_index, args.schema)

    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "outputs",
        f"{report['book_id']}_salvage",
    )
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in report.items()
                   if k not in ("predictions_compressed", "predictions_baseline")},
                  f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(out_dir, "predictions_compressed.jsonl"), "w", encoding="utf-8") as f:
        for r in report["predictions_compressed"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "predictions_baseline.jsonl"), "w", encoding="utf-8") as f:
        for r in report["predictions_baseline"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Salvage written to {out_dir}")
    print(f"  compressed: {report['compressed_turns']} turns "
          f"(acc={report['compressed'][args.schema]['accuracy']:.3f})")
    print(f"  baseline:   {report['baseline_turns']} turns "
          f"(acc={report['baseline']['accuracy']:.3f}) — "
          f"qids 0..{report['baseline']['n'] - 1} done, {100 - report['baseline']['n']} remaining")


if __name__ == "__main__":
    main()
