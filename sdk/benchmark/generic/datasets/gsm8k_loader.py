# -*- coding: utf-8 -*-
"""GSM8K dataset loader and Langfuse upload.

GSM8K (Grade School Math 8K) is a dataset of ~8.5K grade school math
word problems. Each problem has a question and a step-by-step solution
with a final numeric answer marked by "####".

Source: https://huggingface.co/datasets/openai/gsm8k

Usage:
    # Download and sample N=10, upload to Langfuse
    python gsm8k_loader.py --sample 10

    # Download full test set, upload to Langfuse
    python gsm8k_loader.py --split test

    # Custom dataset name
    python gsm8k_loader.py --sample 10 --dataset_name gsm8k-test-10
"""
import argparse
import json
import os
import random
import re
import sys


def download_gsm8k(split: str = "test", cache_dir: str = None) -> list[dict]:
    """Download GSM8K dataset from HuggingFace.

    Args:
        split: "train" or "test"
        cache_dir: Optional cache directory

    Returns:
        List of dicts with "question" and "answer" keys.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        print("ERROR: 'datasets' package not installed.")
        print("  Install with: pip install datasets")
        print("  Or: uv pip install datasets")
        sys.exit(1)

    print(f"Downloading GSM8K ({split} split)...")
    ds = load_dataset("openai/gsm8k", "main", split=split, cache_dir=cache_dir)
    print(f"  Loaded {len(ds)} examples")

    items = []
    for row in ds:
        items.append({
            "question": row["question"],
            "answer": row["answer"],  # Contains step-by-step solution + "#### <number>"
        })

    return items


def extract_gold_number(answer_text: str) -> str:
    """Extract the final numeric answer from GSM8K's answer field.

    GSM8K answers end with "#### <number>".
    """
    match = re.search(r"####\s*([\d,]+(?:\.\d+)?)", answer_text)
    if match:
        return match.group(1).replace(",", "")
    # Fallback: last number in text
    numbers = re.findall(r"[\d,]+(?:\.\d+)?", answer_text)
    return numbers[-1].replace(",", "") if numbers else answer_text


def upload_to_langfuse(items: list[dict], dataset_name: str, langfuse_client) -> int:
    """Upload GSM8K items to a Langfuse dataset.

    Args:
        items: List of dicts with "question" and "answer".
        dataset_name: Langfuse dataset name.
        langfuse_client: Langfuse client instance.

    Returns:
        Number of items uploaded.
    """
    # Create dataset (idempotent)
    try:
        langfuse_client.create_dataset(
            name=dataset_name,
            description=(
                f"GSM8K grade school math benchmark ({len(items)} samples). "
                "Each item has a math word problem and a step-by-step solution "
                "with a final numeric answer."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Math word problem"},
                },
                "required": ["question"],
            },
            expected_output_schema={
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "description": "Final numeric answer"},
                    "solution": {"type": "string", "description": "Full step-by-step solution"},
                },
                "required": ["answer"],
            },
        )
        print(f"  Created dataset '{dataset_name}'")
    except Exception:
        print(f"  Dataset '{dataset_name}' already exists, reusing")

    count = 0
    for i, item in enumerate(items):
        gold_number = extract_gold_number(item["answer"])

        langfuse_client.create_dataset_item(
            dataset_name=dataset_name,
            input={"question": item["question"]},
            expected_output={
                "answer": gold_number,
                "solution": item["answer"],
            },
            metadata={"index": i, "source": "gsm8k"},
        )
        count += 1

    print(f"  Uploaded {count} items")
    return count


def main():
    parser = argparse.ArgumentParser(description="Download GSM8K and upload to Langfuse")
    parser.add_argument(
        "--split", type=str, default="test", choices=["train", "test"],
        help="Dataset split to download (default: test)",
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        help="Random sample N items from the dataset (default: all)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for sampling (default: 42)",
    )
    parser.add_argument(
        "--dataset_name", type=str, default=None,
        help="Custom Langfuse dataset name (default: gsm8k-{split}[-n{sample}])",
    )
    parser.add_argument(
        "--cache_dir", type=str, default=None,
        help="HuggingFace cache directory",
    )
    parser.add_argument(
        "--save_jsonl", type=str, default=None,
        help="Also save sampled data as a local JSONL file",
    )
    args = parser.parse_args()

    # Download
    items = download_gsm8k(split=args.split, cache_dir=args.cache_dir)

    # Sample
    if args.sample and args.sample < len(items):
        random.seed(args.seed)
        items = random.sample(items, args.sample)
        print(f"  Sampled {len(items)} items (seed={args.seed})")

    # Save JSONL if requested
    if args.save_jsonl:
        os.makedirs(os.path.dirname(args.save_jsonl) or ".", exist_ok=True)
        with open(args.save_jsonl, "w", encoding="utf-8") as f:
            for item in items:
                gold_number = extract_gold_number(item["answer"])
                f.write(json.dumps({
                    "question": item["question"],
                    "answer": gold_number,
                    "solution": item["answer"],
                }, ensure_ascii=False) + "\n")
        print(f"  Saved JSONL to {args.save_jsonl}")

    # Upload to Langfuse
    dataset_name = args.dataset_name or (
        f"gsm8k-{args.split}" + (f"-n{len(items)}" if args.sample else "")
    )

    from dotenv import load_dotenv
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )))
    load_dotenv(os.path.join(project_root, ".env"))

    from langfuse import Langfuse
    langfuse_client = Langfuse()

    try:
        langfuse_client.auth_check()
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        print(f"Langfuse connected: {host}")
    except Exception as e:
        print(f"ERROR: Langfuse connection failed: {e}")
        sys.exit(1)

    upload_to_langfuse(items, dataset_name, langfuse_client)

    print(f"\nDone. Dataset '{dataset_name}' ready in Langfuse.")
    print("  Run experiment with:")
    print(f"    python run_experiment.py --dataset {dataset_name} --evaluators numeric_answer")


if __name__ == "__main__":
    main()
