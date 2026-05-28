"""Calibrate token_threshold in case.json files based on actual history token counts.

For each case under ./cases/, computes the token count of history.json PLUS
the system prompt tokens (using the same estimate_tokens_text() used at runtime),
then writes that value into case.json's compressed_config.token_threshold so
compression triggers precisely when the full context reaches this size.

The threshold must account for system_prompt + history, because the ContextManager
checks token count against the full message list (which includes system prompt).

Uses the same BENCHMARK_SYSTEM_PROMPT as test_benchmark.py for consistency.

Usage:
    python calibrate_thresholds.py [--cases-root ./cases] [--system-prompt <text>] [--dry-run]
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import paths  # noqa: F401 — side-effect: adds sdk/ to sys.path

from nexent.core.utils.token_estimation import estimate_tokens_text

# Same lean benchmark prompt as test_benchmark.py — kept in sync.
BENCHMARK_SYSTEM_PROMPT = """You are a helpful assistant. Answer the user's questions based on the conversation history and your knowledge.

- Be precise and concise.
- When the answer depends on information from earlier conversation, refer to it accurately.
- Do not fabricate information you do not know.
- Use final_answer to submit your response.

Now start!"""


def calibrate_thresholds(
    cases_root: str = "./cases",
    system_prompt: str = None,
    dry_run: bool = False,
) -> list[dict]:
    """Calibrate token_threshold in every case.json under cases_root.

    token_threshold = system_prompt_tokens + history_tokens

    Args:
        cases_root: Directory containing case subdirectories.
        system_prompt: System prompt string. Defaults to BENCHMARK_SYSTEM_PROMPT
                       (matching test_benchmark.py runtime).
        dry_run: If True, compute but do not write files.

    Returns:
        List of dicts with calibration details for each case.
    """
    sp = system_prompt if system_prompt is not None else BENCHMARK_SYSTEM_PROMPT
    sp_tokens = estimate_tokens_text(sp)

    results = []
    case_paths = sorted(glob.glob(os.path.join(cases_root, "*/case.json")))

    if not case_paths:
        print(f"No cases found under {cases_root}")
        return results

    print(f"System prompt tokens: {sp_tokens}")

    for case_path in case_paths:
        case_dir = os.path.dirname(case_path)
        case_name = os.path.basename(case_dir)

        with open(case_path, "r", encoding="utf-8") as f:
            case = json.load(f)

        history_relpath = case.get("history_file", "history.json")
        history_abspath = os.path.join(case_dir, history_relpath)

        if not os.path.exists(history_abspath):
            print(f"  SKIP {case_name}: {history_relpath} not found")
            continue

        with open(history_abspath, "r", encoding="utf-8") as f:
            history = json.load(f)

        history_text = "".join(msg["content"] for msg in history)
        history_tokens = estimate_tokens_text(history_text)
        total_tokens = sp_tokens + history_tokens

        old_threshold = case.get("compressed_config", {}).get("token_threshold")
        changed = old_threshold != total_tokens

        results.append({
            "case": case_name,
            "old_threshold": old_threshold,
            "new_threshold": total_tokens,
            "history_tokens": history_tokens,
            "system_prompt_tokens": sp_tokens,
            "changed": changed,
        })

        if changed:
            case.setdefault("compressed_config", {})["token_threshold"] = total_tokens
            if not dry_run:
                with open(case_path, "w", encoding="utf-8") as f:
                    json.dump(case, f, ensure_ascii=False, indent=2)
                print(
                    f"  {case_name}: token_threshold {old_threshold} -> {total_tokens} "
                    f"(sp={sp_tokens} + history={history_tokens})"
                )
            else:
                print(
                    f"  {case_name}: token_threshold {old_threshold} -> {total_tokens} "
                    f"(sp={sp_tokens} + history={history_tokens}) [dry-run]"
                )
        else:
            print(f"  {case_name}: token_threshold already {total_tokens}, no change")

    changed_count = sum(1 for r in results if r["changed"])
    if dry_run:
        print(f"\nDry-run: {changed_count} case(s) would be calibrated (no files written).")
    else:
        print(f"\nCalibrated {changed_count} case(s).")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Calibrate token_threshold in case.json files")
    parser.add_argument(
        "--cases-root", default="./cases",
        help="Root directory containing case subdirectories (default: ./cases)",
    )
    parser.add_argument(
        "--system-prompt", default=None,
        help="Custom system prompt string (default: build from agent_runner template)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute new thresholds but do not write to case.json files",
    )
    args = parser.parse_args()
    calibrate_thresholds(
        cases_root=args.cases_root,
        system_prompt=args.system_prompt,
        dry_run=args.dry_run,
    )