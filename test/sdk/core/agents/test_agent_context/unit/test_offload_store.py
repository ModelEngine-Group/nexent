"""
unit/test_offload_store.py
Tests for OffloadStore: store, reload, list_active, build_reload_inventory,
tokenize, score, eviction, and diagnostics.
"""

import uuid
import pytest

from loader import OffloadStore


# ──────────────────────────────────────────────────────────────
# store()
# ──────────────────────────────────────────────────────────────

class TestStore:

    def test_store_returns_valid_handle_and_retrievable_content(self):
        store = OffloadStore()
        handle = store.store("hello world", description="short desc")
        assert isinstance(handle, str) and len(handle) == 32
        uuid.UUID(hex=handle)
        assert store.reload(handle) == "hello world"
        assert store.list_active()[0][1] == "short desc"

    def test_store_max_entry_chars_boundary(self):
        store = OffloadStore(max_entry_chars=10)
        assert store.store("x" * 11) is None
        assert store.store("x" * 10) is not None

    def test_multiple_stores_increment_count(self):
        store = OffloadStore()
        for _ in range(3):
            store.store("x")
        assert len(store) == 3

    def test_store_empty_inputs(self):
        store = OffloadStore()
        handle = store.store("")
        assert handle is not None and store.reload(handle) == ""
        assert store.list_active()[0][1] == ""


# ──────────────────────────────────────────────────────────────
# reload()
# ──────────────────────────────────────────────────────────────

class TestReload:

    def test_reload_valid_and_invalid_handles(self):
        store = OffloadStore()
        h = store.store("exact content")
        assert store.reload(h) == "exact content"
        assert store.reload("nonexistent") is None

    def test_reload_after_eviction_returns_none(self):
        store = OffloadStore(max_entries=1)
        h1 = store.store("first")
        store.store("second")  # evicts first
        assert store.reload(h1) is None

    def test_reload_hits_and_misses_diagnostics(self):
        store = OffloadStore()
        h = store.store("data")
        store.reload(h)
        store.reload(h)
        store.reload("bad")
        assert store.reload_hits == 2
        assert store.reload_misses == 1


# ──────────────────────────────────────────────────────────────
# list_active()
# ──────────────────────────────────────────────────────────────

class TestListActive:

    def test_empty_store_returns_empty_list(self):
        store = OffloadStore()
        assert store.list_active() == []

    def test_returns_handle_description_pairs(self):
        store = OffloadStore()
        h1 = store.store("content1", "desc1")
        h2 = store.store("content2", "desc2")
        active = store.list_active()
        assert len(active) == 2
        assert (h1, "desc1") in active
        assert (h2, "desc2") in active

    def test_evicted_entries_not_listed(self):
        store = OffloadStore(max_entries=2)
        store.store("a", "first")
        store.store("b", "second")
        store.store("c", "third")  # evicts first
        active = store.list_active()
        assert len(active) == 2
        descriptions = [d for _, d in active]
        assert "first" not in descriptions
        assert "second" in descriptions
        assert "third" in descriptions


# ──────────────────────────────────────────────────────────────
# Eviction
# ──────────────────────────────────────────────────────────────

class TestEviction:

    def test_count_based_eviction_fifo(self):
        store = OffloadStore(max_entries=3)
        handles = [store.store(f"item{i}") for i in range(5)]
        assert len(store) == 3
        # First two should be evicted
        assert store.reload(handles[0]) is None
        assert store.reload(handles[1]) is None
        assert store.reload(handles[2]) == "item2"
        assert store.reload(handles[3]) == "item3"
        assert store.reload(handles[4]) == "item4"

    def test_size_based_eviction(self):
        store = OffloadStore(max_total_chars=20)
        store.store("A" * 12)  # 12 chars
        h2 = store.store("B" * 12)  # would be 24 total, evicts first
        assert len(store) == 1
        assert store.reload(h2) == "B" * 12

    def test_size_eviction_evicts_multiple_if_needed(self):
        store = OffloadStore(max_total_chars=30)
        store.store("A" * 10)  # 10
        store.store("B" * 10)  # 20 total
        store.store("C" * 25)  # 25 would make 45, evict both A and B
        assert len(store) == 1

    def test_store_rejects_oversized_content_only(self):
        """Content over max_entry_chars is rejected; smaller ones still accepted."""
        store = OffloadStore(max_entry_chars=20)
        h1 = store.store("ok size")
        h2 = store.store("x" * 25)
        assert h1 is not None
        assert h2 is None
        assert len(store) == 1

    def test_clear_removes_all_entries(self):
        store = OffloadStore()
        store.store("a")
        store.store("b")
        store.clear()
        assert len(store) == 0
        assert store.list_active() == []

    def test_clear_resets_total_chars(self):
        store = OffloadStore(max_total_chars=10)
        store.store("1234567890")  # 10 chars fills it up
        store.clear()
        # After clear, should be able to store another 10 chars
        h = store.store("abcdefghij")
        assert h is not None


