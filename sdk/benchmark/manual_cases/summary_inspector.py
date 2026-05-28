# -*- coding: utf-8 -*-
"""
Standalone Summary Inspector — quick evaluation of compression prompt/schema quality.

Completely independent from test_benchmark.py and the cases/ directory.
Uses compress_history_offline to compress history and checks whether the
resulting summary retains key information. No agent runs needed — just
one LLM call per inspection + text-based checks.

Use case:
  - Iterate on summary prompt / schema in summary_config.py
  - Verify that key facts survive compression without running full agent loops
  - Compare different ContextManagerConfig settings side-by-side

Directory layout (independent from cases/ and reports/):

    inspections/
    └── <name>/
        ├── history.json       # [{"role": "user|assistant", "content": "..."}]
        └── checks.json        # [{"description": "...", "must_contain": [...]}]

Result is written to inspections/<name>/_result.json (co-located with input).

Usage:
  python summary_inspector.py                          # all inspections
  python summary_inspector.py -n example_infra         # single inspection
  python summary_inspector.py --config my_config.json  # custom config overrides
  python summary_inspector.py --save-summary           # also save raw summary .txt
"""

import argparse
import json
import os
import sys
import glob

# ============ Path Setup ============
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: F401 — side-effect: adds sdk/, backend/ to sys.path

from dotenv import load_dotenv
load_dotenv()

from nexent.core.agents.agent_context import compress_history_offline, ContextManagerConfig
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.models.openai_llm import OpenAIModel

from eval_utils import eval_text


# ============ Config ============
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME")
LLM_API_URL = os.getenv("LLM_API_URL")

INSPECTIONS_DIR = "./inspections"


def create_model(temperature: float = 0.1):
    """Create an LLM model for offline compression."""
    from nexent.core.utils.observer import MessageObserver

    model_config = ModelConfig(
        cite_name="inspector_model",
        api_key=LLM_API_KEY,
        model_name=LLM_MODEL_NAME,
        url=LLM_API_URL,
        temperature=temperature,
        ssl_verify=False,
    )
    return OpenAIModel(
        observer=MessageObserver(),
        model_id=model_config.model_name,
        api_key=model_config.api_key,
        api_base=model_config.url,
        temperature=model_config.temperature,
        top_p=model_config.top_p,
        ssl_verify=model_config.ssl_verify,
    )


def history_to_pairs(history: list) -> list[tuple[str, str]]:
    """Convert [{role, content}] to [(user_text, assistant_text)] pairs.

    Consecutive user messages are merged; same for assistant messages,
    so the output is a clean alternating sequence of pairs.
    """
    pairs = []
    current_user = []
    current_assistant = []

    for entry in history:
        role = entry["role"]
        content = entry["content"]
        if role == "user":
            if current_assistant:
                pairs.append((
                    "\n".join(current_user).strip(),
                    "\n".join(current_assistant).strip(),
                ))
                current_user = []
                current_assistant = []
            current_user.append(content)
        elif role == "assistant":
            current_assistant.append(content)

    if current_user and current_assistant:
        pairs.append((
            "\n".join(current_user).strip(),
            "\n".join(current_assistant).strip(),
        ))

    return pairs


def build_config(overrides: dict = None) -> ContextManagerConfig:
    """Build ContextManagerConfig with optional field overrides."""
    config = ContextManagerConfig()
    if not overrides:
        return config

    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)
        else:
            print(f"WARNING: unknown config field '{key}', ignoring")

    return config


