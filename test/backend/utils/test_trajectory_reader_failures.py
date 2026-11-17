# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Malformed and truncated JSON never escapes the bounded archive reader."""

import json
from io import BytesIO

import pytest
from infrastructure.observability.trajectory_io import TrajectoryCorrupt
from infrastructure.observability.trajectory_reader import JSONReader, read_text
from ops.services.trajectory.quantiles import DiskQuantiles


@pytest.mark.parametrize(
    "raw,message",
    [
        (b'"unfinished', "Unterminated"),
        (b'"\\q"', "Invalid JSON escape"),
        (b'"\\uZZZZ"', "unicode escape"),
        (b'"\\uDC00"', "Unpaired"),
        (b'"\\uD800\\u0000"', "surrogate pair"),
        (b'"\\uD800x"', "Unpaired"),
        (b'{"x" 1}', "colon"),
        (b"[1;2]", "scalar"),
        (b"[1:2]", "scalar"),
        (b"[1 true]", "separator"),
        (b"[" + b"9" * 129 + b"]", "scalar"),
        (b"1e999", "scalar"),
        (b'{"' + b"x" * 1025 + b'":1}', "key"),
        (b"[", "scalar"),
    ],
)
def test_invalid_json_has_explicit_diagnostic(tmp_path, raw, message):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with path.open("rb") as file, pytest.raises(TrajectoryCorrupt, match=message):
        JSONReader(file.fileno(), len(raw), buffer_size=3).value()


def test_confirmed_length_cannot_extend_past_actual_file(tmp_path):
    path = tmp_path / "short.json"
    path.write_bytes(b'"abc')
    with path.open("rb") as file:
        with pytest.raises(TrajectoryCorrupt, match="prefix is missing"):
            JSONReader(file.fileno(), 9).value()
        with pytest.raises(TrajectoryCorrupt, match="end of JSON"):
            JSONReader(file.fileno(), 0).take()
        with pytest.raises(TrajectoryCorrupt, match="Expected a JSON string"):
            list(JSONReader(file.fileno(), 4, start=1).string_parts())


def test_empty_containers_and_primitives_survive_tiny_buffers(tmp_path):
    value = [{}, [], None, True, False, 0, -1.5, "\b\f\r/😀"]
    path = tmp_path / "valid.json"
    path.write_text(json.dumps(value))
    with path.open("rb") as file:
        assert (
            JSONReader(file.fileno(), path.stat().st_size, buffer_size=1).value()
            == value
        )


@pytest.mark.parametrize(
    "offset,limit",
    [(-1, 4), (True, 4), (0, 3), (0, True), (0, 1048577), (100, 4), (1, 4)],
)
def test_body_byte_ranges_reject_invalid_or_split_codepoints(tmp_path, offset, limit):
    path = tmp_path / "text.json"
    path.write_text(json.dumps("中文", ensure_ascii=False))
    with path.open("rb") as file, pytest.raises(ValueError):
        read_text(file.fileno(), 0, path.stat().st_size, offset=offset, limit=limit)


@pytest.mark.parametrize("value", [True, -1, "1", float("inf"), float("nan")])
def test_quantiles_reject_invalid_samples_and_truncated_sort_file(value):
    with (
        DiskQuantiles() as calculator,
        pytest.raises(ValueError, match="Invalid percentile sample"),
    ):
        calculator.add(value)
    with pytest.raises(ValueError, match="truncated"):
        list(DiskQuantiles._values(BytesIO(b"short")))


def test_quantiles_empty_flush_is_idempotent():
    with DiskQuantiles() as calculator:
        calculator._flush()
        assert calculator.paths == [] and calculator.count == 0
