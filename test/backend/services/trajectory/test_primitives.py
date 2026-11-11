# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for authenticated references and bounded JSON strings."""

import json
import os

import pytest
from infrastructure.observability.trajectory_io import TrajectoryCorrupt
from infrastructure.observability.trajectory_reader import JSONReader, read_text
from management.services.trajectory.primitives import (
    percentiles,
)


@pytest.mark.parametrize("ensure_ascii", [True, False])
def test_incremental_unicode_body_and_offsets(tmp_path, ensure_ascii):
    body = ('汉字😀\\"\n\t' * 10000) + "\n"
    path = tmp_path / "body.json"
    path.write_text(
        json.dumps({"body": body, "number": 12}, ensure_ascii=ensure_ascii),
        encoding="utf8",
    )
    fd = os.open(path, os.O_RDONLY)
    try:
        result = JSONReader(fd, path.stat().st_size, buffer_size=97).value()
        text = result["body"]
        assert len(text.encode()) <= 16384
        assert text.char_count == len(body)
        assert text.byte_count == len(body.encode())
        chunks = []
        offset = 0
        while offset < text.byte_count:
            chunk = read_text(fd, text.start, text.end, offset=offset, limit=1001)
            assert len(chunk["text"].encode()) <= 1001
            assert chunk["offset"] == offset
            offset = chunk["next_offset"]
            chunks.append(chunk["text"])
        assert "".join(chunks) == body
        assert result["number"] == 12
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":NaN}',
        b'{"x":"\\uD800"}',
        b'{"x":1,"x":2}',
        b'{"x":"\x00"}',
        b"[" * 66 + b"0" + b"]" * 66,
    ],
)
def test_bad_json_is_not_silently_accepted(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    fd = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises((TrajectoryCorrupt, UnicodeError)):
            JSONReader(fd, len(raw)).value()
    finally:
        os.close(fd)


def test_full_result_percentiles():
    assert percentiles([]) == {
        "p50_ms": None,
        "p90_ms": None,
        "p99_ms": None,
        "sample_count": 0,
    }
    assert percentiles([0, 10]) == {
        "p50_ms": 5,
        "p90_ms": 9,
        "p99_ms": 9.9,
        "sample_count": 2,
    }


def test_parser_resource_limit_is_distinct_from_file_corruption(tmp_path):
    from infrastructure.observability.trajectory_reader import (
        TrajectoryReadBudgetExceeded,
    )

    path = tmp_path / "value.json"
    path.write_text('"valid"')
    with path.open("rb") as stream:
        reader = JSONReader(stream.fileno(), path.stat().st_size)
        reader.retained = 16 * 1024 * 1024
        with pytest.raises(TrajectoryReadBudgetExceeded):
            reader.value()
        reader = JSONReader(stream.fileno(), path.stat().st_size)
        reader.values = 500_000
        with pytest.raises(TrajectoryReadBudgetExceeded):
            reader.value()
