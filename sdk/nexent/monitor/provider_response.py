# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded provider JSON capture without retaining individual streaming frames."""

from __future__ import annotations

import json
from io import StringIO


class ProviderResponse:
    """Merge native OpenAI deltas while retaining only fields actually received."""

    def __init__(self, reserve):
        self.reserve = reserve
        self.body = None
        self.seen = self.streaming = self.failed = False

    def _charge(self, value):
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if not self.reserve(size + 4):
            self.failed = True
            return False
        return True

    def response(self, body):
        if self.streaming or self.failed:
            return
        if self.seen and self.body == body:
            return
        if self._charge(body):
            self.body, self.seen = body, True

    def frame(self, body):
        if self.failed or not isinstance(body, dict):
            return
        if not self.seen:
            self.body = {}
        self.seen = self.streaming = True
        self._merge(self.body, body, ())

    def _merge(self, target, incoming, path):
        if len(path) > 64:
            self.failed = True
            raise ValueError("Provider response nesting exceeds 64 levels")
        for key, value in incoming.items():
            if self.failed:
                return
            present = key in target
            if not present and not self._charge(key):
                return
            if value is None and present:
                continue
            previous = target.get(key)
            location = (*path, key)
            if isinstance(value, dict):
                if not isinstance(previous, dict):
                    previous = target[key] = {}
                self._merge(previous, value, location)
            elif isinstance(value, list) and key in {"choices", "tool_calls"}:
                if not isinstance(previous, list):
                    previous = target[key] = []
                for item in value:
                    index = item.get("index") if isinstance(item, dict) else None
                    if type(index) is not int or index < 0:
                        # An invalid protocol item still belongs to the provider, not an internal DTO.
                        if self._charge(item):
                            previous.append(item)
                        continue
                    selected = next((v for v in previous if isinstance(v, dict) and v.get("index") == index), None)
                    if selected is None:
                        if not self._charge({}):
                            return
                        selected = {}
                        previous.append(selected)
                    self._merge(selected, item, location)
                previous.sort(
                    key=lambda item: item["index"] if isinstance(item, dict) and type(item.get("index")) is int else -1
                )
            elif (
                isinstance(value, str)
                and "delta" in path
                and (
                    key in {"content", "reasoning", "reasoning_content", "refusal"}
                    or key in {"name", "arguments"}
                    and path[-1] in {"function", "function_call"}
                )
            ):
                if self._charge(value):
                    if not isinstance(previous, StringIO):
                        previous = target[key] = StringIO()
                    previous.write(value)
            elif not present or previous != value:
                if self._charge(value):
                    target[key] = value

    def value(self):
        def decode(value):
            if isinstance(value, StringIO):
                return value.getvalue()
            if isinstance(value, dict):
                return {key: decode(item) for key, item in value.items()}
            if isinstance(value, list):
                return [decode(item) for item in value]
            return value

        return decode(self.body)
