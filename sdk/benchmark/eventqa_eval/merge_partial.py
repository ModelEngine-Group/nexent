#!/usr/bin/env python3
"""Merge a salvaged trace + a resumed run into the canonical book output.

After an interrupted EventQA run, the pipeline becomes:

    1. salvage_trace.py  ->  outputs/<book_id>_salvage/{summary,predictions_*}.jsonl
    2. run_eventqa.py --skip_compressed --question_start N
                        ->  outputs/<book_id>/{summary,predictions}.jsonl    (NEW partial)
    3. merge_partial.py  ->  outputs/<book_id>/{summary,predictions}.jsonl    (UNIFIED)

The merge takes:
  - All 100 compressed-arm probe results from the salvage.
  - Baseline probe results from the salvage for qids 0..N-1.
  - Baseline probe results from the resumed run for qids N..99 (overwrites any
    overlap, so item N is taken from the fresh resumed run since it was the one
    interrupted).

Outputs match the format ``run_eventqa.py`` writes natively.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: F401


def _qnum(qid: str) -> int:
    m = re.search(r"no(\d+)$", qid or "")
    return int(m.group(1)) if m else -1


def _read_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main():
    ap = argparse.ArgumentParser(description="Merge salvaged + resumed EventQA outputs.")
    ap.add_argument("--book_id", default="eventqa_full_book0")
    ap.add_argument("--schema", default="narrative")
    ap.add_argument("--resume_start_qid", type=int, default=43,
                    help="The qid number at which the resumed run started.")
    ap.add_argument("--outputs_dir", default=None,
                    help="Parent outputs dir; default = eventqa_eval/outputs/")
    args = ap.parse_args()

    base = args.outputs_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "outputs"
    )
    salvage_dir = os.path.join(base, f"{args.book_id}_salvage")
    resume_dir = os.path.join(base, args.book_id)
    if not os.path.isdir(salvage_dir):
        sys.exit(f"salvage dir not found: {salvage_dir}")
    if not os.path.isdir(resume_dir):
        sys.exit(f"resumed-run dir not found: {resume_dir}")

    # --- salvage ---
    salvage_sum = json.load(open(os.path.join(salvage_dir, "summary.json")))
    salvage_comp = _read_jsonl(os.path.join(salvage_dir, "predictions_compressed.jsonl"))
    salvage_base = _read_jsonl(os.path.join(salvage_dir, "predictions_baseline.jsonl"))

    # --- resumed run ---
    resume_sum = json.load(open(os.path.join(resume_dir, "summary.json")))
    resume_preds = _read_jsonl(os.path.join(resume_dir, "predictions.jsonl"))

    # Compressed arm: all 100 from salvage.
    # Baseline arm: salvage qids 0..(resume_start_qid-1), then resume qids resume_start_qid..99.
    base_by_qid = {}
    for r in salvage_base:
        n = _qnum(r["qid"])
        if 0 <= n < args.resume_start_qid:
            base_by_qid[r["qid"]] = r
    for r in resume_preds:
        b = r.get("baseline")
        if not b:
            continue
        n = _qnum(r["qid"])
        if n >= args.resume_start_qid:
            base_by_qid[r["qid"]] = {
                "qid": r["qid"], "gold": r.get("gold"),
                "answer": b.get("answer"), "selected": b.get("selected"),
                "correct": b.get("correct"), "score": 1.0 if b.get("correct") else 0.0,
                "match_type": b.get("match_type"),
            }

    # Build unified predictions in run_eventqa format
    by_qid = {}
    for r in salvage_comp:
        by_qid.setdefault(r["qid"], {"qid": r["qid"], "gold": r["gold"]})
        by_qid[r["qid"]].setdefault("compressed", {})[args.schema] = {
            "answer": r["answer"], "selected": r["selected"],
            "correct": r["correct"], "match_type": r["match_type"],
        }
    for qid, r in base_by_qid.items():
        by_qid.setdefault(qid, {"qid": qid, "gold": r.get("gold")})
        by_qid[qid]["baseline"] = {
            "answer": r["answer"], "selected": r["selected"],
            "correct": r["correct"], "match_type": r["match_type"],
        }
    predictions = sorted(by_qid.values(), key=lambda x: _qnum(x["qid"]))

    # Aggregate metrics
    base_results = [(_qnum(r["qid"]), r) for r in base_by_qid.values()]
    base_results.sort(key=lambda x: x[0])
    comp_results = sorted(salvage_comp, key=lambda r: _qnum(r["qid"]))

    bacc = sum(1.0 if r["correct"] else 0.0 for _, r in base_results) / max(len(base_results), 1)
    cacc = sum(r["score"] for r in comp_results) / max(len(comp_results), 1)
    retention = cacc / bacc if bacc > 0 else 0.0

    # Pull compression metadata from salvage's compressed/<schema>/compression
    comp_meta = salvage_sum["compressed"][args.schema]["compression"]
    token_reduction = salvage_sum["compressed"][args.schema].get("token_reduction")

    summary = {
        "book_id": args.book_id,
        "book_title": salvage_sum.get("book_title"),
        "novel_chars": salvage_sum.get("novel_chars"),
        "num_questions": salvage_sum.get("num_questions"),
        "baseline": {"accuracy": bacc, "n": len(base_results)},
        "compressed": {
            args.schema: {
                "accuracy": cacc,
                "n": len(comp_results),
                "memory_retention": retention,
                "token_reduction": token_reduction,
                "compression": comp_meta,
            }
        },
        "_merge_provenance": {
            "salvage_dir": salvage_dir,
            "resume_dir": resume_dir,
            "resume_start_qid": args.resume_start_qid,
            "baseline_from_salvage": sum(1 for _, r in base_results if _qnum(r["qid"]) < args.resume_start_qid),
            "baseline_from_resume": sum(1 for _, r in base_results if _qnum(r["qid"]) >= args.resume_start_qid),
        },
    }

    # Write to the canonical book outputs dir
    out_dir = os.path.join(base, args.book_id)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(out_dir, "predictions.jsonl"), "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"Merged to {out_dir}")
    print(f"  baseline N={len(base_results)} acc={bacc:.3f}")
    print(f"  compressed[{args.schema}] N={len(comp_results)} acc={cacc:.3f}")
    print(f"  retention={retention:.3f}  token_reduction={token_reduction}")
    print(f"  provenance: baseline {summary['_merge_provenance']['baseline_from_salvage']} from salvage "
          f"+ {summary['_merge_provenance']['baseline_from_resume']} from resume run")


if __name__ == "__main__":
    main()
