# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Per-run evidence at the root tool's forward boundary, for isolated evaluation."""

import hashlib
import inspect
import json
from functools import wraps
from threading import Lock


def argument_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ReplayToolRecorder:
    def __init__(self, root_config, watched):
        self.root_config = root_config
        self.watched = watched
        self.registered = set()
        self.calls = []
        self.event_index = 0
        self.complete = True
        self.lock = Lock()

    def bind(self, tool, name, mapping_input=False):
        if name not in self.watched or not callable(getattr(tool, "forward", None)):
            return
        input_names = list(getattr(tool, "inputs", {}) or {})
        tool.forward = self.wrap_forward(name, tool.forward, input_names, mapping_input)

    def wrap_forward(self, name, forward, input_names, mapping_input=False):
        if name not in self.watched:
            return forward
        fields = self.watched[name]

        def begin(args, kwargs):
            call = {"name": name, "arguments": {}, "outcome": "pending", "end": None}
            with self.lock:
                self.event_index += 1
                call["start"] = self.event_index
                if len(self.calls) < 512:
                    self.calls.append(call)
                else:
                    self.complete = False
            if mapping_input and len(args) == 1 and isinstance(args[0], dict):
                values = {**args[0], **kwargs}
            else:
                values = {**dict(zip(input_names, args)), **kwargs}
            try:
                for key in fields:
                    if key in values:
                        call["arguments"][key] = argument_digest(values[key])
            except (TypeError, ValueError, RecursionError, UnicodeError):
                with self.lock:
                    self.complete = False
            return call

        def finish(call, outcome):
            with self.lock:
                self.event_index += 1
                call["end"] = self.event_index
                call["outcome"] = outcome

        async def wait_for_return(call, value):
            try:
                result = await value
            except BaseException:
                finish(call, "raised")
                raise
            finish(call, "returned")
            return result

        @wraps(forward)
        def sync_forward(*args, **kwargs):
            call = begin(args, kwargs)
            try:
                result = forward(*args, **kwargs)
            except BaseException:
                finish(call, "raised")
                raise
            if inspect.isawaitable(result):
                return wait_for_return(call, result)
            finish(call, "returned")
            return result

        @wraps(forward)
        async def async_forward(*args, **kwargs):
            return await wait_for_return(begin(args, kwargs), forward(*args, **kwargs))

        with self.lock:
            self.registered.add(name)
        return async_forward if inspect.iscoroutinefunction(forward) else sync_forward

    def receipt(self):
        with self.lock:
            return {"registered": sorted(self.registered), "calls": [dict(c) for c in self.calls],
                    "complete": self.complete and all(c["outcome"] != "pending" for c in self.calls)}


def bind_replay_tool(observer, config, tool, name):
    recorder = getattr(observer, "replay_tool_recorder", None)
    if isinstance(recorder, ReplayToolRecorder) and recorder.root_config is config:
        recorder.bind(tool, name)
