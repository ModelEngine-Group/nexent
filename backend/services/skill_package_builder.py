"""Skill package builder.

Packages on-disk Skill directories (WorkBuddy-style: SKILL.md + scripts/ +
references/) into the ``SkillZipEntry`` payload shape that the agent import
flow expects: ``{skill_name, skill_zip_base64}``.

Used by the official-template seeder so that base64 ZIP blobs never need to be
committed to git — the skill source files live under ``resources/skill_packages/``
and are zipped at seed time.
"""

import io
import logging
import os
import zipfile
from typing import List, Optional

logger = logging.getLogger(__name__)

# Resolve the resources directory relative to this file so it works both when
# run from the repo checkout (host) and from the baked image layout. The repo
# layout is: backend/services/skill_package_builder.py ->
# backend/resources/skill_packages/. The container also mounts the repo at
# /mnt/nexent, in which case the same relative resolution still holds because
# __file__ points inside /opt/backend or /mnt/nexent/backend.
_RESOURCES_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "resources")
)
# Default skills location (kept for backwards compatibility). Solution packages
# now nest their skills under <solution_dir>/skills/ and pass that dir explicitly
# to build_skill_zip_entries().
_SKILL_PACKAGES_DIR = os.path.join(_RESOURCES_DIR, "skill_packages")


def _skill_dir(skill_name: str, skills_dir: Optional[str] = None) -> str:
    base = skills_dir or _SKILL_PACKAGES_DIR
    return os.path.join(base, skill_name)


def build_skill_zip_base64(skill_name: str, skills_dir: Optional[str] = None) -> str:
    """Zip a skill package directory and return its base64 string.

    The archive is rooted at ``<skill_name>/`` so that
    ``SkillService.create_skill_from_zip_bytes`` detects the SKILL.md inside a
    subdirectory (the layout it expects when ``SKILL.md`` is not at zip root).
    """
    import base64

    skill_dir = _skill_dir(skill_name, skills_dir)
    if not os.path.isdir(skill_dir):
        raise FileNotFoundError(
            f"Skill package directory not found for '{skill_name}': {skill_dir}"
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(skill_dir):
            for filename in files:
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, skill_dir)
                # arcname rooted at <skill_name>/ so the zip is self-describing
                arcname = os.path.join(skill_name, rel_path).replace("\\", "/")
                zf.write(file_path, arcname)

    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def build_skill_zip_entries(
    skill_names: List[str], skills_dir: Optional[str] = None
) -> List[dict]:
    """Build a list of ``{skill_name, skill_zip_base64}`` dicts for the import flow.

    ``skills_dir`` points at the directory holding the skill packages (defaults
    to the legacy ``resources/skill_packages``). Solution packages pass their
    nested ``<solution_dir>/skills`` path here.
    """
    entries = []
    for name in skill_names:
        try:
            entries.append({
                "skill_name": name,
                "skill_zip_base64": build_skill_zip_base64(name, skills_dir=skills_dir),
            })
        except FileNotFoundError as exc:
            logger.error("Skipping skill '%s' during packaging: %s", name, exc)
    return entries
