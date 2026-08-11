# -*- coding: utf-8 -*-
"""Webhook server for triggering benchmark experiments from Langfuse UI.

Receives POST requests from Langfuse's "Custom Experiment" button and
runs experiments or re-evaluations in the background.

Start:
    backend/.venv/bin/python sdk/benchmark/generic/integrations/langfuse/webhook_server.py --port 8090

Langfuse UI setup:
    1. Open Datasets, select your dataset, and choose Start Experiment.
    2. Click the lightning icon under "Custom Experiment".
    3. Webhook URL: http://<your-host>:8090/webhook
    4. Default config (JSON):
       {
         "mode": "run",
         "evaluators": ["numeric_answer"],
         "max_steps": 10
       }
    5. Click Save, then use "Run" to trigger
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel


GENERIC_DIR = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = GENERIC_DIR.parent
sys.path.insert(0, str(GENERIC_DIR))
sys.path.insert(0, str(BENCHMARK_DIR))
import paths  # noqa: E402, F401 - resolves project import paths as a side effect


load_dotenv(os.path.join(paths.PROJECT_ROOT, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("benchmark-webhook")

app = FastAPI(title="Nexent Benchmark Webhook")


class WebhookPayload(BaseModel):
    # Original format (curl / direct calls)
    dataset_id: Optional[str] = None
    dataset_name: Optional[str] = None
    config: Optional[dict] = None
    # Langfuse UI format (camelCase, payload is a JSON string)
    projectId: Optional[str] = None
    datasetId: Optional[str] = None
    datasetName: Optional[str] = None
    payload: Optional[str] = None


def run_experiment_task(dataset_name: str, evaluators: list, max_steps: int,
                        run_name: str, temperature: float, language: str,
                        agent_config_path: str = None):
    """Run a new experiment (blocking - called in background thread)."""
    try:
        import yaml
        from evaluators import resolve_evaluators
        from langfuse import Langfuse
        from runtime.task_adapter import make_nexent_task

        logger.info(f"Starting experiment '{run_name}' for dataset '{dataset_name}'")
        lf = Langfuse()
        evaluator_fns = resolve_evaluators(evaluators)

        duty_prompt = ""
        constraint_prompt = ""
        few_shots_prompt = ""
        system_prompt = ""
        enable_cm = False

        if agent_config_path:
            if not os.path.isabs(agent_config_path):
                agent_config_path = str(GENERIC_DIR / agent_config_path)
            logger.info(f"Loading agent config from: {agent_config_path}")
            with open(agent_config_path, "r", encoding="utf-8") as f:
                agent_config = yaml.safe_load(f)

            agent_info = agent_config.get("agent_info", {})
            logger.info(f"  Agent: {agent_info.get('display_name', 'unknown')}")

            prompts = agent_config.get("prompts", {})
            agent_cfg = agent_config.get("agent_config", {})

            duty_prompt = prompts.get("duty_prompt", "")
            constraint_prompt = prompts.get("constraint_prompt", "")
            few_shots_prompt = prompts.get("few_shots_prompt", "")
            max_steps = max_steps or agent_cfg.get("max_steps", 10)
            enable_cm = agent_cfg.get("enable_context_manager", False)

        from nexent.core.agents.agent_context import ContextManagerConfig
        cm_config = ContextManagerConfig(enabled=enable_cm)

        dataset = lf.get_dataset(dataset_name)
        items = dataset.items
        logger.info(f"Experiment '{run_name}': {len(items)} items, evaluators={evaluators}")

        task_fn = make_nexent_task(
            system_prompt=system_prompt,
            duty_prompt=duty_prompt,
            constraint_prompt=constraint_prompt,
            few_shots_prompt=few_shots_prompt,
            max_steps=max_steps,
            temperature=temperature,
            language=language,
            context_manager_config=cm_config,
        )

        logger.info("Configuration:")
        logger.info(f"  Max steps:    {max_steps}")
        logger.info(f"  Temperature:  {temperature}")
        logger.info(f"  Language:     {language}")
        logger.info(f"  Context mgr:  {enable_cm}")
        if duty_prompt:
            logger.info(f"  Duty prompt:  {duty_prompt[:60]}...")

        total_scores = {}
        passed = 0
        failed = 0
        agg_compression_calls = 0
        agg_compression_input_tokens = 0
        agg_compression_cache_hits = 0

        for i, item in enumerate(items):
            q_preview = str(item.input)[:60] if item.input else ""
            logger.info(f"  [{i+1}/{len(items)}] {q_preview}...")
            trace = lf.trace(
                name=f"benchmark-{dataset_name}",
                input=item.input,
                metadata={"run_name": run_name, "item_index": i},
            )

            try:
                output = task_fn(item=item)
            except Exception as e:
                logger.error(f"  [{i+1}] ERROR: {e}")
                output = {"final_answer": "", "errors": [str(e)]}

            trace.update(
                output=output,
                metadata={
                    "run_name": run_name,
                    "item_index": i,
                    "system_prompt": output.get("system_prompt", ""),
                    "model_config": output.get("model_config", {}),
                    "agent_config": output.get("agent_config", {}),
                    "compression": output.get("compression", {}),
                },
            )

            steps = output.get("steps", [])
            for step in steps:
                step_num = step.get("step_number", "?")
                if step_num == "final_answer":
                    trace.span(
                        name="final_answer",
                        output={"answer": step.get("main_output", "")},
                        metadata={"token_usage": step.get("token_usage")},
                    )
                else:
                    trace.span(
                        name=f"step_{step_num}",
                        input={
                            "thinking": step.get("thinking", ""),
                            "deep_thinking": step.get("deep_thinking", ""),
                        },
                        output={
                            "main_output": step.get("main_output", ""),
                            "code": step.get("code", ""),
                            "observation": step.get("observation", ""),
                        },
                        metadata={
                            "token_usage": step.get("token_usage"),
                            "compression": step.get("compression"),
                        },
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
                    logger.error(f"  [{i+1}] EVAL_ERROR: {e}")

            compression = output.get("compression", {})
            agg_compression_calls += compression.get("calls", 0)
            agg_compression_input_tokens += compression.get("input_tokens", 0)
            agg_compression_cache_hits += compression.get("cache_hits", 0)
            if compression.get("calls", 0) > 0:
                trace.score(name="compression_calls", value=compression["calls"])
                trace.score(name="compression_input_tokens", value=compression.get("input_tokens", 0))
                trace.score(name="compression_output_tokens", value=compression.get("output_tokens", 0))
                trace.score(name="compression_cache_hits", value=compression.get("cache_hits", 0))
                total_uncompressed = compression.get("total_uncompressed_est_tokens", 0)
                total_input = output.get("total_input_tokens", 0)
                if total_uncompressed > 0:
                    trace.score(
                        name="compression_token_reduction_pct",
                        value=round((1 - total_input / total_uncompressed) * 100, 1),
                    )

            primary = next(iter(item_scores.values()), 0.0)
            if primary >= 1.0:
                passed += 1
            else:
                failed += 1

            score_str = ", ".join(f"{k}={v:.2f}" for k, v in item_scores.items())
            logger.info(f"  [{i+1}] ✓ {score_str}")

            item.link(trace, run_name)

        lf.flush()

        logger.info(f"Experiment '{run_name}' DONE:")
        logger.info(f"  Total:  {len(items)}")
        logger.info(f"  Passed: {passed}")
        logger.info(f"  Failed: {failed}")
        for metric, values in total_scores.items():
            avg = sum(values) / len(values) if values else 0
            logger.info(f"  Avg {metric}: {avg:.4f}")
        if agg_compression_calls > 0:
            logger.info("  Compression:")
            logger.info(f"    Total calls:        {agg_compression_calls}")
            logger.info(f"    Total input tokens: {agg_compression_input_tokens}")
            logger.info(f"    Total cache hits:   {agg_compression_cache_hits}")

    except Exception as e:
        logger.error(f"Experiment '{run_name}' FAILED: {e}", exc_info=True)


def rescore_task(dataset_name: str, existing_run: str, evaluators: list, new_run_name: str):
    """Re-evaluate existing traces with new evaluators (no LLM calls)."""
    from evaluators import resolve_evaluators
    from langfuse import Langfuse

    lf = Langfuse()
    evaluator_fns = resolve_evaluators(evaluators)

    dataset = lf.get_dataset(dataset_name)
    items = dataset.items

    existing = lf.get_dataset_run(dataset_name, existing_run)
    run_items = existing.dataset_run_items
    logger.info(f"Rescore '{new_run_name}': {len(run_items)} traces from '{existing_run}'")

    output_by_item_id = {}
    for ri in run_items:
        trace = lf.get_trace(ri.trace_id)
        output_by_item_id[ri.dataset_item_id] = trace.output

    total_scores = {}
    passed = 0

    for i, item in enumerate(items):
        output = output_by_item_id.get(item.id)
        if output is None:
            logger.info(f"  [{i+1}] SKIP (no trace)")
            continue

        trace = lf.trace(
            name=f"re-eval-{dataset_name}",
            input=item.input, output=output,
            metadata={"re_eval_of": existing_run, "evaluators": evaluators},
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
                logger.error(f"  [{i+1}] EVAL_ERROR: {e}")

        primary = next(iter(item_scores.values()), 0.0)
        if primary >= 1.0:
            passed += 1

        item.link(trace, new_run_name)
        logger.info(f"  [{i+1}] scores={item_scores}")

    lf.flush()

    avg_str = ", ".join(
        f"avg_{k}={sum(v)/len(v):.4f}" for k, v in total_scores.items()
    )
    logger.info(f"Rescore '{new_run_name}' DONE: {passed}/{len(items)} passed, {avg_str}")


@app.post("/webhook")
async def handle_webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    """Handle webhook from both direct curl and Langfuse UI "Run Experiment" button.

    Accepts two payload formats:
      Direct:  {"dataset_name": "...", "config": {...}}
      Langfuse: {"datasetName": "...", "datasetId": "...", "projectId": "...", "payload": "{...}"}

    Config fields (inside config dict or parsed payload string):
      mode: "run" (default) or "rescore"
      evaluators: list of evaluator names (default: ["numeric_answer"])
      max_steps: int (default: 10)
      temperature: float (default: 0.1)
      language: "en" or "zh" (default: "en")
      agent-config: path to agent YAML config file (optional)
      existing_run: str (required for mode="rescore")
    """
    logger.info(f"Webhook received: dataset_name={payload.dataset_name}, datasetName={payload.datasetName}, "
                f"config_keys={list((payload.config or {}).keys())}, payload_type={type(payload.payload).__name__}")

    dataset_name = payload.dataset_name or payload.datasetName

    config = payload.config
    if config is None and payload.payload is not None:
        try:
            config = json.loads(payload.payload) if isinstance(payload.payload, str) else payload.payload
        except (json.JSONDecodeError, TypeError):
            logger.warning("Rejected webhook request with invalid payload JSON")
            return {"status": "error", "message": "invalid payload JSON"}
    config = config or {}

    mode = config.get("mode", "run")
    evaluators = config.get("evaluators", ["numeric_answer"])

    if not dataset_name:
        return {"status": "error", "message": "dataset_name is required (send dataset_name or datasetName)"}

    if mode == "rescore":
        existing_run = config.get("existing_run", "")
        if not existing_run:
            return {"status": "error", "message": "existing_run is required for rescore mode"}
        new_run_name = config.get("run_name") or f"{existing_run}-rescore-{'-'.join(evaluators)}"
        background_tasks.add_task(rescore_task, dataset_name, existing_run, evaluators, new_run_name)
        return {"status": "accepted", "mode": "rescore", "run_name": new_run_name}

    max_steps = config.get("max_steps", 10)
    temperature = config.get("temperature", 0.1)
    language = config.get("language", "en")
    run_name = config.get("run_name") or f"{dataset_name}-{int(time.time())}"
    agent_config_path = config.get("agent-config") or config.get("agent_config")

    background_tasks.add_task(
        run_experiment_task, dataset_name, evaluators, max_steps,
        run_name, temperature, language, agent_config_path,
    )
    return {"status": "accepted", "mode": "run", "run_name": run_name}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nexent-benchmark-webhook"}


@app.get("/evaluators")
async def list_evaluators():
    from evaluators import list_evaluators
    return {"evaluators": list_evaluators()}


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    logger.info(f"Starting webhook server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
