import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic import run_benchmark


class FakeTrace:
    def __init__(self, **created_with):
        self.created_with = created_with
        self.updated_with = None
        self.spans = []
        self.generations = []
        self.scores = []

    def update(self, **kwargs):
        self.updated_with = kwargs

    def span(self, **kwargs):
        self.spans.append(kwargs)

    def generation(self, **kwargs):
        self.generations.append(kwargs)

    def score(self, **kwargs):
        self.scores.append(kwargs)


class FakeItem:
    def __init__(self, item_id, question="question", expected="answer"):
        self.id = item_id
        self.input = {"question": question}
        self.expected_output = {"answer": expected}
        self.metadata = {"category": "test"}
        self.links = []

    def link(self, trace, run_name):
        self.links.append((trace, run_name))


class FakeLangfuse:
    def __init__(self, items):
        self.dataset = SimpleNamespace(id="dataset-id", version="v1", items=items)
        self.traces = []
        self.trace_outputs = {}
        self.run_items = []
        self.created_dataset_items = []
        self.flush_calls = 0
        self.create_dataset_calls = []

    def get_dataset(self, dataset_name):
        return self.dataset

    def trace(self, **kwargs):
        trace = FakeTrace(**kwargs)
        self.traces.append(trace)
        return trace

    def flush(self):
        self.flush_calls += 1

    def create_dataset(self, **kwargs):
        self.create_dataset_calls.append(kwargs)

    def create_dataset_item(self, **kwargs):
        self.created_dataset_items.append(kwargs)

    def get_dataset_run(self, dataset_name, run_name):
        return SimpleNamespace(dataset_run_items=self.run_items)

    def get_trace(self, trace_id):
        return SimpleNamespace(output=self.trace_outputs[trace_id])


def _complete_task_output():
    return {
        "final_answer": "answer",
        "total_input_tokens": 50,
        "agent_config": {"name": "agent"},
        "compression": {
            "calls": 1,
            "input_tokens": 20,
            "output_tokens": 5,
            "summary_cache_hits": 1,
            "total_uncompressed_est_tokens": 100,
        },
        "model_config": {"model_name": "model"},
        "provider_cache": {
            "status": "available",
            "available_calls": 2,
            "hit_calls": 1,
            "provider_cached_tokens": 30,
            "provider_input_tokens": 50,
            "provider_cached_input_ratio": 0.6,
        },
        "system_prompt": "system",
        "parity_snapshot": {"processing_mode": "passthrough"},
        "web_evidence": {"exa_search_calls": 1},
        "latency": {"wall_clock_seconds": 1.5},
        "peak_context": {"peak_context_tokens": 80},
        "token_saving": {"net_token_saving": 50},
        "steps": [
            {
                "step_number": 1,
                "query": "question",
                "thinking": "think",
                "main_output": "draft",
                "token_usage": {"api_input_tokens": 40, "output_tokens": 10},
            },
            {
                "step_number": "final_answer",
                "query": "question",
                "main_output": "answer",
                "token_usage": {"output_tokens": 2},
            },
        ],
    }


def test_upload_jsonl_skips_invalid_rows_and_preserves_extra_input_fields(
    monkeypatch,
    tmp_path,
    capsys,
):
    fake_langfuse = FakeLangfuse([])
    monkeypatch.setattr("langfuse.Langfuse", lambda: fake_langfuse)
    jsonl_path = tmp_path / "dataset.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"question": "q", "answer": "a", "source": "fixture"}),
                "not-json",
                json.dumps({"question": "without gold"}),
            ]
        ),
        encoding="utf-8",
    )

    count = run_benchmark.upload_jsonl("dataset", str(jsonl_path))

    assert count == 2
    assert fake_langfuse.created_dataset_items == [
        {
            "dataset_name": "dataset",
            "input": {"question": "q", "source": "fixture"},
            "expected_output": {"answer": "a"},
        },
        {
            "dataset_name": "dataset",
            "input": {"question": "without gold"},
            "expected_output": None,
        },
    ]
    assert fake_langfuse.flush_calls == 1
    assert "skipping line 2" in capsys.readouterr().out


