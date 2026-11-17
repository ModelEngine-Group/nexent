# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run-local enforcement for explicit, current-request collaborator directives."""

import re


class DelegationError(ValueError):
    """A requested authorized delegation has not been satisfied."""


_QUOTED = re.compile(r'```[\s\S]*?```|"[^"\n]*"|\'[^\'\n]*\'|“[^”]*”|「[^」]*」')
_NEGATIVE = re.compile(
    r"不要|不用|无需|不需要|不想|不希望|不允许|不准|不得|不必|不再|禁止|避免|别|不能"
    r"|\b(?:do\s+not|don['’]t|never|without)\b",
    re.I,
)
_QUESTION = re.compile(r"如何|怎么|为什么|解释|说明|\b(?:how|why|whether|explain)\b", re.I)
_CAPABILITY = re.compile(r"是否|能否|可否|能不能|可以|支持|\b(?:can\s+you|could\s+you|do\s+you)\b", re.I)
_HELP = re.compile(r"帮我|为我|\bplease\b", re.I)
_ACTION = re.compile(r"调用|使用|委派(?:给)?|交给|让|\b(?:call|invoke|use|ask|delegate)\b", re.I)
_GENERIC = re.compile(r"子智能体|子\s*agent|\b(?:sub[\s-]?agents?|workers?|a2a)\b", re.I)


class DelegationPolicy:
    """Require actual authorized dispatch, never a proposed call or old history."""

    def __init__(self, query, collaborators, *, enabled=True):
        aliases = {}
        for child in collaborators:
            name = getattr(child, "invocation_name", None) or child.name
            aliases[name] = {name.casefold(), child.name.casefold()}
            if getattr(child, "display_name", None):
                aliases[name].add(child.display_name.casefold())
        self.required = False
        selected = set()
        for clause in re.split(r"[，。！？!?;,\n]", _QUOTED.sub("", (query or "") if enabled else "")):
            action = _ACTION.search(clause)
            if action is None or _NEGATIVE.search(clause[: action.end()]) or _QUESTION.search(clause[: action.end()]):
                continue
            prefix = clause[: action.end()]
            if _CAPABILITY.search(prefix) and not _HELP.search(prefix):
                continue
            target = clause[action.end() :].casefold()
            named = {name for name, values in aliases.items() if any(value in target for value in values)}
            if named or _GENERIC.search(target):
                self.required = True
                selected.update(named)
        self.names = frozenset(selected or aliases)
        self.dispatched = False
        self.corrections = 0

    @property
    def pending(self):
        return self.required and not self.dispatched

    @property
    def instruction(self):
        if not self.required:
            return ""
        return (
            "The latest request explicitly requires delegation before direct execution. "
            "Call an authorized collaborator: " + ", ".join(sorted(self.names)) + ". "
            "Do not create the file yourself or return a final answer before that call executes. "
            "Pass the concrete task, deliverable and requested format, not an instruction to delegate again. "
            "Reuse successfully uploaded worker artifacts without recreating or uploading them again. "
            "Use the actual worker result and report failures truthfully."
        )

    def validate_targets(self, names):
        """Reject empty proposals and unauthorized execution while delegation is pending."""
        if self.pending and (not names or any(name not in self.names for name in names)):
            raise DelegationError("DELEGATION_REQUIRED")

    def allow_correction(self):
        """Allow one logical regeneration per run; transport retries are separate."""
        if self.corrections >= 1:
            return False
        self.corrections += 1
        return True

    def record_dispatch(self, name):
        """Release the gate only after the authorized entry returned successfully."""
        if name in self.names:
            self.dispatched = True
