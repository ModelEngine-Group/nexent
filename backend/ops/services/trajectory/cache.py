# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Byte-bounded process-local caches; eviction explicitly resets query snapshots."""

import threading
import time
from collections import OrderedDict


class ByteCache:
    def __init__(self, max_bytes=32 * 1024 * 1024, ttl=1800):
        self.max_bytes, self.ttl = max_bytes, ttl
        self.entries, self.size = OrderedDict(), 0
        self.lock = threading.Lock()
        self.hits = self.misses = 0

    def put(self, key, value, size):
        if size > self.max_bytes:
            return False
        with self.lock:
            if key in self.entries:
                self.size -= self.entries.pop(key)[2]
            self.entries[key] = (time.monotonic() + self.ttl, value, size)
            self.size += size
            while self.size > self.max_bytes:
                self.size -= self.entries.popitem(last=False)[1][2]
        return True

    def get(self, key):
        with self.lock:
            if key not in self.entries:
                self.misses += 1
                return None
            deadline, value, size = self.entries[key]
            if deadline <= time.monotonic():
                self.entries.pop(key)
                self.size -= size
                self.misses += 1
                return None
            self.entries.move_to_end(key)
            self.hits += 1
            return value
