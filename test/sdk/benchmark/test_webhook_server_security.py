import logging
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from sdk.benchmark.generic.integrations.langfuse import webhook_server
from sdk.benchmark.generic.integrations.langfuse.webhook_server import (
    WebhookPayload,
    handle_webhook,
)


class FakeTrace:
    def __init__(self):
        self.updated_with = None
        self.spans = []
        self.scores = []

    def update(self, **kwargs):
        self.updated_with = kwargs

    def span(self, **kwargs):
        self.spans.append(kwargs)

    def score(self, **kwargs):
        self.scores.append(kwargs)


class FakeItem:
    def __init__(self, item_id):
        self.id = item_id
        self.input = {"question": "question"}
        self.expected_output = {"answer": "answer"}
        self.metadata = {}
        self.links = []

    def link(self, trace, run_name):
        self.links.append((trace, run_name))


class FakeLangfuse:
    def __init__(self, items):
        self.dataset = SimpleNamespace(items=items)
        self.traces = []
        self.run_items = []
        self.trace_outputs = {}
        self.flush_calls = 0

    def get_dataset(self, dataset_name):
        return self.dataset

    def trace(self, **kwargs):
        trace = FakeTrace()
        self.traces.append(trace)
        return trace

    def flush(self):
        self.flush_calls += 1

    def get_dataset_run(self, dataset_name, run_name):
        return SimpleNamespace(dataset_run_items=self.run_items)

    def get_trace(self, trace_id):
        return SimpleNamespace(output=self.trace_outputs[trace_id])


@pytest.mark.asyncio
async def test_invalid_payload_does_not_expose_parser_or_payload_details(caplog):
    raw_payload = '{"api_key": "secret-value"'
    payload = WebhookPayload(
        datasetName="security-test",
        payload=raw_payload,
    )

    with caplog.at_level(logging.WARNING, logger="benchmark-webhook"):
        response = await handle_webhook(payload, BackgroundTasks())

    assert response == {
        "status": "error",
        "message": "invalid payload JSON",
    }
    serialized_response = str(response)
    assert "secret-value" not in serialized_response
    assert "Expecting" not in serialized_response
    assert raw_payload not in caplog.text
    assert "secret-value" not in caplog.text


@pytest.mark.asyncio
async def test_direct_run_payload_schedules_experiment_with_explicit_configuration():
    background_tasks = BackgroundTasks()
    payload = WebhookPayload(
        dataset_name="dataset",
        config={
            "mode": "run",
            "evaluators": ["exact_match"],
            "max_steps": 7,
            "temperature": 0,
            "language": "en",
            "run_name": "run-name",
            "agent_config": "configs/agent.yaml",
        },
    )

    response = await handle_webhook(payload, background_tasks)

    assert response == {"status": "accepted", "mode": "run", "run_name": "run-name"}
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is webhook_server.run_experiment_task
    assert task.args == (
        "dataset",
        ["exact_match"],
        7,
        "run-name",
        0,
        "en",
        "configs/agent.yaml",
    )


@pytest.mark.asyncio
async def test_langfuse_rescore_payload_schedules_rescore_with_default_run_name():
    background_tasks = BackgroundTasks()
    payload = WebhookPayload(
        datasetName="dataset",
        payload='{"mode":"rescore","existing_run":"old","evaluators":["em","f1"]}',
    )

    response = await handle_webhook(payload, background_tasks)

    assert response == {
        "status": "accepted",
        "mode": "rescore",
        "run_name": "old-rescore-em-f1",
    }
    task = background_tasks.tasks[0]
    assert task.func is webhook_server.rescore_task
    assert task.args == ("dataset", "old", ["em", "f1"], "old-rescore-em-f1")


