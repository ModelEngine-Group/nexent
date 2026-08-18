#!/usr/bin/env python3
"""Tag gaia-level1 dataset items and traces with category metadata.

Reads the 5 GAIA Level 1 subset JSONL files to build a task_id -> category
mapping, then updates:
  1. Each dataset item in gaia-level1 with metadata.category
  2. Each trace in the specified run with:
     a. metadata.category (for trace detail view)
     b. A CATEGORICAL score named "category" (for run table column filtering)

The CATEGORICAL score is what makes category appear as a filterable column
in the Langfuse dataset run table UI.

Usage:
    backend/.venv/bin/python sdk/benchmark/generic/tools/gaia/tag_categories.py
    backend/.venv/bin/python sdk/benchmark/generic/tools/gaia/tag_categories.py --dataset gaia-level1 --run-name gaia-level1-base-en
    backend/.venv/bin/python sdk/benchmark/generic/tools/gaia/tag_categories.py --run-name my-new-run
    backend/.venv/bin/python sdk/benchmark/generic/tools/gaia/tag_categories.py --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


GENERIC_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(GENERIC_DIR))

try:
    from ...common.benchmark_paths import DATASET_ROOT
except ImportError:
    from common.benchmark_paths import DATASET_ROOT

load_dotenv()
load_dotenv(GENERIC_DIR.parents[2] / ".env")

DATASET_DIR = DATASET_ROOT / "gaia_level1"

SUBSET_FILES = {
    "reasoning": "gaia_level1_reasoning.jsonl",
    "web_search": "gaia_level1_web_search.jsonl",
    "file_parse": "gaia_level1_file_parse.jsonl",
    "image": "gaia_level1_image.jsonl",
    "audio": "gaia_level1_audio.jsonl",
}


def build_category_mapping() -> dict[str, str]:
    """Build task_id -> category mapping from the 5 subset JSONL files."""
    mapping = {}
    for category, filename in SUBSET_FILES.items():
        filepath = DATASET_DIR / filename
        if not filepath.exists():
            print(f"ERROR: {filepath} not found")
            sys.exit(1)
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                task_id = obj.get("task_id")
                if task_id:
                    if task_id in mapping:
                        print(f"WARNING: duplicate task_id {task_id} in {category} and {mapping[task_id]}")
                    mapping[task_id] = category

    print(f"Built mapping: {len(mapping)} task_ids across {len(SUBSET_FILES)} categories")
    for cat in SUBSET_FILES:
        count = sum(1 for v in mapping.values() if v == cat)
        print(f"  {cat}: {count}")
    return mapping


def update_dataset_items(lf, dataset_name: str, mapping: dict[str, str], dry_run: bool) -> int:
    """Update dataset items with category metadata."""
    dataset = lf.get_dataset(dataset_name)
    items = dataset.items
    print(f"\nDataset '{dataset_name}': {len(items)} items")

    updated = 0
    unmatched = 0

    for item in items:
        inp = item.input or {}
        task_id = inp.get("task_id", "")

        if task_id not in mapping:
            unmatched += 1
            print(f"  SKIP: no category for task_id={task_id[:12]}...")
            continue

        category = mapping[task_id]
        existing_meta = item.metadata or {}

        if existing_meta.get("category") == category:
            updated += 1
            continue

        if dry_run:
            print(f"  [DRY] {task_id[:12]}... -> {category}")
            updated += 1
            continue

        # Upsert dataset item with updated metadata
        new_meta = {**existing_meta, "category": category}
        lf.create_dataset_item(
            dataset_name=dataset_name,
            input=item.input,
            expected_output=item.expected_output,
            metadata=new_meta,
            id=item.id,
        )
        updated += 1

    lf.flush()
    print(f"  Updated: {updated}, Unmatched: {unmatched}")
    return updated


def update_traces(lf, dataset_name: str, run_name: str, mapping: dict[str, str], dry_run: bool) -> int:
    """Update traces in a dataset run with category metadata + CATEGORICAL score.

    Two things are written per trace:
      1. metadata.category - visible in trace detail view
      2. A CATEGORICAL score named "category" - appears as a filterable column
         in the Langfuse dataset run table UI
    """
    import requests

    host = os.environ.get("LANGFUSE_HOST", "").rstrip("/")
    pub_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sec_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    auth = (pub_key, sec_key)

    # Get dataset ID
    resp = requests.get(
        f"{host}/api/public/datasets/{dataset_name}",
        auth=auth,
        timeout=30,
    )
    resp.raise_for_status()
    dataset_id = resp.json()["id"]

    # Get all run items
    all_run_items = []
    page = 1
    while True:
        resp = requests.get(
            f"{host}/api/public/dataset-run-items",
            params={"datasetId": dataset_id, "runName": run_name, "page": page, "limit": 50},
            auth=auth,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        all_run_items.extend(data.get("data", []))
        meta = data.get("meta", {})
        if page >= meta.get("totalPages", 1):
            break
        page += 1

    print(f"\nRun '{run_name}': {len(all_run_items)} run items")

    scores_created = 0
    meta_updated = 0
    unmatched = 0

    for ri in all_run_items:
        trace_id = ri.get("traceId")
        if not trace_id:
            continue

        trace = lf.get_trace(trace_id)
        inp = trace.input or {}
        task_id = inp.get("task_id", "")

        if task_id not in mapping:
            unmatched += 1
            continue

        category = mapping[task_id]

        existing_cat_scores = [
            s for s in (trace.scores or [])
            if s.name == "category" and getattr(s, "string_value", None) == category
        ]
        if existing_cat_scores:
            meta_updated += 1
            continue

        if dry_run:
            score = "PASS" if any(
                s.name in ("gaia_exact_match", "exact_match") and s.value >= 1.0
                for s in (trace.scores or [])
            ) else "FAIL"
            print(f"  [DRY] {task_id[:12]}... -> {category} ({score})")
            meta_updated += 1
            continue

        existing_meta = trace.metadata or {}
        new_meta = {**existing_meta, "category": category}
        lf.trace(id=trace_id, metadata=new_meta)

        resp = requests.post(
            f"{host}/api/public/scores",
            auth=auth,
            json={
                "traceId": trace_id,
                "name": "category",
                "value": category,
                "dataType": "CATEGORICAL",
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            scores_created += 1
        else:
            print(f"  ERROR creating score for {trace_id}: {resp.status_code} {resp.text[:100]}")

        meta_updated += 1

    lf.flush()
    print(f"  Scores: {scores_created} created")
    print(f"  Updated: {meta_updated}, Unmatched: {unmatched}")
    return meta_updated


def main():
    parser = argparse.ArgumentParser(description="Tag gaia-level1 items with category metadata")
    parser.add_argument("--dataset", type=str, default="gaia-level1",
                        help="Langfuse dataset name (default: gaia-level1)")
    parser.add_argument("--run-name", type=str, default="gaia-level1-base-en",
                        help="Run name to tag traces (default: gaia-level1-base-en)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing")
    parser.add_argument("--skip-dataset-items", action="store_true",
                        help="Skip updating dataset items (traces only)")
    parser.add_argument("--skip-traces", action="store_true",
                        help="Skip updating traces (dataset items only)")
    args = parser.parse_args()

    mapping = build_category_mapping()

    from langfuse import Langfuse
    lf = Langfuse()
    try:
        lf.auth_check()
        print(f"Langfuse connected: {os.environ.get('LANGFUSE_HOST')}")
    except Exception as e:
        print(f"ERROR: Langfuse connection failed: {e}")
        sys.exit(1)

    if not args.skip_dataset_items:
        update_dataset_items(lf, args.dataset, mapping, args.dry_run)

    if not args.skip_traces:
        update_traces(lf, args.dataset, args.run_name, mapping, args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
