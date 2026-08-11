#!/usr/bin/env python3
"""
Unified benchmark runner for Nexent Agent evaluation.

This script replaces run_experiment.py and re_evaluate.py, providing a single
entry point for running benchmark experiments with Nexent Agents.

It can load agent configuration from a YAML file (exported by export_agent_config.py)
and allows CLI arguments to override YAML values.

Usage:
    # Run new experiment with agent config
    python run_benchmark.py \\
        --agent-config configs/agent_7.yaml \\
        --dataset gsm8k-n10 \\
        --evaluators numeric_answer \\
        --run-name gsm8k-with-math-assistant

    # Override YAML config with CLI args
    python run_benchmark.py \\
        --agent-config configs/agent_7.yaml \\
        --dataset gsm8k-n10 \\
        --max-steps 20 \\
        --temperature 0.2 \\
        --evaluators numeric_answer em f1

    # Rescore existing traces (no LLM calls)
    python run_benchmark.py \\
        --rescore \\
        --dataset gsm8k-n10 \\
        --existing-run gsm8k-deepseek-v4-flash-n10 \\
        --evaluators em f1 exact_match

    # Upload dataset and run experiment
    python run_benchmark.py \\
        --agent-config configs/agent_7.yaml \\
        --dataset my-benchmark \\
        --upload data/test.jsonl \\
        --evaluators numeric_answer

YAML config file structure (see export_agent_config.py):
    agent_info:
      display_name: Math Assistant
      ...
    agent_config:
      max_steps: 15
      enable_context_manager: true
      ...
    prompts:
      duty_prompt: |
        You are a professional mathematics assistant...
      constraint_prompt: ""
      few_shots_prompt: ""
    tools: [...]
    sub_agents: [...]
    skills: [...]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv


# Add current directory (generic/) and parent (sdk/benchmark/) to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from common.benchmark_paths import ARTIFACT_ROOT
    from common.secret_refs import resolve_env_references
except ImportError:  # Package import in tests.
    from .common.benchmark_paths import ARTIFACT_ROOT
    from .common.secret_refs import resolve_env_references

# Load environment variables
load_dotenv()
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")


def load_agent_config(config_path: str) -> dict:
    """Load YAML agent configuration and resolve strict environment references."""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return resolve_env_references(config or {})


def load_parity_snapshot(snapshot_path: str) -> dict:
    """Load a production parity snapshot from JSON or YAML."""
    with open(snapshot_path, "r", encoding="utf-8") as handle:
        if snapshot_path.endswith(".json"):
            return json.load(handle)
        return yaml.safe_load(handle)


def select_dataset_items(
    items: list,
    *,
    item_limit: int | None = None,
    item_ids: list[str] | None = None,
) -> list:
    """Select a deterministic dataset subset and reject unresolved item IDs."""
    if item_limit is not None and item_ids:
        raise ValueError("--item-limit cannot be combined with --item-id")
    if not item_ids:
        return items[:item_limit] if item_limit is not None else list(items)

    requested = [str(item_id) for item_id in item_ids]
    if len(requested) != len(set(requested)):
        raise ValueError("--item-id contains duplicate values")
    requested_set = set(requested)
    selected = [item for item in items if str(item.id) in requested_set]
    resolved = {str(item.id) for item in selected}
    missing = sorted(requested_set - resolved)
    if missing:
        raise ValueError(
            "Requested dataset item IDs were not found: " + ", ".join(missing)
        )
    return selected


def upload_jsonl(dataset_name: str, jsonl_path: str,
                 input_key: str = "question", output_key: str = "answer") -> int:
    """Upload a JSONL file as a Langfuse dataset."""
    from langfuse import Langfuse
    lf = Langfuse()

    try:
        lf.create_dataset(name=dataset_name)
        print(f"  Created dataset '{dataset_name}'")
    except Exception:
        print(f"  Dataset '{dataset_name}' already exists")

    count = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"  WARNING: skipping line {line_num} (invalid JSON)")
                continue

            inp = {input_key: obj.get(input_key, "")}
            for k, v in obj.items():
                if k not in (input_key, output_key):
                    inp[k] = v

            exp_out = {output_key: obj.get(output_key, "")} if output_key in obj else None

            lf.create_dataset_item(
                dataset_name=dataset_name,
                input=inp,
                expected_output=exp_out,
            )
            count += 1

    lf.flush()
    print(f"  Uploaded {count} items from {jsonl_path}")
    return count


def run_experiment(dataset_name: str, task_fn, evaluator_fns: list,
                   run_name: str, max_concurrency: int = 1,
                   manifest_context: dict | None = None,
                   item_limit: int | None = None,
                   item_ids: list[str] | None = None,
                   exa_cache_controller=None):
    """Run experiment using Langfuse v2 SDK: the trace, score, and link pattern."""
    from langfuse import Langfuse
    lf = Langfuse()

    dataset = lf.get_dataset(dataset_name)
    items = select_dataset_items(
        dataset.items,
        item_limit=item_limit,
        item_ids=item_ids,
    )
    n = len(items)
    print(f"  {n} items loaded")

    if n == 0:
        print("ERROR: Dataset is empty.")
        return

    print(f"\n{'='*60}")
    print(f"Running experiment: {run_name}")
    print(f"  Dataset:      {dataset_name} ({n} items)")
    print(f"  Model:        {os.environ.get('LLM_MODEL_NAME', 'unknown')}")
    print(f"{'='*60}\n")

    total_scores = {}
    passed = 0
    failed = 0
    agg_compression_calls = 0
    agg_compression_input_tokens = 0
    agg_summary_cache_hits = 0
    agg_provider_cache_available_calls = 0
    agg_provider_cache_hit_calls = 0
    agg_provider_cached_tokens = 0
    agg_provider_input_tokens = 0
    agg_wall_clock_seconds = 0.0
    agg_peak_context_tokens = 0
    agg_net_token_saving = 0
    item_web_evidence = {}
    manifest = None
    manifest_path = None
    dataset_item_ids = [str(item.id) for item in items]
    dataset_version = str(getattr(dataset, "version", "") or "") or None

    if manifest_context is not None:
        from provenance.experiment_manifest import manifest_path

        artifact_path = manifest_path(
            ARTIFACT_ROOT / "manifests",
            run_name,
        )
        if artifact_path.exists():
            raise FileExistsError(
                f"Run '{run_name}' already has a manifest: {artifact_path}"
            )
        from tools.web_evidence import web_evidence_artifact_path

        web_artifact_path = web_evidence_artifact_path(
            ARTIFACT_ROOT / "web_evidence",
            run_name,
        )
        if web_artifact_path.exists():
            raise FileExistsError(
                f"Run '{run_name}' already has web evidence: {web_artifact_path}"
            )

    for i, item in enumerate(items):
        q_preview = str(item.input)[:60] if item.input else ""
        print(f"[{i+1}/{n}] {q_preview}...", end=" ", flush=True)

        trace = lf.trace(
            name=f"benchmark-{dataset_name}",
            input=item.input,
            metadata={"run_name": run_name, "item_index": i},
        )

        try:
            output = task_fn(item=item)
        except Exception as e:
            print(f"ERROR: {e}")
            output = {"final_answer": "", "errors": [str(e)]}

        required_output_fields = {
            "agent_config",
            "compression",
            "model_config",
            "provider_cache",
            "system_prompt",
            "parity_snapshot",
        }
        missing_output_fields = sorted(required_output_fields - output.keys())
        if missing_output_fields:
            raise RuntimeError(
                "Benchmark task output is incomplete; refusing to score or link "
                f"an invalid run item. Missing: {', '.join(missing_output_fields)}; "
                f"errors={output.get('errors', [])}"
            )

        if manifest is None and manifest_context is not None:
            from provenance.experiment_manifest import build_manifest, write_manifest_exclusive

            agent_config = output.get("agent_config", {})
            expected_snapshot = manifest_context.get("expected_parity_snapshot")
            parity_gate = {
                "passed": None,
                "simulation_fidelity": "mechanism_only",
            }
            if expected_snapshot is not None:
                from provenance.parity_snapshot import (
                    diff_parity_snapshots,
                    simulation_fidelity_for_snapshot,
                )
                parity_diff = diff_parity_snapshots(
                    expected_snapshot,
                    output.get("parity_snapshot", {}),
                )
                if not parity_diff["passed"]:
                    raise RuntimeError(
                        "Parity snapshot gate failed: "
                        + json.dumps(parity_diff, ensure_ascii=False, sort_keys=True)
                    )
                parity_gate = {
                    "passed": True,
                    "simulation_fidelity": simulation_fidelity_for_snapshot(expected_snapshot),
                    "diff": parity_diff,
                }
            build_context = {
                key: value
                for key, value in manifest_context.items()
                if key != "expected_parity_snapshot"
            }
            manifest = build_manifest(
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                dataset_item_ids=dataset_item_ids,
                run_name=run_name,
                system_prompt=output.get("system_prompt", ""),
                model_config=output.get("model_config", {}),
                agent_config=agent_config,
                parity_snapshot=output.get("parity_snapshot", {}),
                parity_gate=parity_gate,
                **build_context,
            )
            manifest_path = write_manifest_exclusive(
                manifest,
                ARTIFACT_ROOT / "manifests",
            )
            print(f"\n  Resolved manifest: {manifest_path}")

        trace.update(
            output=output,
            metadata={
                "run_name": run_name,
                "item_index": i,
                "system_prompt": output.get("system_prompt", ""),
                "model_config": output.get("model_config", {}),
                "agent_config": output.get("agent_config", {}),
                "compression": output.get("compression", {}),
                "provider_cache": output.get("provider_cache", {}),
                "web_evidence": output.get("web_evidence", {}),
                "manifest_hash": manifest.get("manifest_hash") if manifest else None,
                "manifest_path": str(manifest_path) if manifest_path else None,
            },
        )
        item_web_evidence[str(item.id)] = output.get("web_evidence", {})

        steps = output.get("steps", [])
        for step in steps:
            step_num = step.get("step_number", "?")
            if step_num == "final_answer":
                trace.span(
                    name="final_answer",
                    input={"query": step.get("query", "")},
                    output={"answer": step.get("main_output", "")},
                    metadata={"token_usage": step.get("token_usage")},
                )
            else:
                token_usage = step.get("token_usage") or {}
                trace.generation(
                    name=f"model_step_{step_num}",
                    model=(output.get("model_config") or {}).get("model_name"),
                    input={
                        "query": step.get("query", ""),
                        "thinking": step.get("thinking", ""),
                        "deep_thinking": step.get("deep_thinking", ""),
                    },
                    output={
                        "main_output": step.get("main_output", ""),
                        "code": step.get("code", ""),
                        "tool_call": step.get("tool_call", ""),
                        "observation": step.get("observation", ""),
                        "web_events": step.get("web_events", []),
                    },
                    usage_details={
                        "input": token_usage.get("api_input_tokens", 0) or 0,
                        "output": token_usage.get("output_tokens", 0) or 0,
                    },
                    metadata={
                        "token_usage": token_usage,
                        "compression": step.get("compression"),
                        "provider_cache": step.get("provider_cache"),
                    },
                )

        item_scores = {}
        for eval_fn in evaluator_fns:
            try:
                result = eval_fn(
                    input=item.input,
                    output=output,
                    expected_output=item.expected_output,
                    metadata=item.metadata,
                )
                if isinstance(result, dict):
                    name = result.get("name", "unknown")
                    value = result.get("value", 0.0)
                elif isinstance(result, list):
                    for r in result:
                        n_ = r.get("name", "unknown")
                        v_ = r.get("value", 0.0)
                        trace.score(name=n_, value=v_)
                        item_scores[n_] = v_
                        total_scores.setdefault(n_, []).append(v_)
                    continue
                else:
                    name, value = "unknown", 0.0

                trace.score(name=name, value=value)
                item_scores[name] = value

                if name not in total_scores:
                    total_scores[name] = []
                total_scores[name].append(value)

            except Exception as e:
                print(f"EVAL_ERROR: {e}")

        compression = output.get("compression", {})
        agg_compression_calls += compression.get("calls", 0)
        agg_compression_input_tokens += compression.get("input_tokens", 0)
        agg_summary_cache_hits += compression.get("summary_cache_hits", 0)
        if (
            compression.get("calls", 0) > 0
            or compression.get("summary_cache_hits", 0) > 0
        ):
            trace.score(name="compression_calls", value=compression["calls"])
            trace.score(name="compression_input_tokens", value=compression.get("input_tokens", 0))
            trace.score(name="compression_output_tokens", value=compression.get("output_tokens", 0))
            trace.score(name="summary_cache_hits", value=compression.get("summary_cache_hits", 0))
            total_uncompressed = compression.get("total_uncompressed_est_tokens", 0)
            total_input = output.get("total_input_tokens", 0)
            if total_uncompressed > 0:
                trace.score(
                    name="compression_token_reduction_pct",
                    value=round((1 - total_input / total_uncompressed) * 100, 1),
                )

        provider_cache = output.get("provider_cache", {})
        if provider_cache.get("status") == "available":
            available_calls = provider_cache.get("available_calls", 0) or 0
            hit_calls = provider_cache.get("hit_calls", 0) or 0
            cached_tokens = provider_cache.get("provider_cached_tokens", 0) or 0
            provider_input_tokens = provider_cache.get("provider_input_tokens", 0) or 0
            agg_provider_cache_available_calls += available_calls
            agg_provider_cache_hit_calls += hit_calls
            agg_provider_cached_tokens += cached_tokens
            agg_provider_input_tokens += provider_input_tokens
            trace.score(name="provider_cache_hit_calls", value=hit_calls)
            trace.score(name="provider_cached_tokens", value=cached_tokens)
            trace.score(
                name="provider_cached_input_ratio",
                value=provider_cache.get("provider_cached_input_ratio", 0.0) or 0.0,
            )

        latency = output.get("latency", {})
        agg_wall_clock_seconds += latency.get("wall_clock_seconds", 0.0) or 0.0

        peak_ctx = output.get("peak_context", {})
        item_peak = peak_ctx.get("peak_context_tokens", 0) or 0
        if item_peak > agg_peak_context_tokens:
            agg_peak_context_tokens = item_peak

        token_saving = output.get("token_saving", {})
        agg_net_token_saving += token_saving.get("net_token_saving", 0) or 0

        primary_score = next(iter(item_scores.values()), 0.0)
        if primary_score >= 1.0:
            passed += 1
        else:
            failed += 1

        score_str = ", ".join(f"{k}={v:.2f}" for k, v in item_scores.items())
        print(f"✓ {score_str}")

        item.link(trace, run_name)

    lf.flush()

    from tools.web_evidence import (
        aggregate_web_evidence,
        write_web_evidence_artifact,
    )

    web_artifact_path = write_web_evidence_artifact(
        output_dir=ARTIFACT_ROOT / "web_evidence",
        run_name=run_name,
        dataset_name=dataset_name,
        item_evidence=item_web_evidence,
        exa_cache=(
            exa_cache_controller.snapshot()
            if exa_cache_controller is not None
            else None
        ),
    )
    web_aggregate = aggregate_web_evidence(item_web_evidence)

    print(f"\n{'='*60}")
    print(f"Experiment complete: {run_name}")
    print(f"  Total:  {n}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    for metric, values in total_scores.items():
        avg = sum(values) / len(values) if values else 0
        print(f"  Avg {metric}: {avg:.4f}")
    if agg_compression_calls > 0:
        print("  Compression:")
        print(f"    Total calls:        {agg_compression_calls}")
        print(f"    Total input tokens: {agg_compression_input_tokens}")
        print(f"    Summary cache hits: {agg_summary_cache_hits}")
    if agg_provider_cache_available_calls:
        print("  Provider prefix cache:")
        print(
            "    Call hit rate:       "
            f"{agg_provider_cache_hit_calls / agg_provider_cache_available_calls:.2%}"
        )
        print(f"    Cached tokens:      {agg_provider_cached_tokens}")
        print(
            "    Cached input ratio:  "
            f"{agg_provider_cached_tokens / agg_provider_input_tokens:.2%}"
            if agg_provider_input_tokens
            else "    Cached input ratio:  unavailable"
        )
    else:
        print("  Provider prefix cache: unsupported or metrics unavailable")
    if n > 0:
        print("  Latency:")
        print(f"    Total wall-clock:    {agg_wall_clock_seconds:.1f}s")
        print(f"    Avg per item:        {agg_wall_clock_seconds / n:.1f}s")
    print(f"  Peak context:          {agg_peak_context_tokens} tokens")
    print(f"  Net token saving:      {agg_net_token_saving} tokens")
    print("  Web retrieval:")
    print(f"    Exa search calls:    {web_aggregate['exa_search_calls']}")
    print(f"    Tavily extract calls:{web_aggregate['tavily_extract_calls']}")
    print(f"    Terminal fetch calls:{web_aggregate['terminal_fetch_calls']}")
    print(
        "    Search after URL:    "
        f"{web_aggregate['search_after_url_discovery']}"
    )
    print(
        "    URL found/no fetch:  "
        f"{web_aggregate['items_with_discovered_url_but_no_fetch']} items"
    )
    print(f"    Artifact:            {web_artifact_path}")
    print(f"\nView in Langfuse: {os.environ.get('LANGFUSE_HOST', '')}/dataset/{dataset.id}")
    print(f"{'='*60}")


def rescore_experiment(dataset_name: str, existing_run: str, evaluator_fns: list,
                       new_run_name: str):
    """Re-evaluate existing traces with new evaluators (no LLM calls)."""
    from langfuse import Langfuse
    lf = Langfuse()

    dataset = lf.get_dataset(dataset_name)
    items = dataset.items

    existing = lf.get_dataset_run(dataset_name, existing_run)
    run_items = existing.dataset_run_items
    print(f"Rescore '{new_run_name}': {len(run_items)} traces from '{existing_run}'")

    output_by_item_id = {}
    for ri in run_items:
        trace = lf.get_trace(ri.trace_id)
        output_by_item_id[ri.dataset_item_id] = trace.output

    total_scores = {}
    passed = 0

    for i, item in enumerate(items):
        output = output_by_item_id.get(item.id)
        if output is None:
            print(f"  [{i+1}] SKIP (no trace)")
            continue

        trace = lf.trace(
            name=f"re-eval-{dataset_name}",
            input=item.input, output=output,
            metadata={"re_eval_of": existing_run, "evaluators": [f.__name__ for f in evaluator_fns]},
        )

        item_scores = {}
        for eval_fn in evaluator_fns:
            try:
                result = eval_fn(
                    input=item.input, output=output,
                    expected_output=item.expected_output, metadata=item.metadata,
                )
                if isinstance(result, dict):
                    name = result.get("name", "unknown")
                    value = result.get("value", 0.0)
                    trace.score(name=name, value=value)
                    item_scores[name] = value
                    total_scores.setdefault(name, []).append(value)
                elif isinstance(result, list):
                    for r in result:
                        trace.score(name=r.get("name"), value=r.get("value"))
                        item_scores[r.get("name")] = r.get("value")
                        total_scores.setdefault(r.get("name"), []).append(r.get("value"))
            except Exception as e:
                print(f"  [{i+1}] EVAL_ERROR: {e}")

        primary = next(iter(item_scores.values()), 0.0)
        if primary >= 1.0:
            passed += 1

        item.link(trace, new_run_name)
        print(f"  [{i+1}] scores={item_scores}")

    lf.flush()

    avg_str = ", ".join(
        f"avg_{k}={sum(v)/len(v):.4f}" for k, v in total_scores.items()
    )
    print(f"Rescore '{new_run_name}' DONE: {passed}/{len(items)} passed, {avg_str}")


def main():
    parser = argparse.ArgumentParser(
        description="Unified benchmark runner for Nexent Agent evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Agent config
    parser.add_argument("--agent-config", type=str,
                        help="Path to agent YAML config file (from export_agent_config.py)")

    # Dataset
    parser.add_argument("--dataset", type=str, required=True,
                        help="Langfuse dataset name")
    parser.add_argument("--upload", type=str,
                        help="Path to JSONL file to upload as dataset")
    parser.add_argument("--input-key", type=str, default="question",
                        help="Key in JSONL for question (default: question)")
    parser.add_argument("--output-key", type=str, default="answer",
                        help="Key in JSONL for answer (default: answer)")

    # Evaluators
    parser.add_argument("--evaluators", nargs="+", default=["exact_match"],
                        help="Evaluator names (default: exact_match)")

    # Agent execution params (override YAML)
    parser.add_argument("--max-steps", type=int,
                        help="Max agent steps (overrides YAML)")
    parser.add_argument("--temperature", type=float,
                        help="LLM temperature (default: 0.1; exported YAML does not include it)")
    parser.add_argument(
        "--model-factory",
        type=str,
        help=(
            "Explicit provider capability identifier used for cache metrics "
            "(for example: openai); unknown providers remain unsupported"
        ),
    )
    parser.add_argument("--language", type=str, choices=["en", "zh"],
                        help="Prompt language (overrides YAML)")
    parser.add_argument("--duty-prompt", type=str,
                        help="Custom duty prompt (overrides YAML)")
    parser.add_argument("--constraint-prompt", type=str,
                        help="Custom constraint prompt (overrides YAML)")
    parser.add_argument("--few-shots-prompt", type=str,
                        help="Custom few shots prompt (overrides YAML)")
    parser.add_argument("--system-prompt-file", type=str,
                        help="Path to custom system prompt file (bypasses template)")
    parser.add_argument(
        "--production-parity-snapshot",
        type=str,
        help=(
            "JSON/YAML snapshot used as a strict parity gate; fidelity is derived "
            "from its producer metadata"
        ),
    )
    parser.add_argument(
        "--tenant-id",
        help="Tenant identity used by passively injected builtin skill tools",
    )
    parser.add_argument(
        "--skills-path",
        help="Local skill root passed to production-equivalent builtin skill tools",
    )
    parser.add_argument("--experiment-time", type=str,
                        help=argparse.SUPPRESS)

    # Context processing policy
    context_group = parser.add_mutually_exclusive_group()
    context_group.add_argument(
        "--context-processing-mode",
        choices=["passthrough", "adaptive_compact"],
        help="Context processing policy (preferred over legacy enable/disable aliases)",
    )
    context_group.add_argument("--enable-context-manager", action="store_true",
                               help="Deprecated alias for --context-processing-mode adaptive_compact")
    context_group.add_argument("--disable-context-manager", action="store_true",
                               help="Deprecated alias for --context-processing-mode passthrough")
    parser.add_argument("--token-threshold", type=positive_int,
                        help="Context manager token threshold (SDK default: 10000)")
    parser.add_argument("--soft-input-budget", type=positive_int,
                        help="Explicit soft input budget in tokens")
    parser.add_argument("--hard-input-budget", type=positive_int,
                        help="Explicit hard input budget in tokens")
    parser.add_argument(
        "--budget-profile",
        choices=(
            "legacy_threshold",
            "production_like",
            "synthetic_trigger",
            "synthetic_stress",
        ),
        help="Budget provenance/classification recorded in the run manifest",
    )
    parser.add_argument("--context-window-tokens", type=positive_int,
                        help="Model context-window capacity recorded by ContextManager")
    parser.add_argument("--keep-recent-steps", type=non_negative_int,
                        help="Keep N recent action steps from compression (SDK default: 4)")
    parser.add_argument("--keep-recent-pairs", type=non_negative_int,
                        help=argparse.SUPPRESS)
    parser.add_argument("--max-observation-length", type=non_negative_int,
                        help=argparse.SUPPRESS)

    # Execution
    parser.add_argument("--max-concurrency", type=positive_int, default=1,
                        help="Max parallel agent runs (default: 1)")
    parser.add_argument("--item-limit", type=positive_int,
                        help="Run only the first N dataset items (for deterministic smoke tests)")
    parser.add_argument(
        "--item-id",
        action="append",
        default=[],
        help="Run one exact Langfuse dataset item ID; repeat for multiple items",
    )
    parser.add_argument(
        "--exa-cache-mode",
        choices=["off", "record", "replay"],
        default="off",
        help=(
            "Benchmark-only Exa cache: record reuses hits and records misses; "
            "replay fails on every miss without a live fallback"
        ),
    )
    parser.add_argument(
        "--exa-cache-path",
        help="JSON cache path required when --exa-cache-mode is not off",
    )
    parser.add_argument("--run-name", type=str,
                        help="Custom run name (default: auto-generated)")

    # Rescore mode
    parser.add_argument("--rescore", action="store_true",
                        help="Rescore existing traces (no LLM calls)")
    parser.add_argument("--existing-run", type=str,
                        help="Existing run name to rescore (required with --rescore)")

    # Utilities
    parser.add_argument("--dry-run", action="store_true",
                        help="Upload dataset but don't run experiment")
    parser.add_argument("--list-evaluators", action="store_true",
                        help="List available evaluators and exit")

    args = parser.parse_args()
    if args.item_limit is not None and args.item_id:
        parser.error("--item-limit cannot be combined with --item-id")
    if args.exa_cache_mode != "off" and not args.exa_cache_path:
        parser.error("--exa-cache-path is required when Exa cache is enabled")
    if args.exa_cache_mode == "off" and args.exa_cache_path:
        parser.error("--exa-cache-path requires --exa-cache-mode record or replay")

    # List evaluators
    if args.list_evaluators:
        from evaluators import list_evaluators
        print("Available evaluators:")
        for name in list_evaluators():
            print(f"  - {name}")
        return

    # Load agent config if provided
    agent_config = {}
    if args.agent_config:
        print(f"Loading agent config from: {args.agent_config}")
        agent_config = load_agent_config(args.agent_config)

        agent_info = agent_config.get("agent_info", {})
        print(f"  Agent: {agent_info.get('display_name', 'unknown')}")
        print(f"  Description: {agent_info.get('description', '')[:80]}...")

    # Merge config: CLI args override YAML
    prompts = agent_config.get("prompts", {})
    agent_cfg = agent_config.get("agent_config", {})

    duty_prompt = args.duty_prompt or prompts.get("duty_prompt", "")
    constraint_prompt = args.constraint_prompt or prompts.get("constraint_prompt", "")
    few_shots_prompt = args.few_shots_prompt or prompts.get("few_shots_prompt", "")
    max_steps = args.max_steps or agent_cfg.get("max_steps", 10)
    temperature = args.temperature if args.temperature is not None else agent_cfg.get("temperature", 0.1)
    language = args.language or "en"
    model_factory = args.model_factory or agent_cfg.get("model_factory")
    budget_profile = args.budget_profile or (
        "explicit_unclassified"
        if args.soft_input_budget is not None or args.hard_input_budget is not None
        else "legacy_threshold"
    )

    yaml_enable_cm = agent_cfg.get("enable_context_manager", False)
    processing_mode = (
        args.context_processing_mode
        or ("adaptive_compact" if yaml_enable_cm else "passthrough")
    )
    if args.enable_context_manager:
        processing_mode = "adaptive_compact"
    elif args.disable_context_manager:
        processing_mode = "passthrough"

    if not args.rescore:
        removed_args = [
            name
            for name, value in {
                "--keep-recent-pairs": args.keep_recent_pairs,
                "--max-observation-length": args.max_observation_length,
            }.items()
            if value is not None
        ]
        if removed_args:
            parser.error(
                f"{', '.join(removed_args)} were removed by the unified ContextItems runtime"
            )
        if (
            args.soft_input_budget is not None
            and args.hard_input_budget is not None
            and args.soft_input_budget > args.hard_input_budget
        ):
            parser.error("--soft-input-budget cannot exceed --hard-input-budget")

    # Load custom system prompt if provided
    system_prompt = ""
    if args.system_prompt_file:
        with open(args.system_prompt_file, "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()
        print(f"Loaded custom system prompt from: {args.system_prompt_file}")

    # Resolve evaluators
    from evaluators import resolve_evaluators
    evaluator_fns = resolve_evaluators(args.evaluators)
    print(f"Evaluators: {args.evaluators}")

    # Init Langfuse
    from langfuse import Langfuse
    lf = Langfuse()
    try:
        lf.auth_check()
        print(f"Langfuse connected: {os.environ.get('LANGFUSE_HOST')}")
    except Exception as e:
        print(f"ERROR: Langfuse connection failed: {e}")
        sys.exit(1)

    # Upload dataset if requested
    if args.upload:
        if not os.path.exists(args.upload):
            print(f"ERROR: File not found: {args.upload}")
            sys.exit(1)
        upload_jsonl(
            dataset_name=args.dataset,
            jsonl_path=args.upload,
            input_key=args.input_key,
            output_key=args.output_key,
        )

    if args.dry_run:
        print("\nDry run complete.")
        return

    # Rescore mode
    if args.rescore:
        if not args.existing_run:
            parser.error("--existing-run is required with --rescore")

        new_run_name = args.run_name or f"{args.existing_run}-rescore-{'-'.join(args.evaluators)}"
        rescore_experiment(
            dataset_name=args.dataset,
            existing_run=args.existing_run,
            evaluator_fns=evaluator_fns,
            new_run_name=new_run_name
        )
        return

    from agent_runner import build_tools_from_yaml, inject_production_managed_tools
    tools_yaml = agent_config.get("tools", [])
    tools = build_tools_from_yaml(tools_yaml) if tools_yaml else []
    agent_info = agent_config.get("agent_info", {})
    tenant_id = args.tenant_id or agent_info.get("tenant_id") or "tenant_id"
    skills_path = args.skills_path or os.getenv("SKILLS_PATH")
    tools = inject_production_managed_tools(
        tools,
        agent_id=int(agent_info.get("agent_id", 0) or 0),
        tenant_id=str(tenant_id),
        version_no=int(agent_cfg.get("version_no", 0) or 0),
        local_skills_dir=skills_path,
    )
    exa_cache_controller = None
    if args.exa_cache_mode != "off":
        from runtime.exa_replay import install_exa_record_replay

        exa_cache_controller = install_exa_record_replay(
            args.exa_cache_mode,
            args.exa_cache_path,
        )
        print(
            f"Exa cache: mode={args.exa_cache_mode}, "
            f"path={Path(args.exa_cache_path).resolve()}"
        )

    # Run new experiment
    from runtime.task_adapter import make_nexent_task

    from nexent.core.agents.context import ContextManagerConfig, PolicyLayers
    cm_kwargs = {
        "policy_layers": PolicyLayers(
            platform={"processing_mode": processing_mode}
        )
    }
    if args.token_threshold is not None:
        cm_kwargs["token_threshold"] = args.token_threshold
    if args.soft_input_budget is not None:
        cm_kwargs["soft_input_budget_tokens"] = args.soft_input_budget
    if args.hard_input_budget is not None:
        cm_kwargs["hard_input_budget_tokens"] = args.hard_input_budget
    if args.context_window_tokens is not None:
        cm_kwargs["context_window_tokens"] = args.context_window_tokens
    if args.keep_recent_steps is not None:
        cm_kwargs["keep_recent_steps"] = args.keep_recent_steps
    cm_config = ContextManagerConfig(**cm_kwargs)

    task_fn = make_nexent_task(
        system_prompt=system_prompt,
        duty_prompt=duty_prompt,
        constraint_prompt=constraint_prompt,
        few_shots_prompt=few_shots_prompt,
        max_steps=max_steps,
        temperature=temperature,
        language=language,
        input_key=args.input_key,
        context_manager_config=cm_config,
        experiment_time=args.experiment_time,
        tools=tools,
        model_factory=model_factory,
        user_id="user_id",
        prompt_template_version=str(agent_cfg.get("prompt_template_id", "")),
        prompt_template_source=(
            str(Path(args.agent_config).resolve()) if args.agent_config else "benchmark_cli"
        ),
        resource_support={
            "tools": True,
            "skills": True,
            "managed_agents": True,
            "external_agents": False,
            "memory": False,
            "knowledge_base": False,
        },
        intentional_empty_resources={
            "skills": not bool(agent_config.get("skills")),
            "managed_agents": not bool(agent_config.get("sub_agents")),
        },
        prompt_components=agent_config.get("prompt_components"),
    )

    run_name = args.run_name or f"{args.dataset}-{int(time.time())}"

    print("\nConfiguration:")
    print(f"  Max steps:    {max_steps}")
    print(f"  Temperature:  {temperature}")
    print(f"  Language:     {language}")
    print(f"  Model factory:{model_factory or 'unknown'}")
    print(f"  Context mode: {processing_mode}")
    print(f"  Budget profile: {budget_profile}")
    print(f"  CM config:    threshold={cm_config.token_threshold}, "
          f"soft_budget={cm_config.soft_input_budget_tokens or cm_config.token_threshold}, "
          f"hard_budget={cm_config.hard_input_budget_tokens or int(cm_config.token_threshold * 1.1)}, "
          f"keep_steps={cm_config.keep_recent_steps}")
    print(f"  Tools:        {len(tools)} ({', '.join(t.name for t in tools) if tools else 'none'})")
    if duty_prompt:
        print(f"  Duty prompt:  {duty_prompt[:60]}...")

    run_experiment(
        dataset_name=args.dataset,
        task_fn=task_fn,
        evaluator_fns=evaluator_fns,
        run_name=run_name,
        max_concurrency=args.max_concurrency,
        item_limit=args.item_limit,
        item_ids=args.item_id,
        exa_cache_controller=exa_cache_controller,
        manifest_context={
            "repo_root": Path(__file__).resolve().parents[3],
            "lifecycle_mode": "isolated-item",
            "context_manager_config": cm_config,
            "max_steps": max_steps,
            "temperature": temperature,
            "language": language,
            "max_concurrency": args.max_concurrency,
            "tools": tools,
            "evaluator_names": args.evaluators,
            "observation_policy": {
                "owner": "context_items",
                "algorithm": "item_representation",
                "web_evidence_contract_version": 1,
                "exa_cache_mode": args.exa_cache_mode,
            },
            "started_at": datetime.now(timezone.utc).isoformat(),
            "budget_profile": budget_profile,
            "expected_parity_snapshot": (
                load_parity_snapshot(args.production_parity_snapshot)
                if args.production_parity_snapshot else None
            ),
        },
    )


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed


if __name__ == "__main__":
    main()
