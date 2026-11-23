import json

from nexent.core.agents.context.long_term_memory_selector import (
    parse_markdown_blocks,
    select_long_term_memory,
)


class Model:
    model_id = "selector-test"

    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = 0

    def __call__(self, messages, stop_sequences):
        self.calls += 1
        if self.error:
            raise self.error
        return type("Response", (), {"content": self.content})()


def test_block_ids_are_stable_and_scoped():
    markdown = "## Preferences\n\n- concise\n- English\n"
    first = parse_markdown_blocks("user", markdown)
    second = parse_markdown_blocks("user", markdown)
    assert [block.block_id for block in first] == [block.block_id for block in second]
    assert all(block.block_id.startswith("user:") for block in first)


def test_one_call_selects_both_scopes_and_preserves_markdown_order():
    docs = {"tenant": "## Policy\n\n- safe", "user": "## Preference\n\n- concise"}
    ids = {scope: [block.block_id for block in parse_markdown_blocks(scope, text)] for scope, text in docs.items()}
    model = Model(json.dumps({"selections": ids}))
    selected, audit = select_long_term_memory(
        docs, task="answer", target_tokens=100, model=model, chars_per_token=4,
    )
    assert model.calls == 1
    assert selected["tenant"] == docs["tenant"]
    assert selected["user"] == docs["user"]
    assert audit["outcome"] == "selected"


def test_unknown_cross_scope_duplicate_and_model_error_use_fallback():
    docs = {"tenant": "## Policy\n\n- safe", "user": "## Preference\n\n- concise"}
    for output in (
        {"selections": {"tenant": ["user:unknown"], "user": []}},
        {"selections": {"tenant": [], "user": ["user:x", "user:x"]}},
    ):
        selected, audit = select_long_term_memory(
            docs, task="answer", target_tokens=20, model=Model(json.dumps(output)), chars_per_token=4,
        )
        assert audit["outcome"] == "fallback"
        assert set(selected) == {"tenant", "user"}
    _, audit = select_long_term_memory(
        docs, task="answer", target_tokens=20, model=Model(error=TimeoutError()), chars_per_token=4,
    )
    assert audit["outcome"] == "fallback"
