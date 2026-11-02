# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared Agent identifiers and deterministic runtime callable allocation."""

import builtins
import hashlib
import keyword
import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any


AGENT_NAME_MAX_LENGTH = 100
_FRAMEWORK_NAMES = frozenset(dir(builtins)) | {
    "final_answer", "parallel_executor", "metadata", "self", "state",
    "create_plan", "update_plan_step", "__name__", "_print_outputs", "_operations_count",
}
_PROTECTED_BINDINGS = {"__builtins__", "__name__", "__package__", "__loader__", "__spec__"}


def validate_agent_name(name: str) -> str:
    """Preserve existing Python identifiers while excluding keywords and overlength names."""
    if (not isinstance(name, str) or not 1 <= len(name) <= AGENT_NAME_MAX_LENGTH
            or not name.isidentifier() or keyword.iskeyword(name)):
        raise ValueError(
            "Agent name must be a valid Python identifier, not a Python keyword, "
            f"and contain 1-{AGENT_NAME_MAX_LENGTH} characters"
        )
    return name


def _canonical(name: str) -> str:
    return unicodedata.normalize("NFKC", name)


def _is_callable(name: str) -> bool:
    return (
        isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name)
        and not name.casefold().startswith("_nexent") and name not in _PROTECTED_BINDINGS
    )


def validate_callable_names(names: Iterable[str]) -> None:
    """Reject malformed or ambiguous registry keys before interpolating Python source."""
    seen: set[str] = set()
    for name in names:
        if not _is_callable(name):
            raise ValueError(f"Invalid Agent/tool callable name: {name!r}")
        canonical = _canonical(name)
        if canonical in seen:
            raise ValueError(f"Duplicate Agent/tool callable name: {name!r}")
        seen.add(canonical)


def allocate_external_agent_names(
    agents: Iterable[tuple[str, str]], reserved_names: Iterable[str] = (),
) -> dict[str, str]:
    """Keep unique legal legacy calls and allocate stable ID-based collision-free aliases."""
    records = sorted((str(agent_id), name) for agent_id, name in agents)
    if not records:
        return {}
    if len({agent_id for agent_id, _ in records}) != len(records):
        raise ValueError("Duplicate external Agent ID in callable registry")
    used = {_canonical(name) for name in (*_FRAMEWORK_NAMES, *reserved_names)}
    aliases: dict[str, str] = {}
    # Reserve every compatible legacy name before allocating any fallback.
    for agent_id, name in records:
        if _is_callable(name) and name == _canonical(name) and name not in used:
            aliases[agent_id] = name
            used.add(name)
    for agent_id, _ in records:
        if agent_id in aliases:
            continue
        suffix = agent_id if re.fullmatch(r"[0-9]{1,80}", agent_id) else hashlib.sha256(
            agent_id.encode("utf-8")
        ).hexdigest()
        base = f"a2a_agent_{suffix}"
        alias = base
        counter = 2
        while alias in used:
            alias = f"{base}_{counter}"
            counter += 1
        aliases[agent_id] = alias
        used.add(alias)
    return aliases


def resolve_external_agent_configs(agents: Sequence[Any], reserved_names: Iterable[str] = ()) -> list[Any]:
    """Return copies so resolving runtime names never rewrites original Card/display names."""
    aliases = allocate_external_agent_names(
        ((agent.agent_id, agent.invocation_name or agent.name) for agent in agents), reserved_names,
    )
    return [agent.model_copy(update={"invocation_name": aliases[str(agent.agent_id)]}) for agent in agents]
