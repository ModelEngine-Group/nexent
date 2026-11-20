# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lossless array projection using owner-authorized historical originals."""

import ast
import hashlib
import io
import json
import re
import tokenize
from copy import deepcopy
from decimal import Decimal


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-finite JSON number")


DECODER = json.JSONDecoder(parse_float=Decimal, object_pairs_hook=_pairs, parse_constant=_constant)


def _typed(value):
    if isinstance(value, dict):
        return ["object", [[key, _typed(v)] for key, v in sorted(value.items())]]
    if isinstance(value, list):
        return ["array", [_typed(v) for v in value]]
    if isinstance(value, Decimal):
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        return ["decimal", sign, digits, exponent if digits else 0]
    return [type(value).__name__, value]


def _digest(value):
    return hashlib.sha256(json.dumps(_typed(value), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _pointer(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _space(text, position):
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _rewrite(text, value, start, end, visit, path, found):
    if isinstance(value, list) and value:
        found.append((value, path, end - start))
        replacement = visit(value, path)
        if replacement is not None and len(replacement) < end - start:
            return replacement
    if isinstance(value, str):
        projected, changed, children = _project_text(value, visit, path + "/@text")
        found.extend(children)
        return json.dumps(projected, ensure_ascii=False) if changed else text[start:end]
    if not isinstance(value, (dict, list)):
        return text[start:end]
    parts, cursor, position = [], start, _space(text, start + 1)
    children = value.items() if isinstance(value, dict) else enumerate(value)
    for key, child in children:
        if isinstance(value, dict):
            _, position = DECODER.raw_decode(text, position)
            position = _space(text, position)
            if text[position] != ":":
                raise ValueError("Invalid JSON field")
            position = _space(text, position + 1)
        _, child_end = DECODER.raw_decode(text, position)
        parts.extend(
            (text[cursor:position], _rewrite(text, child, position, child_end, visit, _pointer(path, key), found))
        )
        cursor = child_end
        position = _space(text, child_end)
        if position < end and text[position] == ",":
            position = _space(text, position + 1)
    parts.append(text[cursor:end])
    return "".join(parts)


def _project_text(text, visit, path=""):
    """Only complete parsed spans are eligible; parser failures preserve original input."""
    cursor, position, parts, found = 0, 0, [], []
    try:
        while position < len(text):
            starts = [i for char in "[{" if (i := text.find(char, position)) >= 0]
            if not starts:
                break
            position = min(starts)
            value, end = DECODER.raw_decode(text, position)
            parts.extend((text[cursor:position], _rewrite(text, value, position, end, visit, path, found)))
            cursor = position = end
        parts.append(text[cursor:])
        projected = "".join(parts)
        return projected, projected != text, found
    except (ValueError, TypeError, RecursionError, IndexError):
        return text, False, []


def _literal_strings(text, transform):
    """Decode STRING tokens in canonical executor repr; never evaluate Python objects."""
    if not re.match(r"^\s*[\[{]\s*'", text):
        return text
    starts, position = [0], 0
    for line in text.splitlines(keepends=True):
        position += len(line)
        starts.append(position)
    try:
        literals = []
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.STRING:
                value = ast.literal_eval(token.string)
                if isinstance(value, str):
                    literals.append((token, value))
    except (ValueError, SyntaxError, tokenize.TokenError, RecursionError):
        return text
    patches = []
    for token, value in literals:
        projected = transform(value)
        if projected != value:
            patches.append(
                (starts[token.start[0] - 1] + token.start[1], starts[token.end[0] - 1] + token.end[1], repr(projected))
            )
    for start, end, replacement in reversed(patches):
        text = text[:start] + replacement + text[end:]
    return text


class StructuredSourceIndex:
    """Internal proof index; model text cannot register or authorize its own source."""

    def __init__(self, history, owner):
        self.collections = {}
        for source in history.authorized_sources(owner):
            source_hash = hashlib.sha256(source.text.encode()).hexdigest()
            for part_number, part in enumerate(source.parts):
                candidates = _project_text(part, lambda *_: None)[2]
                if source.source_kind == "execution_result":

                    def collect(value):
                        candidates.extend(_project_text(value, lambda *_: None)[2])
                        return value

                    _literal_strings(part, collect)
                for value, path, span_size in candidates:
                    try:
                        digest = _digest(value)
                    except (ValueError, RecursionError):
                        continue
                    descriptor = {
                        "source_kind": source.source_kind,
                        "source_ref": source.reference,
                        "source_sha256": source_hash,
                        "sha256": digest,
                        "part": part_number,
                        "json_path": path,
                        "row_count": len(value),
                    }
                    replacement = json.dumps(
                        {"trusted_bulk_source": descriptor}, ensure_ascii=False, separators=(",", ":")
                    )
                    if len(replacement) < span_size:
                        self.collections.setdefault(digest, descriptor)

    def project_text(self, text):
        def replace(value, path):
            descriptor = self.collections.get(_digest(value))
            return (
                json.dumps({"trusted_bulk_source": descriptor}, ensure_ascii=False, separators=(",", ":"))
                if descriptor is not None
                else None
            )

        return _project_text(text, replace)[0]

    def project_turn(self, content):
        """Only the summary gets this private projection; storage/events stay original."""
        result = deepcopy(content)
        for key in ("user_message", "assistant_final_answer"):
            if isinstance(result.get(key), str):
                result[key] = self.project_text(result[key])
        for record in result.get("execution_records") or ():
            if isinstance(record, dict) and isinstance(record.get("content"), str):
                if record.get("record_type") == "execution_result":
                    from .action_history import decode_execution_fields
                    from .execution_history import result_text

                    try:
                        payload = json.loads(record["content"])
                        fields = decode_execution_fields(payload)
                        if fields is not None:
                            fields = {
                                key: _literal_strings(self.project_text(value), self.project_text)
                                for key, value in fields.items()
                            }
                            payload["content"] = result_text(fields)
                            record["content"] = json.dumps(payload, ensure_ascii=False)
                    except (ValueError, TypeError, KeyError):
                        pass
                record["content"] = self.project_text(record["content"])
        return result
