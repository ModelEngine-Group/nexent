import hashlib
import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../../.."))


class PipelineMemoryRecord:
    def __init__(self, **kwargs):
        self.record_id = kwargs.get("record_id", "")
        self.content = kwargs.get("content", "")
        self.score = kwargs.get("score", 0.0)
        self.fused_score = kwargs.get("fused_score", 0.0)
        self.__dict__.update(kwargs)


def _dedup_by_content_hash(candidates):
    seen = {}
    result = []
    for c in candidates:
        h = hashlib.sha256(c.content.encode()).hexdigest()
        if h not in seen:
            seen[h] = len(result)
            result.append(c)
    return result


def _make_record(content, record_id="1", score=0.9):
    return PipelineMemoryRecord(
        record_id=record_id,
        content=content,
        score=score,
        fused_score=score,
    )


def test_identical_content_merged():
    r1 = _make_record("hello world", record_id="1", score=0.9)
    r2 = _make_record("hello world", record_id="2", score=0.8)
    result = _dedup_by_content_hash([r1, r2])
    assert len(result) == 1
    assert result[0].record_id == "1"


def test_different_content_preserved():
    r1 = _make_record("hello world", record_id="1")
    r2 = _make_record("goodbye world", record_id="2")
    result = _dedup_by_content_hash([r1, r2])
    assert len(result) == 2


def test_empty_candidates():
    result = _dedup_by_content_hash([])
    assert result == []


def test_multiple_duplicates_keeps_first():
    r1 = _make_record("same content", record_id="1", score=0.95)
    r2 = _make_record("different", record_id="2", score=0.8)
    r3 = _make_record("same content", record_id="3", score=0.7)
    result = _dedup_by_content_hash([r1, r2, r3])
    assert len(result) == 2
    assert result[0].record_id == "1"
    assert result[1].record_id == "2"


def test_three_identical_keeps_only_first():
    r1 = _make_record("dup", record_id="1", score=0.9)
    r2 = _make_record("dup", record_id="2", score=0.8)
    r3 = _make_record("dup", record_id="3", score=0.7)
    result = _dedup_by_content_hash([r1, r2, r3])
    assert len(result) == 1
    assert result[0].record_id == "1"


def test_whitespace_matters_in_hash():
    r1 = _make_record("hello world", record_id="1")
    r2 = _make_record("hello  world", record_id="2")
    result = _dedup_by_content_hash([r1, r2])
    assert len(result) == 2


def test_case_matters_in_hash():
    r1 = _make_record("Hello World", record_id="1")
    r2 = _make_record("hello world", record_id="2")
    result = _dedup_by_content_hash([r1, r2])
    assert len(result) == 2


def test_order_preserved():
    records = [_make_record(f"content_{i}", record_id=str(i)) for i in range(5)]
    result = _dedup_by_content_hash(records)
    assert [r.record_id for r in result] == ["0", "1", "2", "3", "4"]
