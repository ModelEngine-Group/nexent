# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Per-run evidence at the root tool's forward boundary, for isolated evaluation."""

import hashlib
import inspect
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock


def argument_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ReplayToolRecorder:
    def __init__(self, root_config, watched, probe_names=(), *, watch_skill_process=False):
        self.root_config = root_config
        self.watch_skill_process = watch_skill_process
        self.watched = watched
        self.requested = ContextVar("replay_requested_arguments", default=None)
        self.registered = set()
        self.calls = []
        self.event_index = 0
        self.complete = True
        self.catalog = None
        self.tool_patterns = {name: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")
                              for name in probe_names}
        self.lock = Lock()

    def observe_model_input(self, messages, tools=()):
        """Keep only watched names from system instructions and native tool definitions."""
        if self.catalog is None or not self.tool_patterns:
            return
        mentioned = set()
        for message in messages:
            if isinstance(message, dict):
                role, content = message.get("role"), message.get("content")
            elif hasattr(message, "semantic_role"):
                role, content = message.semantic_role, message.content_parts
            else:
                role, content = getattr(message, "role", None), getattr(message, "content", None)
            if getattr(role, "value", role) not in {"system", "developer"}:
                continue
            pieces = [content] if isinstance(content, str) else [
                p["text"] for p in content or () if isinstance(p, dict) and isinstance(p.get("text"), str)]
            for piece in pieces:
                mentioned.update(name for name, pattern in self.tool_patterns.items() if pattern.search(piece))
        schema_names = {tool.name for tool in tools if tool.name in self.tool_patterns}
        with self.lock:
            self.catalog["model_inputs"] += 1
            for key, found in (("instruction_mentions", mentioned), ("native_definitions", schema_names)):
                self.catalog[key] = sorted(found.union(self.catalog[key]))

    def bind(self, tool, name, mapping_input=False):
        if name not in self.watched or not callable(getattr(tool, "forward", None)):
            return
        input_names = list(getattr(tool, "inputs", {}) or {})
        forward = tool.forward
        if name == "run_skill_script" and self.watch_skill_process:
            from nexent.core.agents.resources.replay_scripts import active_script_call
            tool._require_replay_sandbox = True

            def bind_process(call, *args, **kwargs):
                token = active_script_call.set(call)
                try:
                    return forward(*args, **kwargs)
                finally:
                    active_script_call.reset(token)

            tool.forward = self.wrap_forward(name, forward, input_names, mapping_input, process_call=bind_process)
        else:
            tool.forward = self.wrap_forward(name, forward, input_names, mapping_input)

    @contextmanager
    def observe_requested(self, name, values, public_fields):
        """Pair the approved public inputs with the physical call in this task's context."""
        fields = set(self.watched.get(name, ())).intersection(public_fields)
        if not fields:
            yield
            return
        try:
            digests = {key: argument_digest(values[key]) for key in fields if key in values}
        except (TypeError, ValueError, RecursionError, UnicodeError):
            with self.lock:
                self.complete = False
            digests = {}
        token = self.requested.set((name, digests))
        try:
            yield
        finally:
            self.requested.reset(token)

    def bind_requested(self, tool, name):
        if not self.watched.get(name):
            return
        forward = tool.forward
        fields = list(tool.inputs)

        def observe(args, kwargs):
            values = args[0] if len(args) == 1 and isinstance(args[0], dict) and not kwargs else {
                **dict(zip(fields, args)), **kwargs
            }
            return self.observe_requested(name, values, fields)

        @wraps(forward)
        async def async_forward(*args, **kwargs):
            with observe(args, kwargs):
                return await forward(*args, **kwargs)

        @wraps(forward)
        def sync_forward(*args, **kwargs):
            with observe(args, kwargs):
                result = forward(*args, **kwargs)
            if not inspect.isawaitable(result):
                return result

            async def finish():
                with observe(args, kwargs):
                    return await result
            return finish()

        tool.forward = async_forward if inspect.iscoroutinefunction(forward) else sync_forward

    def wrap_forward(self, name, forward, input_names, mapping_input=False, *, process_call=None):
        if name not in self.watched:
            return forward
        fields = self.watched[name]

        def begin(args, kwargs):
            call = {"name": name, "arguments": {}, "outcome": "pending", "end": None}
            requested = self.requested.get()
            if requested is not None and requested[0] == name:
                call["requested_arguments"] = requested[1]
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
                result = process_call(call, *args, **kwargs) if process_call else forward(*args, **kwargs)
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


def record_tool_catalog(observer, config, core, items, schema_names, executable):
    recorder = getattr(observer, "replay_tool_recorder", None)
    if not isinstance(recorder, ReplayToolRecorder) or recorder.root_config is not config or not recorder.tool_patterns:
        return
    names = {item.content["name"] for item in items
             if getattr(item.type, "value", item.type) == "tool" and item.content.get("name")}
    recorder.catalog = {"core": core, "prompt_tools": sorted(names),
                        "schema_tools": sorted(set(schema_names)), "executable": sorted(set(executable)),
                        "model_inputs": 0, "instruction_mentions": [], "native_definitions": []}
    return recorder
