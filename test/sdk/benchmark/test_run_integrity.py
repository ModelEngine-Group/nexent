import json
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic import run_integrity


class FakeLangfuse:
    def __init__(self, traces=None, run=None, dataset_items=None):
        self.traces = traces or {}
        self.run = run
        self.dataset = SimpleNamespace(items=dataset_items or [])

    def get_trace(self, trace_id):
        return self.traces[trace_id]

    def get_dataset_run(self, dataset_name, run_name):
        if self.run is None:
            raise RuntimeError("run unavailable")
        return self.run

    def auth_check(self):
        return True

    def get_dataset(self, dataset_name):
        return self.dataset


def _complete_output(**overrides):
    output = {
        "agent_config": {"name": "agent"},
        "compression": {"calls": 0},
        "model_config": {"model_name": "model"},
        "provider_cache": {"status": "unsupported"},
        "system_prompt": "system",
        "errors": [],
    }
    output.update(overrides)
    return output


def test_check_run_integrity_accepts_complete_run_and_matching_manifest(monkeypatch):
    run = SimpleNamespace(
        dataset_run_items=[
            SimpleNamespace(dataset_item_id="one", trace_id="trace-one"),
            SimpleNamespace(dataset_item_id="two", trace_id="trace-two"),
        ]
    )
    langfuse = FakeLangfuse(
        run=run,
        traces={
            "trace-one": SimpleNamespace(
                scores=[SimpleNamespace(name="exact_match", value=1.0)],
                output=_complete_output(),
            ),
            "trace-two": SimpleNamespace(
                scores=[SimpleNamespace(name="exact_match", value=0.0)],
                output=json.dumps(_complete_output()),
            ),
        },
    )
    monkeypatch.setattr(
        run_integrity,
        "fetch_complete_dataset_run",
        lambda *args, **kwargs: run,
    )

    report = run_integrity.check_run_integrity(
        langfuse=langfuse,
        dataset_name="dataset",
        run_name="run",
        expected_item_ids=["one", "two"],
        evaluator_names=["exact_match"],
        manifest={
            "dataset_item_ids": ["one", "two"],
            "evaluator_names": ["exact_match"],
        },
    )

    assert report.run_complete is True
    assert report.to_dict()["linked_trace_count"] == 2
    assert "Status: COMPLETE" in report.summary()


def test_check_run_integrity_reports_all_incomplete_run_causes(monkeypatch):
    run = SimpleNamespace(
        dataset_run_items=[
            SimpleNamespace(dataset_item_id="one", trace_id="trace-empty"),
            SimpleNamespace(dataset_item_id="one", trace_id="trace-incomplete"),
            SimpleNamespace(dataset_item_id="three", trace_id="trace-error"),
        ]
    )
    langfuse = FakeLangfuse(
        run=run,
        traces={
            "trace-empty": SimpleNamespace(scores=[], output=None),
            "trace-incomplete": SimpleNamespace(
                scores=[SimpleNamespace(name="other", value=1.0)],
                output={"agent_config": {}},
            ),
            "trace-error": SimpleNamespace(
                scores=[SimpleNamespace(name="exact_match", value=1.0)],
                output=_complete_output(errors=["tool failed"]),
            ),
        },
    )
    monkeypatch.setattr(
        run_integrity,
        "fetch_complete_dataset_run",
        lambda *args, **kwargs: run,
    )

    report = run_integrity.check_run_integrity(
        langfuse=langfuse,
        dataset_name="dataset",
        run_name="run",
        expected_item_ids=["one", "two"],
        evaluator_names=["exact_match"],
        manifest={
            "dataset_item_ids": ["one", "two", "manifest-only"],
            "evaluator_names": ["exact_match", "manifest-score"],
        },
    )

    assert report.run_complete is False
    assert report.missing_item_ids == ["two"]
    assert report.duplicate_item_ids == ["one"]
    assert report.missing_scores == {"one": ["exact_match"]}
    assert report.empty_outputs == ["one", "one"]
    assert report.trace_errors == ["three"]
    assert len(report.config_mismatches) == 3
    summary = report.summary()
    assert "Status: INCOMPLETE" in summary
    assert "Missing item IDs: two" in summary
    assert "Duplicate item IDs: one" in summary
    assert "Trace errors: three" in summary
    assert "Config mismatches:" in summary


def test_check_run_integrity_returns_missing_report_when_run_cannot_be_loaded(
    monkeypatch,
):
    langfuse = FakeLangfuse()
    monkeypatch.setattr(
        run_integrity,
        "fetch_complete_dataset_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("not ready")),
    )

    report = run_integrity.check_run_integrity(
        langfuse=langfuse,
        dataset_name="dataset",
        run_name="missing",
        expected_item_ids=["one", "two"],
        evaluator_names=["exact_match"],
    )

    assert report.run_complete is False
    assert report.linked_trace_count == 0
    assert report.missing_item_ids == ["one", "two"]


@pytest.mark.parametrize(
    ("raw_output", "expected"),
    [
        (None, {}),
        ({"answer": 1}, {"answer": 1}),
        ('{"answer": 1}', {"answer": 1}),
        ("[]", {}),
        ("not-json", {}),
        (123, {}),
    ],
)
def test_parse_trace_output_accepts_only_mapping_outputs(raw_output, expected):
    assert run_integrity._parse_trace_output(raw_output) == expected


def test_integrity_cli_loads_manifest_and_exits_zero_for_complete_run(
    monkeypatch,
    tmp_path,
    capsys,
):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"dataset_item_ids":["one"]}', encoding="utf-8")
    args = SimpleNamespace(
        dataset="dataset",
        run_name="run",
        evaluators=["exact_match"],
        manifest=manifest_path,
    )
    monkeypatch.setattr(run_integrity, "_parse_cli_args", lambda: args)
    langfuse = FakeLangfuse(dataset_items=[SimpleNamespace(id="one")])
    monkeypatch.setattr("langfuse.Langfuse", lambda: langfuse)
    report = run_integrity.IntegrityReport(
        run_name="run",
        dataset_name="dataset",
        run_complete=True,
        expected_item_count=1,
        linked_trace_count=1,
        unique_item_count=1,
    )
    checked = {}

    def fake_check_run_integrity(**kwargs):
        checked.update(kwargs)
        return report

    monkeypatch.setattr(
        run_integrity,
        "check_run_integrity",
        fake_check_run_integrity,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_integrity.main()

    assert exc_info.value.code == 0
    assert checked["manifest"] == {"dataset_item_ids": ["one"]}
    assert checked["expected_item_ids"] == ["one"]
    assert "Status: COMPLETE" in capsys.readouterr().out
