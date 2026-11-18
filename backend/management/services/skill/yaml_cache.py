# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bounded cache of successful parses of already validated local skill paths."""

import os
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
from threading import Lock
from typing import Any


class SkillYamlCache:
    """Read every file snapshot and reuse only its successful parse."""

    def __init__(self, max_entries: int = 256, max_bytes: int = 8 * 1024 * 1024):
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries = OrderedDict()
        self._bytes = 0
        self._lock = Lock()
        # Fixed stripes bound synchronization state, including for failed paths.
        self._stripes = tuple(Lock() for _ in range(32))

    def load(self, path: str, parser: Callable[[bytes], Any]) -> Any:
        """Load a file snapshot; the caller retains path and error policy ownership."""
        key = (os.path.abspath(path), parser)
        with self._stripes[hash(key) % len(self._stripes)]:
            # Read each time: same-size edits can retain timestamps, and read access
            # may change independently of the file metadata used by stat().
            with open(path, "rb") as stream:
                raw = stream.read()
            signature = sha256(raw).digest()
            with self._lock:
                cached = self._entries.pop(key, None)
                if cached is not None:
                    if cached[0] == signature:
                        self._entries[key] = cached
                    else:
                        self._bytes -= cached[2]
                        cached = None
            if cached is not None:
                return deepcopy(cached[1])

            parsed = parser(raw)
            if self._max_entries > 0 and len(raw) <= self._max_bytes:
                value = deepcopy(parsed)
                with self._lock:
                    self._entries[key] = (signature, value, len(raw))
                    self._bytes += len(raw)
                    while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                        _, (_, _, size) = self._entries.popitem(last=False)
                        self._bytes -= size
            return parsed


skill_yaml_cache = SkillYamlCache()