@pytest.mark.asyncio
async def test_webhook_rejects_missing_dataset_and_incomplete_rescore_request():
    missing_dataset = await handle_webhook(WebhookPayload(config={}), BackgroundTasks())
    missing_existing_run = await handle_webhook(
        WebhookPayload(dataset_name="dataset", config={"mode": "rescore"}),
        BackgroundTasks(),
    )

    assert missing_dataset == {
        "status": "error",
        "message": "dataset_name is required (send dataset_name or datasetName)",
    }
    assert missing_existing_run == {
        "status": "error",
        "message": "existing_run is required for rescore mode",
    }


@pytest.mark.asyncio
async def test_health_and_evaluator_routes(monkeypatch):
    import evaluators

    monkeypatch.setattr(evaluators, "list_evaluators", lambda: ["em", "f1"])

    assert await webhook_server.health() == {
        "status": "ok",
        "service": "nexent-benchmark-webhook",
    }
    assert await webhook_server.list_evaluators() == {"evaluators": ["em", "f1"]}


def test_webhook_cli_defaults_to_localhost():
    args = webhook_server.build_cli_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8090


def test_run_experiment_task_executes_scoring_tracing_and_compression(
    monkeypatch,
    tmp_path,
    caplog,
):
    import evaluators
    import runtime.task_adapter as runtime_task_adapter

    item = FakeItem("item-1")
    fake_langfuse = FakeLangfuse([item])
    monkeypatch.setattr("langfuse.Langfuse", lambda: fake_langfuse)

    def exact_match(**kwargs):
        return {"name": "exact_match", "value": 1.0}

    def secondary_scores(**kwargs):
        return [{"name": "f1", "value": 0.5}]

    def failing_evaluator(**kwargs):
        raise ValueError("api_key=secret-evaluator-value\nforged evaluator log")

    monkeypatch.setattr(
        evaluators,
        "resolve_evaluators",
        lambda names: [exact_match, secondary_scores, failing_evaluator],
    )
    task_configuration = {}
    task_output = {
        "final_answer": "answer",
        "total_input_tokens": 50,
        "system_prompt": "system",
        "model_config": {"model_name": "model"},
        "agent_config": {"name": "agent"},
        "steps": [
            {
                "step_number": 1,
                "thinking": "think",
                "main_output": "draft",
                "token_usage": {"input_tokens": 10},
            },
            {
                "step_number": "final_answer",
                "main_output": "answer",
                "token_usage": {"output_tokens": 2},
            },
        ],
        "compression": {
            "calls": 1,
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_hits": 1,
            "total_uncompressed_est_tokens": 100,
        },
    }

    def fake_make_nexent_task(**kwargs):
        task_configuration.update(kwargs)
        return lambda **task_kwargs: task_output

    monkeypatch.setattr(
        runtime_task_adapter,
        "make_nexent_task",
        fake_make_nexent_task,
    )
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        """
agent_info:
  display_name: Test agent
prompts:
  duty_prompt: Solve the task with secret-prompt-value
  constraint_prompt: Be exact
  few_shots_prompt: Example
agent_config:
  max_steps: 12
  enable_context_manager: true
""".strip(),
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO, logger="benchmark-webhook"):
        webhook_server.run_experiment_task(
            "dataset",
            ["exact_match"],
            0,
            "run",
            0.0,
            "en",
            str(config_path),
        )

    trace = fake_langfuse.traces[0]
    assert task_configuration["max_steps"] == 12
    assert task_configuration["duty_prompt"] == "Solve the task with secret-prompt-value"
    assert (
        task_configuration["context_manager_config"].policy_layers.platform[
            "processing_mode"
        ]
        == "adaptive_compact"
    )
    assert trace.updated_with["output"] is task_output
    assert [span["name"] for span in trace.spans] == ["step_1", "final_answer"]
    assert {"exact_match", "f1", "compression_calls"} <= {
        score["name"] for score in trace.scores
    }
    assert item.links == [(trace, "run")]
    assert fake_langfuse.flush_calls == 1
    assert "Evaluator execution failed" in caplog.text
    assert "secret-evaluator-value" not in caplog.text
    assert "forged evaluator log" not in caplog.text
    assert "secret-prompt-value" not in caplog.text
    assert str(config_path) not in caplog.text
    assert "question" not in caplog.text
    assert "Passed: 1" in caplog.text


