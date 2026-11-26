# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public answer projection for reserved framework context and final envelopes."""

import re


HISTORY_TAGS = frozenset({"completed_action_history", "completed_action", "historical_attachments"})
EXECUTION_RECORD_TAGS = HISTORY_TAGS | {"code_exec_result", "summaried_result", "output_ref"}
_TAG = re.compile(r"<\s*(/?)\s*([a-z_]+)\b[^>]*>", re.IGNORECASE)
_DSML_HEADER = r"<\s*(/?)\s*[|｜]{1,2}dsml[|｜]{1,2}"
_DSML_MARKUP = re.compile(_DSML_HEADER, re.IGNORECASE)
_DSML_TAG = re.compile(_DSML_HEADER + r"\s*([a-z_]+)\b[^>]*>", re.IGNORECASE)
_DSML_PREFIXES = ("|dsml|", "||dsml||")
_FINAL = re.compile(r"<final_answer\s*>(.*?)</final_answer\s*>", re.IGNORECASE | re.DOTALL)


def contains_provider_tool_markup(text):
    """Recognize DeepSeek DSML serialized into the model's visible text."""
    return bool(_DSML_MARKUP.search(text))


def _starts_dsml_tag(text):
    if _DSML_MARKUP.match(text):
        return True
    start = re.match(r"<\s*/?\s*([|｜].*)", text, re.DOTALL)
    if not start:
        return False
    tail = start[1].replace("｜", "|").casefold()
    return any(tag.startswith(tail) or tail.startswith(tag) for tag in _DSML_PREFIXES)


class AnswerBoundaryError(ValueError):
    """Reject an ambiguous answer without exposing its source or executing actions."""


class PublicTextFilter:
    """Withhold split control prefixes and discard internal block bodies incrementally."""

    def __init__(self, *, preserve_final=False, hidden_tags=HISTORY_TAGS):
        self.pending = ""
        self.hidden = []
        self.invalid = False
        self.preserve_final = preserve_final
        self.hidden_tags = hidden_tags
        self.tag_names = hidden_tags | {"final_answer"}

    def push(self, text):
        self.pending += text
        output = []
        while self.pending:
            offset = self.pending.find("<")
            if offset < 0:
                if not self.hidden:
                    output.append(self.pending)
                self.pending = ""
                break
            if offset:
                if not self.hidden:
                    output.append(self.pending[:offset])
                self.pending = self.pending[offset:]
            provider_tag = _DSML_TAG.match(self.pending)
            match = provider_tag or _TAG.match(self.pending)
            if match:
                closing, name = match.group(1), match.group(2).lower()
                if provider_tag:
                    name = "dsml:" + name
                tag = match.group()
                self.pending = self.pending[match.end():]
                if provider_tag or name in self.hidden_tags:
                    if closing:
                        if not self.hidden or self.hidden[-1] != name:
                            self.invalid = True
                        else:
                            self.hidden.pop()
                    else:
                        self.hidden.append(name)
                elif not self.hidden and (name != "final_answer" or self.preserve_final):
                    output.append(tag)
                continue
            prefix = re.match(r"<\s*/?\s*([a-z_]*)", self.pending, re.IGNORECASE)
            if _starts_dsml_tag(self.pending) or prefix and (
                re.fullmatch(r"<\s*/?\s*", self.pending)
                or prefix.group(1) and any(name.startswith(prefix.group(1).lower()) for name in self.tag_names)
            ):
                # A bounded malformed tag is never flushed into the public stream.
                if len(self.pending) > 4096:
                    self.invalid = True
                    self.pending = ""
                    self.hidden.append("invalid")
                break
            if not self.hidden:
                output.append("<")
            self.pending = self.pending[1:]
        return "".join(output)

    def flush_visible_tail(self):
        """Release a literal trailing prefix while withholding incomplete internal records."""
        tail, self.pending = self.pending, ""
        prefix = re.match(r"<\s*/?\s*([a-z_]+)", tail, re.IGNORECASE)
        if self.hidden or self.invalid or _starts_dsml_tag(tail) or (
            prefix and any(name.startswith(prefix.group(1).lower()) for name in self.hidden_tags)
        ):
            return ""
        return tail

    def finish(self):
        if self.pending or self.hidden or self.invalid:
            raise AnswerBoundaryError("JIUWEN_FINAL_OUTPUT_INVALID")


def normalize_public_answer(text):
    """Extract one unambiguous final body, preserving ordinary Markdown and file links."""
    if not isinstance(text, str):
        raise AnswerBoundaryError("JIUWEN_FINAL_OUTPUT_INVALID")
    history = PublicTextFilter(preserve_final=True)
    clean = history.push(text)
    history.finish()
    finals = list(_FINAL.finditer(clean))
    markers = re.findall(r"<\s*/?\s*final_answer\b[^>]*>", clean, re.IGNORECASE)
    if markers:
        if len(finals) != 1 or len(markers) != 2 or _FINAL.fullmatch(clean.strip()) is None:
            raise AnswerBoundaryError("JIUWEN_FINAL_OUTPUT_INVALID")
        clean = finals[0].group(1)
    if re.search(r"<\s*/?\s*(?:code|final_answer)\b|```<run>", clean, re.IGNORECASE):
        raise AnswerBoundaryError("JIUWEN_FINAL_OUTPUT_INVALID")
    clean = clean.strip()
    if not clean:
        raise AnswerBoundaryError("JIUWEN_FINAL_OUTPUT_INVALID")
    return clean
