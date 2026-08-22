#!/usr/bin/env python3
"""Download EventQA data from the MemoryAgentBench dataset on HuggingFace.

EventQA lives in the ``Accurate_Retrieval`` split of ``ai-hyz/MemoryAgentBench``.
Rows whose ``metadata.source`` equals ``eventqa_full`` carry the five full novels
(each ~1.7M-3.2M characters) plus 100 six-choice "what happens next" questions.

This script downloads the split's parquet file, extracts the five ``eventqa_full``
rows, and writes them to ``data/eventqa_full.jsonl`` (one book per line).

Usage:
    python download_data.py
    python download_data.py --source eventqa_131072   # truncated 128K variant

Requires ``huggingface_hub`` and ``pyarrow`` in the active environment.
"""
import argparse
import json
import os

HF_REPO = "ai-hyz/MemoryAgentBench"
HF_FILE = "data/Accurate_Retrieval-00000-of-00001.parquet"

# Map a context prefix to a human-readable novel title. The five EventQA books
# always appear in this order in the parquet, but matching on the prefix keeps
# the labels correct even if the row order ever changes.
_BOOK_TITLES = [
    ("Part One \nCHAPTER I \nDEBBIE", "Gone with the Wind"),
    ("VOLUME I\nMIRACLE", "Les Miserables"),
    ("Chapter 1\nMarseilles", "The Count of Monte Cristo"),
    ("Whether I shall turn out to be the hero", "David Copperfield"),
    ("PART ONE\nChapter 1\nHappy families", "Anna Karenina"),
]


def _book_title(context: str, fallback_index: int) -> str:
    head = context.lstrip()
    for prefix, title in _BOOK_TITLES:
        if head.startswith(prefix.lstrip()):
            return title
    return f"book{fallback_index}"


def main(source: str, output_dir: str):
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq

    print(f"Downloading {HF_FILE} from {HF_REPO} ...")
    path = hf_hub_download(HF_REPO, HF_FILE, repo_type="dataset")
    print(f"  cached at: {path}")

    rows = pq.read_table(path).to_pylist()
    books = [r for r in rows if (r.get("metadata") or {}).get("source") == source]
    if not books:
        sources = sorted({(r.get("metadata") or {}).get("source") for r in rows})
        raise SystemExit(f"No rows with source={source!r}. Available sources: {sources}")

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{source}.jsonl")

    with open(out_path, "w", encoding="utf-8") as f:
        for i, row in enumerate(books):
            context = row.get("context") or ""
            md = row.get("metadata") or {}
            record = {
                "book_index": i,
                "book_id": f"{source}_book{i}",
                "book_title": _book_title(context, i),
                "source": source,
                "context": context,
                "questions": row.get("questions") or [],
                "answers": row.get("answers") or [],
                "previous_events": md.get("previous_events") or [],
                "qa_pair_ids": md.get("qa_pair_ids") or [],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  book {i}: {record['book_title']:<28} "
                  f"ctx_chars={len(context):>9d}  questions={len(record['questions'])}")

    print(f"\nWrote {len(books)} books to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download EventQA data from MemoryAgentBench")
    parser.add_argument(
        "--source",
        type=str,
        default="eventqa_full",
        choices=["eventqa_full", "eventqa_65536", "eventqa_131072"],
        help="Which EventQA variant to extract (default: eventqa_full)",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
        help="Directory to write the .jsonl file",
    )
    args = parser.parse_args()
    main(source=args.source, output_dir=args.output_dir)
