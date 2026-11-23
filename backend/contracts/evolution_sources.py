# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Identify shared material across revisions of business evaluation tasks."""

import unicodedata
from hashlib import sha256


def normalized_text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def example_source_keys(task):
    def fingerprint(value):
        return sha256(normalized_text(value).encode("utf-8")).hexdigest()

    keys = {"file:" + file["sha256"] for file in task["attachments"]}
    if not keys:
        keys.add("query:" + fingerprint(task["query"]))
    if task.get("source_group"):
        keys.add("group:" + fingerprint(task["source_group"]))
    if task.get("trace_source"):
        keys.add("conversation:" + task["trace_source"]["source_group"])
    return keys
