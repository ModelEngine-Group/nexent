# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Request-local configuration path validation and batched regular-file checks."""

import os

from contracts.constants.environment import CONTAINER_SKILLS_PATH
from contracts.errors.exceptions import ForbiddenError, SkillException
from nexent.skills.paths import (
    InvalidSkillNameError,
    SkillPathResolver,
    UnsafeSkillPathError,
    UnsafeSkillRootError,
    validate_path_component,
)


def _regular_files(paths: list[str]) -> dict[str, bool]:
    """Scan each shared parent once, retaining stat behavior on enumeration errors."""
    parents: dict[str, list[str]] = {}
    for path in paths:
        parents.setdefault(os.path.dirname(path), []).append(path)
    result = dict.fromkeys(paths, False)
    for parent, targets in parents.items():
        wanted = {os.path.normcase(os.path.basename(path)): path for path in targets}
        try:
            with os.scandir(parent) as entries:
                for entry in entries:
                    path = wanted.get(os.path.normcase(entry.name))
                    if path is not None:
                        # Preserve stat/access semantics even when directory entry
                        # type metadata is cached or the parent is not searchable.
                        result[path] = os.path.isfile(path)
        except (FileNotFoundError, NotADirectoryError):
            pass
        except OSError:
            # Execute-only directories may allow stat/open without enumeration.
            result.update((path, os.path.isfile(path)) for path in targets)
    return result


class SkillConfigPaths:
    """Own one list operation's roots; do not retain paths or existence results."""

    def __init__(self, local_dir: str | None):
        self.local_dir = local_dir
        self._resolver: SkillPathResolver | None = None

    def files_for(self, skill_name: str) -> list[tuple[str, bool]]:
        """Resolve both current YAML paths with the established exception policy."""
        try:
            name = str(skill_name or "").strip()
            if self._resolver is None:
                validate_path_component(name)
                self._resolver = SkillPathResolver(self.local_dir, allowed_root=CONTAINER_SKILLS_PATH)
            paths = self._resolver.resolve_many(name, [("config", "config.yaml"), ("config", "schema.yaml")])
        except (InvalidSkillNameError, UnsafeSkillRootError) as exc:
            raise SkillException(str(exc)) from exc
        except UnsafeSkillPathError as exc:
            raise ForbiddenError(str(exc)) from exc
        existing = _regular_files(paths)
        return [(path, existing[path]) for path in paths]
