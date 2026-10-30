# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Load authorized skill snapshots with Jiuwen's native skill rail."""

from pathlib import Path

from openjiuwen.harness.rails.skills.skill_use_rail import SkillUseRail


class NexentSkillRail(SkillUseRail):
    """Keep native skill discovery/prompt lifecycle without adding host shell tools."""

    def __init__(self, directories: list[str], names: list[str], *, authorized_by_root=None):
        super().__init__(directories, enabled_skills=names, skill_mode="all", include_tools=False, enable_cache=False)
        self._roots = tuple(Path(directory).resolve() for directory in directories)
        self._names = frozenset(names)
        authorization = authorized_by_root if authorized_by_root is not None else {
            directory: names for directory in directories
        }
        self._authorized_by_root = {Path(root).resolve(): frozenset(allowed) for root, allowed in authorization.items()}

    def init(self, agent):
        # Authorized Nexent read/run handlers are already native abilities.
        # The upstream init would additionally register an unscoped skill tool.
        self.system_prompt_builder = agent.system_prompt_builder
        self.attachment_manager = agent.prompt_attachment_manager

    async def _read_skill_text(self, path: Path, *, head=None):
        path = path.resolve()
        if path.name != "SKILL.md" or path.parent.name not in self._names:
            raise PermissionError("Skill is outside the authorized snapshot")
        if not any(path.is_relative_to(root) and path.parent.name in allowed
                   for root, allowed in self._authorized_by_root.items()):
            raise PermissionError("Skill path escapes the authorized snapshot")
        text = path.read_text(encoding="utf-8-sig")
        return "\n".join(text.splitlines()[:head]) if head is not None else text

    async def _load_yaml(self, path: Path):
        text = await self._read_skill_text(path)
        return self._split_front_matter(text) or (None, text)