# ──────────────────────────────────────────────────────────────
# items() and __len__
# ──────────────────────────────────────────────────────────────

class TestItemsAndLen:

    def test_len_reflects_entry_count(self):
        store = OffloadStore()
        assert len(store) == 0
        store.store("a")
        assert len(store) == 1
        store.store("b")
        assert len(store) == 2

    def test_items_returns_handle_content_pairs(self):
        store = OffloadStore()
        h1 = store.store("content_a")
        h2 = store.store("content_b")
        items = store.items()
        assert len(items) == 2
        contents = [c for _, c in items]
        assert "content_a" in contents
        assert "content_b" in contents

    def test_items_is_snapshot(self):
        store = OffloadStore()
        store.store("a")
        items = store.items()
        store.store("b")
        assert len(items) == 1  # snapshot is frozen

    def test_items_empty_store(self):
        store = OffloadStore()
        assert store.items() == []


# ──────────────────────────────────────────────────────────────
# build_reload_inventory()
# ──────────────────────────────────────────────────────────────

class TestBuildReloadInventory:

    def test_disabled_returns_none(self):
        store = OffloadStore()
        store.store("content", "desc")
        assert store.build_reload_inventory(enable_reload=False) is None

    def test_empty_store_returns_none(self):
        store = OffloadStore()
        assert store.build_reload_inventory(enable_reload=True) is None

    def test_no_query_returns_recent_entries(self):
        store = OffloadStore()
        store.store("old", "oldest")
        store.store("mid", "middle")
        store.store("new", "newest")
        result = store.build_reload_inventory(enable_reload=True, max_items=2)
        assert result is not None
        assert "newest" in result
        assert "middle" in result
        assert "oldest" not in result

    def test_header_text_present(self):
        store = OffloadStore()
        store.store("data", "test_desc")
        result = store.build_reload_inventory(enable_reload=True)
        assert "[System Notice" in result
        assert "handle=" in result
        assert "test_desc" in result

    def test_max_items_caps_output(self):
        store = OffloadStore()
        for i in range(10):
            store.store(f"content{i}", f"desc{i}")
        result = store.build_reload_inventory(enable_reload=True, max_items=3)
        lines = [l for l in result.split("\n") if l.startswith("- handle=")]
        assert len(lines) == 3

    def test_with_query_scores_and_ranks(self):
        store = OffloadStore()
        store.store("irrelevant", "nothing here")
        store.store("target", "important database query result")
        store.store("other", "some other text")
        result = store.build_reload_inventory(
            enable_reload=True, query="database result", max_items=2
        )
        assert result is not None
        # "database" should match in the description
        assert "important database query result" in result

    def test_with_query_no_matches_falls_back_to_recency(self):
        store = OffloadStore()
        store.store("a", "first entry")
        store.store("b", "second entry")
        store.store("c", "third entry")
        result = store.build_reload_inventory(
            enable_reload=True, query="zzz_nonexistent_xyz", max_items=2
        )
        assert result is not None
        # Falls back to recency (tail)
        assert "third entry" in result
        assert "second entry" in result

    def test_query_with_unicode(self):
        store = OffloadStore()
        store.store("数据", "数据库查询结果")
        store.store("other", "unrelated")
        result = store.build_reload_inventory(
            enable_reload=True, query="数据库", max_items=1
        )
        assert result is not None
        assert "数据库查询结果" in result


# ──────────────────────────────────────────────────────────────
# _tokenize (static method)
# ──────────────────────────────────────────────────────────────

