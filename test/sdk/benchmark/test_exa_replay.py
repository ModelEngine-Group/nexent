import json
from types import SimpleNamespace

import pytest

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
