# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact linear-interpolated percentiles with bounded in-memory sample sorting."""

import heapq
import math
import struct
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory


class DiskQuantiles:
    def __init__(self, check=lambda: None, chunk_size=65536):
        self.check, self.chunk_size = check, chunk_size
        self._temporary = TemporaryDirectory(prefix="nexent-trajectory-statistics-")
        self.root = Path(self._temporary.name)
        self.buffer = []
        self.paths = []
        self.count = 0
        self.serial = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._temporary.cleanup()

    def add(self, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("Invalid percentile sample")
        self.buffer.append(float(value))
        self.count += 1
        if len(self.buffer) >= self.chunk_size:
            self._flush()

    def _path(self):
        self.serial += 1
        return self.root / f"{self.serial}.bin"

    @staticmethod
    def _values(file):
        while data := file.read(8):
            if len(data) != 8:
                raise ValueError("Statistics sort file is truncated")
            yield struct.unpack("d", data)[0]

    def _flush(self):
        if not self.buffer:
            return
        self.check()
        self.buffer.sort()
        path = self._path()
        with path.open("wb") as file:
            for value in self.buffer:
                file.write(struct.pack("d", value))
        self.paths.append(path)
        self.buffer.clear()

    def result(self):
        self._flush()
        if not self.count:
            return {"p50_ms": None, "p90_ms": None, "p99_ms": None, "sample_count": 0}
        while len(self.paths) > 64:
            merged = []
            for start in range(0, len(self.paths), 64):
                self.check()
                group = self.paths[start : start + 64]
                path = self._path()
                with ExitStack() as stack, path.open("wb") as output:
                    sources = [
                        self._values(stack.enter_context(p.open("rb"))) for p in group
                    ]
                    for index, value in enumerate(heapq.merge(*sources)):
                        if index % 65536 == 0:
                            self.check()
                        output.write(struct.pack("d", value))
                for old in group:
                    old.unlink()
                merged.append(path)
            self.paths = merged
        positions = {p: (self.count - 1) * p / 100 for p in (50, 90, 99)}
        needed = {
            i for pos in positions.values() for i in (math.floor(pos), math.ceil(pos))
        }
        found = {}
        with ExitStack() as stack:
            sources = [
                self._values(stack.enter_context(p.open("rb"))) for p in self.paths
            ]
            for index, value in enumerate(heapq.merge(*sources)):
                if index % 65536 == 0:
                    self.check()
                if index in needed:
                    found[index] = value
                if len(found) == len(needed):
                    break
        return {
            **{
                f"p{p}_ms": found[math.floor(pos)]
                + (found[math.ceil(pos)] - found[math.floor(pos)]) * (pos % 1)
                for p, pos in positions.items()
            },
            "sample_count": self.count,
        }