def run_inspection(
    inspection_dir: str,
    model,
    config: ContextManagerConfig,
) -> dict:
    """Run summary inspection for a single inspection set.

    Reads:
      - <inspection_dir>/history.json
      - <inspection_dir>/checks.json

    Writes:
      - <inspection_dir>/_result.json
      - <inspection_dir>/_summary.txt (optional, if --save-summary)

    Returns:
        dict with name, summary, checks, score, and compression metadata.
    """
    name = os.path.basename(inspection_dir)

    # Load history
    history_path = os.path.join(inspection_dir, "history.json")
    if not os.path.exists(history_path):
        print(f"  SKIP: history.json not found in {inspection_dir}")
        return {"name": name, "skipped": True, "reason": "no history.json"}

    with open(history_path, "r", encoding="utf-8") as f:
        history = json.load(f)

    # Load checks
    checks_path = os.path.join(inspection_dir, "checks.json")
    if not os.path.exists(checks_path):
        print(f"  SKIP: checks.json not found in {inspection_dir}")
        return {"name": name, "skipped": True, "reason": "no checks.json"}

    with open(checks_path, "r", encoding="utf-8") as f:
        checks = json.load(f)

    if not checks:
        print(f"  SKIP: checks.json is empty for {name}")
        return {"name": name, "skipped": True, "reason": "empty checks"}

    # Convert history to pairs
    pairs = history_to_pairs(history)
    print(f"  History: {len(history)} messages -> {len(pairs)} pairs")

    # Compress
    result = compress_history_offline(pairs=pairs, model=model, config=config)
    summary = result.get("summary") or ""
    is_fallback = result.get("is_fallback", False)
    is_incremental = result.get("is_incremental", False)
    input_chars = result.get("input_chars", 0)

    if not summary:
        print(f"  FAILED: compression returned no summary (fallback={is_fallback})")
        report = {
            "name": name,
            "summary": None,
            "is_fallback": is_fallback,
            "input_chars": input_chars,
            "checks": [],
            "score": 0.0,
        }
        _write_result(inspection_dir, report)
        return report

    print(f"  Summary: {len(summary)} chars, fallback={is_fallback}, incremental={is_incremental}")

    # Evaluate checks against summary
    check_results = []
    for check in checks:
        eval_result = eval_text(summary, check)
        check_results.append({
            "check": check,
            "passed": eval_result.passed,
            "score": eval_result.score,
            "details": eval_result.details,
        })

    total_score = sum(r["score"] for r in check_results) / max(len(check_results), 1)
    passed_count = sum(1 for r in check_results if r["passed"])

    print(f"  Result: {passed_count}/{len(check_results)} checks passed, score={total_score:.2f}")

    for r in check_results:
        if not r["passed"]:
            desc = r["check"].get("description", "")
            keywords = r["check"].get("must_contain", r["check"].get("must_contain_any", []))
            print(f"    FAIL: {desc} -- missing {keywords}")

    report = {
        "name": name,
        "summary": summary,
        "is_fallback": is_fallback,
        "is_incremental": is_incremental,
        "input_chars": input_chars,
        "summary_chars": len(summary),
        "checks": check_results,
        "score": total_score,
        "passed": passed_count,
        "total": len(check_results),
    }

    _write_result(inspection_dir, report)
    return report


def _write_result(inspection_dir: str, report: dict):
    """Write _result.json (without full summary to keep file small) and optional _summary.txt."""
    result_path = os.path.join(inspection_dir, "_result.json")
    result_out = {k: v for k, v in report.items() if k != "summary"}
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result_out, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Result saved to {result_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Standalone Summary Inspector -- quick compression quality check"
    )
    parser.add_argument(
        "-n", "--name",
        type=str,
        default=None,
        help="Run a specific inspection by name (directory under inspections/)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a JSON file with ContextManagerConfig field overrides",
    )
    parser.add_argument(
        "--save-summary",
        action="store_true",
        default=False,
        help="Also save the raw summary text to _summary.txt alongside the result",
    )
    args = parser.parse_args()

    # Discover inspections
    if args.name:
        inspection_dirs = [os.path.join(INSPECTIONS_DIR, args.name)]
        if not os.path.isdir(inspection_dirs[0]):
            print(f"ERROR: inspection directory not found: {inspection_dirs[0]}")
            sys.exit(1)
    else:
        inspection_dirs = sorted(glob.glob(os.path.join(INSPECTIONS_DIR, "*/history.json")))
        inspection_dirs = [os.path.dirname(p) for p in inspection_dirs]

    if not inspection_dirs:
        print(f"No inspections found under {INSPECTIONS_DIR}/*/\n"
              f"Create one with: mkdir -p {INSPECTIONS_DIR}/my_test\n"
              f"Then add history.json and checks.json")
        sys.exit(1)

    # Build config
    config_overrides = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            config_overrides = json.load(f)

    config = build_config(config_overrides)
    config.enabled = True

    # Create model
    model = create_model()

    # Run inspection for each
    all_results = []
    for inspection_dir in inspection_dirs:
        name = os.path.basename(inspection_dir)
        print(f"\n===== Inspecting: {name} =====")

        report = run_inspection(inspection_dir, model, config)
        all_results.append(report)

        # Optionally save raw summary text
        if args.save_summary and report.get("summary"):
            summary_path = os.path.join(inspection_dir, "_summary.txt")
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(report["summary"])
            print(f"  Summary saved to {summary_path}")

    # Print overall summary
    print("\n===== Overall =====")
    for r in all_results:
        if r.get("skipped"):
            print(f"  {r['name']}: SKIPPED ({r['reason']})")
        else:
            print(f"  {r['name']}: {r.get('passed', 0)}/{r.get('total', 0)} passed, score={r.get('score', 0):.2f}")

    active = [r for r in all_results if not r.get("skipped")]
    if active:
        avg_score = sum(r.get("score", 0) for r in active) / max(len(active), 1)
        print(f"\n  Average score: {avg_score:.2f}")


if __name__ == "__main__":
    main()