def test_run_experiment_task_logs_outer_failure_without_raising(monkeypatch, caplog):
    def fail_langfuse():
        raise RuntimeError("api_key=secret-langfuse-value\nforged outer log")

    monkeypatch.setattr("langfuse.Langfuse", fail_langfuse)

    with caplog.at_level(logging.ERROR, logger="benchmark-webhook"):
        webhook_server.run_experiment_task(
            "dataset",
            ["exact_match"],
            5,
            "run",
            0.0,
            "en",
        )

    assert "Experiment 'run' FAILED" in caplog.text
    assert "secret-langfuse-value" not in caplog.text
    assert "forged outer log" not in caplog.text
    assert "Traceback" not in caplog.text


def test_run_experiment_task_redacts_task_exception_from_logs_and_trace(
    monkeypatch,
    caplog,
):
    import evaluators
    import runtime.task_adapter as runtime_task_adapter

    item = FakeItem("item-1")
    fake_langfuse = FakeLangfuse([item])
    monkeypatch.setattr("langfuse.Langfuse", lambda: fake_langfuse)
    monkeypatch.setattr(evaluators, "resolve_evaluators", lambda names: [])

    def failing_task(**kwargs):
        raise RuntimeError("password=secret-task-value\nforged task log")

    monkeypatch.setattr(
        runtime_task_adapter,
        "make_nexent_task",
        lambda **kwargs: failing_task,
    )

    with caplog.at_level(logging.INFO, logger="benchmark-webhook"):
        webhook_server.run_experiment_task(
            "dataset",
            [],
            5,
            "run",
            0.0,
            "en",
        )

    tracked_output = fake_langfuse.traces[0].updated_with["output"]
    assert tracked_output["errors"] == ["task execution failed"]
    assert "Task execution failed" in caplog.text
    assert "secret-task-value" not in caplog.text
    assert "forged task log" not in caplog.text
    assert "secret-task-value" not in str(tracked_output)


def test_rescore_task_scores_linked_items_and_skips_missing_traces(
    monkeypatch,
    caplog,
):
    import evaluators

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
        return [{"name": "f1", "value": 0.5}]

    def failing_evaluator(**kwargs):
        raise ValueError("api_key=secret-rescore-value\nforged rescore log")

    monkeypatch.setattr(
        evaluators,
        "resolve_evaluators",
        lambda names: [exact_match, secondary_scores, failing_evaluator],
    )

    with caplog.at_level(logging.INFO, logger="benchmark-webhook"):
        webhook_server.rescore_task(
            "dataset",
            "old-run",
            ["exact_match"],
            "new-run",
        )

    trace = fake_langfuse.traces[0]
    assert {score["name"] for score in trace.scores} == {"exact_match", "f1"}
    assert scored_item.links == [(trace, "new-run")]
    assert missing_item.links == []
    assert fake_langfuse.flush_calls == 1
    assert "SKIP (no trace)" in caplog.text
    assert "1/2 passed" in caplog.text
    assert "Evaluator execution failed" in caplog.text
    assert "secret-rescore-value" not in caplog.text
    assert "forged rescore log" not in caplog.text


def test_rescore_task_redacts_outer_exception(monkeypatch, caplog):
    def fail_langfuse():
        raise RuntimeError("password=secret-rescore-outer\nforged outer rescore log")

    monkeypatch.setattr("langfuse.Langfuse", fail_langfuse)

    with caplog.at_level(logging.ERROR, logger="benchmark-webhook"):
        webhook_server.rescore_task(
            "dataset",
            "old-run",
            ["exact_match"],
            "new-run",
        )

    assert "Rescore task 'new-run' FAILED" in caplog.text
    assert "secret-rescore-outer" not in caplog.text
    assert "forged outer rescore log" not in caplog.text
    assert "Traceback" not in caplog.text