def test_run_experiment_records_trace_scores_manifest_and_aggregates(
    monkeypatch,
    tmp_path,
    capsys,
):
    item = FakeItem("item-1")
    fake_langfuse = FakeLangfuse([item])
    monkeypatch.setattr("langfuse.Langfuse", lambda: fake_langfuse)
    monkeypatch.setattr(run_benchmark, "ARTIFACT_ROOT", tmp_path)

    import provenance.experiment_manifest as manifest_module
    import tools.web_evidence as web_evidence_module

    monkeypatch.setattr(
        manifest_module,
        "manifest_path",
        lambda output_dir, run_name: Path(output_dir) / f"{run_name}.json",
    )
    monkeypatch.setattr(
        manifest_module,
        "build_manifest",
        lambda **kwargs: {"manifest_hash": "manifest-hash", "inputs": kwargs},
    )
    manifest_output = tmp_path / "manifests" / "run.json"
    monkeypatch.setattr(
        manifest_module,
        "write_manifest_exclusive",
        lambda manifest, output_dir: manifest_output,
    )
    monkeypatch.setattr(
        web_evidence_module,
        "web_evidence_artifact_path",
        lambda output_dir, run_name: Path(output_dir) / f"{run_name}.json",
    )
    web_output = tmp_path / "web_evidence" / "run.json"
    written_web_evidence = {}

    def fake_write_web_evidence_artifact(**kwargs):
        written_web_evidence.update(kwargs)
        return web_output

    monkeypatch.setattr(
        web_evidence_module,
        "write_web_evidence_artifact",
        fake_write_web_evidence_artifact,
    )
    monkeypatch.setattr(
        web_evidence_module,
        "aggregate_web_evidence",
        lambda evidence: {
            "exa_search_calls": 1,
            "tavily_extract_calls": 0,
            "terminal_fetch_calls": 0,
            "search_after_url_discovery": 0,
            "items_with_discovered_url_but_no_fetch": 0,
        },
    )

    def passing_evaluator(**kwargs):
        return {"name": "exact_match", "value": 1.0}

    def multi_evaluator(**kwargs):
        return [{"name": "f1", "value": 0.5}]

    def unknown_result_evaluator(**kwargs):
        return None

    def failing_evaluator(**kwargs):
        raise ValueError("evaluator unavailable")

    exa_cache = SimpleNamespace(snapshot=lambda: {"entries": 1})
    run_benchmark.run_experiment(
        dataset_name="dataset",
        task_fn=lambda **kwargs: _complete_task_output(),
        evaluator_fns=[
            passing_evaluator,
            multi_evaluator,
            unknown_result_evaluator,
            failing_evaluator,
        ],
        run_name="run",
        manifest_context={"runner": "test"},
        item_ids=["item-1"],
        exa_cache_controller=exa_cache,
    )

    trace = fake_langfuse.traces[0]
    score_names = {score["name"] for score in trace.scores}
    assert {"exact_match", "f1", "compression_calls", "provider_cache_hit_calls"} <= score_names
    assert trace.generations[0]["usage_details"] == {"input": 40, "output": 10}
    assert trace.spans[0]["name"] == "final_answer"
    assert trace.updated_with["metadata"]["manifest_hash"] == "manifest-hash"
    assert item.links == [(trace, "run")]
    assert fake_langfuse.flush_calls == 1
    assert written_web_evidence["exa_cache"] == {"entries": 1}
    output = capsys.readouterr().out
    assert "Passed: 1" in output
    assert "Avg exact_match: 1.0000" in output
    assert "EVAL_ERROR: evaluator unavailable" in output


def test_run_experiment_rejects_incomplete_task_output(monkeypatch):
    fake_langfuse = FakeLangfuse([FakeItem("item-1")])
    monkeypatch.setattr("langfuse.Langfuse", lambda: fake_langfuse)

    with pytest.raises(RuntimeError, match="Benchmark task output is incomplete"):
        run_benchmark.run_experiment(
            "dataset",
            lambda **kwargs: {"final_answer": "answer"},
            [],
            "run",
        )


def test_run_experiment_returns_without_traces_for_empty_dataset(monkeypatch, capsys):
    fake_langfuse = FakeLangfuse([])
    monkeypatch.setattr("langfuse.Langfuse", lambda: fake_langfuse)

    assert run_benchmark.run_experiment("dataset", lambda **kwargs: {}, [], "run") is None
    assert fake_langfuse.traces == []
    assert "Dataset is empty" in capsys.readouterr().out


def test_rescore_experiment_scores_linked_items_and_skips_missing_traces(
    monkeypatch,
    capsys,
):
    scored_item = FakeItem("item-1")
    missing_item = FakeItem("item-2")
    fake_langfuse = FakeLangfuse([scored_item, missing_item])
    fake_langfuse.run_items = [
        SimpleNamespace(dataset_item_id="item-1", trace_id="old-trace")
    ]
    fake_langfuse.trace_outputs["old-trace"] = {"final_answer": "answer"}
    monkeypatch.setattr("langfuse.Langfuse", lambda: fake_langfuse)

    def exact_match(**kwargs):
        return {"name": "exact_match", "value": 1.0}

    def secondary_scores(**kwargs):
        return [{"name": "f1", "value": 0.75}]

    run_benchmark.rescore_experiment(
        "dataset",
        "old-run",
        [exact_match, secondary_scores],
        "new-run",
    )

    assert scored_item.links == [(fake_langfuse.traces[0], "new-run")]
    assert missing_item.links == []
    assert fake_langfuse.flush_calls == 1
    output = capsys.readouterr().out
    assert "SKIP (no trace)" in output
    assert "1/2 passed" in output


