"""Recursive OpenJiuwen run specification built from assembled AgentConfig."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpenJiuwenRunSpec:
    """One Agent node and its same-framework child tree."""

    agent_id: int
    name: str
    description: str
    agent_config: Any
    parent_agent_id: int | None
    depth: int
    children: tuple["OpenJiuwenRunSpec", ...]


def build_openjiuwen_run_spec(agent_config: Any) -> OpenJiuwenRunSpec:
    """Validate one same-framework acyclic tree before creating native resources."""

    def build(config: Any, parent_id: int | None, depth: int, ancestry: tuple[int, ...]):
        agent_id = getattr(config, "id", None)
        if agent_id is None:
            raise ValueError("OpenJiuwen AgentConfig requires a persisted Agent ID.")
        if agent_id in ancestry:
            raise ValueError(f"Circular internal Agent relationship detected at Agent {agent_id}.")
        framework = getattr(config, "runtime_framework", None)
        if framework != "openjiuwen":
            raise ValueError(
                f"OpenJiuwen run tree contains Agent {agent_id} with framework {framework!r}."
            )
        children = tuple(
            build(child, agent_id, depth + 1, (*ancestry, agent_id))
            for child in getattr(config, "managed_agents", [])
        )
        return OpenJiuwenRunSpec(
            agent_id=agent_id,
            name=config.name,
            description=config.description,
            agent_config=config,
            parent_agent_id=parent_id,
            depth=depth,
            children=children,
        )

    return build(agent_config, None, 0, ())


__all__ = ["OpenJiuwenRunSpec", "build_openjiuwen_run_spec"]
