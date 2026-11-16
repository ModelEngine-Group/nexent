# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile the existing weighted lexical algorithm inside the vector adapter."""

from nexent.core.nlp.tokenizer import calculate_term_weights
from nexent.vector_database.utils import (
    HIGHLIGHT_POST_TAG,
    HIGHLIGHT_PRE_TAG,
    build_weighted_query,
)


def weighted_query(binding, text):
    fields = {"payload." + name: 1 for name in (binding.text_field, *binding.additional_text_fields)}
    query = build_weighted_query(text, calculate_term_weights(text), fields)["query"]
    highlights = {
        "pre_tags": [HIGHLIGHT_PRE_TAG], "post_tags": [HIGHLIGHT_POST_TAG],
        "fields": {name: {"fragment_size": 256, "number_of_fragments": 3} for name in fields},
    }
    if "payload.title" in fields:
        highlights["fields"]["payload.title"] = {"number_of_fragments": 0}
    return query, highlights