def test_main_builds_runtime_configuration_and_dispatches_experiment(
    monkeypatch,
    tmp_path,
):
    import agent_runner
    import evaluators
    import runtime.exa_replay as exa_replay
    import runtime.task_adapter as runtime_task_adapter

    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        """
agent_info:
  display_name: Test agent
  description: Agent description
  agent_id: 7
  tenant_id: yaml-tenant
agent_config:
  max_steps: 8
  version_no: 3
  prompt_template_id: prompt-v1
prompts:
  duty_prompt: Solve carefully
tools:
  - name: search
skills: []
sub_agents: []
""".strip(),
        encoding="utf-8",
    )
    def evaluator_fn(**kwargs):
        return {"name": "exact_match", "value": 1.0}
    monkeypatch.setattr(evaluators, "resolve_evaluators", lambda names: [evaluator_fn])
    monkeypatch.setattr(
        "langfuse.Langfuse",
        lambda: SimpleNamespace(auth_check=lambda: True),
    )
    configured_tool = SimpleNamespace(name="configured")
    injected_tool = SimpleNamespace(name="injected")
    monkeypatch.setattr(
        agent_runner,
        "build_tools_from_yaml",
        lambda tools_yaml: [configured_tool],
    )
    monkeypatch.setattr(
        agent_runner,
        "inject_production_managed_tools",
        lambda tools, **kwargs: [*tools, injected_tool],
    )
    exa_cache = SimpleNamespace(snapshot=lambda: {})
    monkeypatch.setattr(
        exa_replay,
        "install_exa_record_replay",
        lambda mode, path: exa_cache,
    )
    def task_fn(**kwargs):
        return {}
    task_configuration = {}

    def fake_make_nexent_task(**kwargs):
        task_configuration.update(kwargs)
        return task_fn

    monkeypatch.setattr(
        runtime_task_adapter,
        "make_nexent_task",
        fake_make_nexent_task,
    )
    dispatched = {}
    monkeypatch.setattr(
        run_benchmark,
        "run_experiment",
        lambda **kwargs: dispatched.update(kwargs),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark.py",
            "--dataset",
            "dataset",
            "--agent-config",
            str(config_path),
            "--evaluators",
            "exact_match",
            "--run-name",
            "run",
            "--max-steps",
            "5",
            "--temperature",
            "0",
            "--model-factory",
            "openai",
            "--language",
            "en",
            "--context-processing-mode",
            "adaptive_compact",
            "--token-threshold",
            "90",
            "--soft-input-budget",
            "100",
            "--hard-input-budget",
            "200",
            "--context-window-tokens",
            "300",
            "--keep-recent-steps",
            "2",
            "--budget-profile",
            "synthetic_trigger",
            "--tenant-id",
            "cli-tenant",
            "--skills-path",
            "/skills",
            "--exa-cache-mode",
            "record",
            "--exa-cache-path",
            str(tmp_path / "exa.json"),
            "--item-id",
            "item-1",
        ],
    )

    run_benchmark.main()

    cm_config = task_configuration["context_manager_config"]
    assert cm_config.policy_layers.platform["processing_mode"] == "adaptive_compact"
    assert cm_config.soft_input_budget_tokens == 100
    assert cm_config.hard_input_budget_tokens == 200
    assert task_configuration["tools"] == [configured_tool, injected_tool]
    assert task_configuration["max_steps"] == 5
    assert dispatched["dataset_name"] == "dataset"
    assert dispatched["task_fn"] is task_fn
    assert dispatched["run_name"] == "run"
    assert dispatched["item_ids"] == ["item-1"]
    assert dispatched["exa_cache_controller"] is exa_cache
    assert dispatched["manifest_context"]["budget_profile"] == "synthetic_trigger"


def test_main_dispatches_rescore_without_building_agent(monkeypatch):
    import evaluators

    def evaluator_fn(**kwargs):
        return {"name": "em", "value": 1.0}
    monkeypatch.setattr(evaluators, "resolve_evaluators", lambda names: [evaluator_fn])
    monkeypatch.setattr(
        "langfuse.Langfuse",
        lambda: SimpleNamespace(auth_check=lambda: True),
    )
    dispatched = {}
    monkeypatch.setattr(
        run_benchmark,
        "rescore_experiment",
        lambda **kwargs: dispatched.update(kwargs),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark.py",
            "--dataset",
            "dataset",
            "--evaluators",
            "em",
            "--rescore",
            "--existing-run",
            "old-run",
        ],
    )

    run_benchmark.main()

    assert dispatched == {
        "dataset_name": "dataset",
        "existing_run": "old-run",
        "evaluator_fns": [evaluator_fn],
        "new_run_name": "old-run-rescore-em",
    }
