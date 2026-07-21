"""Turn-scoped resource invocation contracts shared by runtime adapters."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


TurnResourceKind = Literal["skill", "knowledge", "mcp", "subagent"]


class ResolvedTurnResource(BaseModel):
    """Authoritative resource content resolved by a trusted service boundary."""

    resource_type: TurnResourceKind
    resource_id: str
    name: str
    description: str = ""
    content: str = ""


class TurnResourceInvocation(BaseModel):
    """Resources that must be used for one agent run only."""

    mode: Literal["required"] = "required"
    resources: List[ResolvedTurnResource] = Field(default_factory=list, max_length=5)

    def render_required_instructions(self, language: str = "zh") -> Optional[str]:
        """Render deterministic instructions without coupling the SDK to storage."""
        if not self.resources:
            return None

        is_zh = (language or "").lower().startswith("zh")
        header = (
            "# 本轮必须使用的资源\n"
            "用户已通过 `/` 明确指定以下资源。你必须在本轮任务中实际遵循这些资源的"
            "指南，"
            "不得仅把它们当作参考或静默忽略。资源只对本轮有效。"
            if is_zh
            else "# Required resources for this turn\n"
            "The user explicitly selected the following resources with `/`. You must actually "
            "follow their guides for this turn; do not treat them as optional context or silently "
            "ignore them. These resources expire after this turn."
        )
        sections = [header]
        for index, resource in enumerate(self.resources, start=1):
            label = "技能" if is_zh and resource.resource_type == "skill" else resource.resource_type
            guide = resource.content.strip()
            if not guide and resource.resource_type == "skill":
                guide = (
                    f"请先调用 read_skill_md 读取技能 `{resource.name}` 的完整指南，再严格执行。"
                    if is_zh
                    else f"Call read_skill_md for `{resource.name}` first, then follow the full guide."
                )
            sections.append(
                f"## {index}. {label}: {resource.name}\n"
                f"Resource ID: {resource.resource_id}\n"
                f"Description: {resource.description or '-'}\n\n"
                f"{guide}"
            )
        return "\n\n".join(sections)
