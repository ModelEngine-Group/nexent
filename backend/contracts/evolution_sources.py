# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Identify shared material across revisions of business evaluation tasks."""

import json
import unicodedata
from hashlib import sha256


def normalized_text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def task_digest(task):
    content = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return sha256(content.encode()).hexdigest()


def example_source_keys(task):
    def fingerprint(value):
        return sha256(normalized_text(value).encode("utf-8")).hexdigest()

    keys = {"file:" + file["sha256"] for file in task["attachments"]}
    if not keys:
        keys.add("query:" + fingerprint(task["query"]))
    initial = (task.get("file_state") or {}).get("initial") or {}
    if any(initial.values()):
        # Renaming a fixture does not make its business material independent.
        material = json.dumps(sorted(initial.values()), ensure_ascii=False, separators=(",", ":"))
        keys.add("file-state:" + sha256(material.encode()).hexdigest())
    if task.get("source_group"):
        keys.add("group:" + fingerprint(task["source_group"]))
    if task.get("trace_source"):
        keys.add("conversation:" + task["trace_source"]["source_group"])
    return keys
