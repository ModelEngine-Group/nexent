# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The shared highlight parser emits only unique plain matched terms."""

from nexent.vector_database.utils import extract_highlight_terms


def test_trusted_markers_are_removed_and_terms_are_deduplicated():
    highlights = {"title": ["__nexent_hit_start__router__nexent_hit_end__"],
                  "content": ["prefix __nexent_hit_start__router__nexent_hit_end__ and __nexent_hit_start__404__nexent_hit_end__"]}
    assert extract_highlight_terms(highlights) == ["router", "404"]
    assert extract_highlight_terms({}) == []
    assert extract_highlight_terms({"content": ["<em>untrusted marker</em>"]}) == []
