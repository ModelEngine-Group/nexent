#!/usr/bin/env python3
"""Download LongMemEval (S*) data from MemoryAgentBench on HuggingFace.

LongMemEval (S*) lives in the ``Accurate_Retrieval`` split of
``ai-hyz/MemoryAgentBench``. Rows whose ``metadata.source`` equals
``"longmemeval_s*"`` carry the 5 long dialogues (~355K tokens each, ~1.6M
characters of flattened conversation) plus 60 free-text questions per dialogue
(300 total).

This script downloads the split's parquet, extracts the five ``longmemeval_s*``
rows, and writes them to ``data/longmemeval_s_star.jsonl`` (one dialogue per
line; the literal ``*`` in the source name is sanitized to ``_star`` for the
filename).

Usage:
    python download_data.py

Requires ``huggingface_hub`` and ``pyarrow`` in the active environment (already
present in ``backend/.venv`` via the ``benchmark`` extra).
"""
import argparse
import json
import os

HF_REPO = "ai-hyz/MemoryAgentBench"
HF_FILE = "data/Accurate_Retrieval-00000-of-00001.parquet"
SOURCE_TAG = "longmemeval_s*"
OUTPUT_BASENAME = "longmemeval_s_star"


def main(output_dir: str):
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq

    print(f"Downloading {HF_FILE} from {HF_REPO} ...")
    try:
        path = hf_hub_download(HF_REPO, HF_FILE, repo_type="dataset")
    except Exception as exc:
        # SSL hiccups during HEAD revalidation are common; fall back to whatever
        # is already in the local HF cache.
        print(f"  online fetch failed ({type(exc).__name__}); "
              f"retrying with local_files_only=True ...")
        path = hf_hub_download(HF_REPO, HF_FILE, repo_type="dataset",
                               local_files_only=True)
    print(f"  cached at: {path}")

    rows = pq.read_table(path).to_pylist()
    dialogues = [r for r in rows if (r.get("metadata") or {}).get("source") == SOURCE_TAG]
    if not dialogues:
        sources = sorted({(r.get("metadata") or {}).get("source") for r in rows})
        raise SystemExit(f"No rows with source={SOURCE_TAG!r}. Available: {sources}")

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{OUTPUT_BASENAME}.jsonl")

    with open(out_path, "w", encoding="utf-8") as f:
        for i, row in enumerate(dialogues):
            md = row.get("metadata") or {}
            record = {
                "dialogue_index": i,
                "dialogue_id": f"{OUTPUT_BASENAME}_d{i}",
                "source": SOURCE_TAG,
                # Flattened-text rendering of the haystack, useful for the
                # baseline arm (truncate-to-window fallback).
                "context": row.get("context") or "",
                # The structured haystack: list[60] of list[2] of list[turn],
                # where each turn = {role, content, has_answer}.
                "haystack_sessions": md.get("haystack_sessions") or [],
                "questions": row.get("questions") or [],
                "answers": row.get("answers") or [],
                "question_types": md.get("question_types") or [],
                "question_dates": md.get("question_dates") or [],
                "question_ids": md.get("question_ids") or [],
            }
            ctx = record["context"]
            n_sess_groups = len(record["haystack_sessions"])
            n_atomic = sum(len(g) for g in record["haystack_sessions"]
                           if isinstance(g, list))
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  dialogue {i}: ctx_chars={len(ctx):>9d}  "
                  f"session_groups={n_sess_groups}  atomic_sessions={n_atomic}  "
                  f"questions={len(record['questions'])}")

    print(f"\nWrote {len(dialogues)} dialogues to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download LongMemEval (S*) data from MemoryAgentBench")
    parser.add_argument(
        "--output_dir",
        type=str,
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
        help="Directory to write the .jsonl file",
    )
    args = parser.parse_args()
    main(output_dir=args.output_dir)
