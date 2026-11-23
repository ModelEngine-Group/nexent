import json
from types import SimpleNamespace

import pytest

from sdk.benchmark.generic.runtime import exa_replay
from sdk.benchmark.generic.runtime.exa_replay import ExaReplayController


def test_record_reuses_cached_result_without_second_live_call(tmp_path):
    controller = ExaReplayController("record", tmp_path / "exa.json")
    calls = []

    def live(_tool, query):
        calls.append(query)
        return json.dumps([{"url": "https://example.com", "text": "evidence"}])

    tool = SimpleNamespace(
        max_results=3,
        image_filter=False,
        observer=None,
    )
    first = controller.call(tool, "query", live)
    second = controller.call(tool, "query", live)

    assert first == second
    assert calls == ["query"]
    assert controller.snapshot()["hits"] == 1
    assert controller.snapshot()["live_calls"] == 1


def test_replay_never_falls_back_to_live_on_miss(tmp_path):
    cache_path = tmp_path / "exa.json"
    cache_path.write_text(
        json.dumps({"schema_version": 1, "entries": {}}),
        encoding="utf-8",
    )
    controller = ExaReplayController("replay", cache_path)

    with pytest.raises(RuntimeError, match="live fallback is disabled"):
        controller.call(
            SimpleNamespace(max_results=3, image_filter=False, observer=None),
            "uncached query",
            lambda *_: pytest.fail("live Exa must not be called"),
        )


def test_replay_requires_existing_cache(tmp_path):
    with pytest.raises(FileNotFoundError):
        ExaReplayController("replay", tmp_path / "missing.json")


def test_cache_rejects_invalid_mode_schema_and_entries(tmp_path):
    with pytest.raises(ValueError, match="cache mode"):
        ExaReplayController("off", tmp_path / "cache.json")

    invalid_schema = tmp_path / "invalid-schema.json"
    invalid_schema.write_text('{"schema_version": 2, "entries": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported Exa cache schema"):
        ExaReplayController("replay", invalid_schema)

    invalid_entries = tmp_path / "invalid-entries.json"
    invalid_entries.write_text('{"schema_version": 1, "entries": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Exa replay cache entries"):
        ExaReplayController("replay", invalid_entries)


def test_install_replays_cached_output_emits_observer_events_and_uninstalls(tmp_path):
    from nexent.core.tools.exa_search_tool import ExaSearchTool

    request = {"query": "query", "max_results": 3, "image_filter": False}
    key = exa_replay._cache_key(request)
    output = json.dumps([{"url": "https://example.com"}])
    cache_path = tmp_path / "exa.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    key: {
                        "request": request,
                        "output": output,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    messages = []
    observer = SimpleNamespace(
        add_message=lambda *args: messages.append(args)
    )
    tool = SimpleNamespace(
        max_results=3,
        image_filter=False,
        observer=observer,
        record_ops=0,
    )
    original_forward = ExaSearchTool.forward

    try:
        controller = exa_replay.install_exa_record_replay("replay", cache_path)
        replayed = ExaSearchTool.forward(tool, "query")

        assert replayed == output
        assert controller.snapshot()["hits"] == 1
        assert len(messages) == 2
        assert tool.record_ops == 1
    finally:
        exa_replay.uninstall_exa_record_replay()

    assert ExaSearchTool.forward is original_forward
