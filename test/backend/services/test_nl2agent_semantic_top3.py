# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent language/pool quotas and raw-cosine cutoff regression proofs."""
import math

import pytest

from services import nl2agent_semantic_retrieval as retrieval
from test.backend.services.test_nl2agent_semantic_retrieval import environment, resource


async def test_bilingual_routes_search_each_pool_then_union_without_truncation(environment):
    _, adapter, _ = environment
    vectors = {"中文": [1., 0., 0.], "English": [0., 1., 0.]}
    catalog = []
    for pool in range(2):
        for index, vector in enumerate([
            [math.sqrt(.5), math.sqrt(.5), 0.],
            [.6, 0., .8], [.59, 0., math.sqrt(1 - .59**2)], [.58, 0., math.sqrt(1 - .58**2)],
            [0., .6, .8], [0., .59, math.sqrt(1 - .59**2)], [0., .58, math.sqrt(1 - .58**2)],
            [.49, .49, math.sqrt(1 - 2 * .49**2)],
        ]):
            item = resource(pool * 10 + index)
            item["installed"] = pool == 0
            vectors[item["name"]] = vector
            catalog.append(item)
    adapter.get_embeddings.side_effect = lambda texts, **kw: [vectors[text.split("\n")[0]] for text in texts]
    # The existing fixture declares a dimension of two; use a three-dimensional model snapshot.
    model = await retrieval.resolve_model("tenant")
    model = (model[0], model[1], 3)
    pair = {"zh": "中文", "en": "English"}
    result = await retrieval.retrieve("tenant", model, {"r1": pair, "r2": pair}, catalog[:8], catalog[8:], None)
    assert result["r1"] == result["r2"]
    for label, base in (("installed", 0), ("installable", 10)):
        rows = result["r1"][label]
        assert {row[1]["candidate_ref"] for row in rows} == {f"tool:{base + i}" for i in (0, 1, 2, 4, 5)}
        assert len(rows) == 5  # Shared language hit is checked once; each route admitted three.
        assert all(score >= .5 for score, _ in rows)
    assert adapter.get_embeddings.call_args_list[0].args[0] == ["中文", "English"]


@pytest.mark.parametrize("threshold,expected", [(.6, ["tool:1"]), (.60001, [])])
async def test_raw_cosine_threshold_is_inclusive_and_never_fills_top3(environment, mocker, threshold, expected):
    _, adapter, _ = environment
    adapter.get_embeddings.side_effect = lambda texts, **kw: [
        [.6, .8] if text.startswith("tool_1\n") else [0., 1.] if "\n" in text else [1., 0.]
        for text in texts]
    mocker.patch.object(retrieval, "NL2AGENT_EMBEDDING_MIN_SIMILARITY", threshold)
    model = await retrieval.resolve_model("tenant")
    result = await retrieval.retrieve("tenant", model, {"r": {"zh": "查询", "en": "query"}},
                                      [resource(i) for i in range(5)], [], None)
    assert [row[1]["candidate_ref"] for row in result["r"]["installed"]] == expected