class TestTokenize:

    def test_latin_tokenization(self):
        tokens = OffloadStore._tokenize("Hello, WORLD! test.")
        assert tokens >= {"hello", "world", "test"}
        assert "," not in tokens and "!" not in tokens

    def test_filters_stop_words_short_tokens_and_digits(self):
        tokens = OffloadStore._tokenize("the a is 42 score cd points 123")
        assert tokens & {"the", "a", "is", "42", "123"} == set()
        assert tokens >= {"score", "points"}
        assert "cd" in tokens

    def test_cjk_tokenization(self):
        # multi-char → bigrams
        tokens = OffloadStore._tokenize("数据库查询")
        assert tokens >= {"数据", "据库", "库查", "查询"}
        # single CJK char → no bigrams produced
        assert OffloadStore._tokenize("数") == set()

    def test_mixed_cjk_and_latin(self):
        tokens = OffloadStore._tokenize("hello 数据库 world")
        assert tokens >= {"hello", "world", "数据", "据库"}

    def test_tokenize_empty_string(self):
        assert OffloadStore._tokenize("") == set()


# ──────────────────────────────────────────────────────────────
# _score_description (private, tested via public API + direct)
# ──────────────────────────────────────────────────────────────

class TestScoreDescription:

    def test_exact_match_score(self):
        store = OffloadStore()
        desc_tokens = store._tokenize("database query result")
        query_tokens = store._tokenize("database query")
        score = store._score_description(desc_tokens, query_tokens)
        assert score > 0
        # exact matches: database, query → overlap=2, 2^2/min(3,8)=4/3≈1.33
        assert score == pytest.approx(4.0 / 3.0, abs=0.01)

    def test_no_match_returns_zero(self):
        store = OffloadStore()
        desc_tokens = store._tokenize("hello world")
        query_tokens = store._tokenize("xyzzy")
        score = store._score_description(desc_tokens, query_tokens)
        assert score == 0.0

    def test_empty_desc_tokens_returns_zero(self):
        store = OffloadStore()
        score = store._score_description(set(), {"hello"})
        assert score == 0.0

    def test_partial_substring_match(self):
        store = OffloadStore()
        desc_tokens = store._tokenize("download")
        query_tokens = store._tokenize("down")
        score = store._score_description(desc_tokens, query_tokens)
        # "down" in "download" → 0.5, squared/min(1,8) = 0.25
        assert score == pytest.approx(0.25, abs=0.01)

    def test_multiple_matches_amplified(self):
        store = OffloadStore()
        desc_tokens = store._tokenize("database sql query result")
        query_tokens = store._tokenize("database query sql")
        score = store._score_description(desc_tokens, query_tokens)
        # 3 exact matches → overlap=3, 3^2/min(4,8)=9/4=2.25
        assert score == pytest.approx(9.0 / 4.0, abs=0.01)

    def test_cjk_score(self):
        store = OffloadStore()
        desc_tokens = store._tokenize("数据库查询优化")
        query_tokens = store._tokenize("数据库")
        score = store._score_description(desc_tokens, query_tokens)
        # desc tokens: 7 (6 CJK bigrams + full word "数据库查询优化")
        # query tokens: 3 (2 CJK bigrams + full word "数据库")
        # Exact: "数据" + "据库" → overlap=2.0
        # Partial: "数据库" in "数据库查询优化" → +0.5
        # score = 2.5^2 / min(7,8) = 6.25/7 ≈ 0.8929
        assert score == pytest.approx(6.25 / 7.0, abs=0.01)


# ──────────────────────────────────────────────────────────────
# Custom constructor parameters
# ──────────────────────────────────────────────────────────────

class TestCustomConfig:

    @pytest.mark.parametrize("kwargs, expected", [
        ({}, (200, 2_000_000, 30000)),
        ({"max_entries": 50, "max_total_chars": 10000, "max_entry_chars": 500},
         (50, 10000, 500)),
    ])
    def test_config_defaults_and_custom(self, kwargs, expected):
        store = OffloadStore(**kwargs)
        assert store._max_entries == expected[0]
        assert store._max_total_chars == expected[1]
        assert store._max_entry_chars == expected[2]


# ──────────────────────────────────────────────────────────────
# Integration with ContextManager
# ──────────────────────────────────────────────────────────────

class TestContextManagerOffloadStore:

    def test_cm_offload_store_integration(self):
        from factories import make_cm
        cm = make_cm()
        assert isinstance(cm.offload_store, OffloadStore)
        # Singleton property
        assert cm.offload_store is cm.offload_store
        # Functional end-to-end
        handle = cm.offload_store.store("cm content", "cm desc")
        assert handle and cm.offload_store.reload(handle) == "cm content"
        assert cm.offload_store.reload_hits == 1
