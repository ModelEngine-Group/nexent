"""Load and validate official agent bundles from external profile directories."""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

from consts.model import AgentRepositorySnapshot, KnowledgeBaseSeed

logger = logging.getLogger("official_agent_bundle_service")

MAX_BUNDLE_BYTES = 100 * 1024 * 1024
MAX_BUNDLE_FILES = 1_000
MAX_BUNDLE_FILE_BYTES = 20 * 1024 * 1024


class _BundleSkillZipEntry(BaseModel):
    skill_name: str
    skill_zip_base64: str


@dataclass(frozen=True)
class OfficialAgentBundle:
    profile: str
    name: str
    snapshot: AgentRepositorySnapshot
    display_name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    icon: str | None = None
    bundle_path: Path | None = None
    knowledge_bases: list[KnowledgeBaseSeed] | None = None
    knowledge_base_documents: dict[str, list[dict[str, str]]] | None = None


def _seed_doc(file_name: str, *, content: str | None = None, file_path: str | None = None) -> dict[str, str]:
    result = {"file_name": file_name}
    if content is not None:
        result["content"] = content
    if file_path is not None:
        result["file_path"] = file_path
    return result


def parse_official_agent_profiles(value: str | Iterable[str] | None) -> list[str]:
    """Normalize a comma-separated profile setting without accepting paths."""
    values = value.split(",") if isinstance(value, str) else (value or [])
    profiles: list[str] = []
    for raw in values:
        profile = str(raw).strip()
        if not profile or profile in {".", ".."} or "/" in profile or "\\" in profile:
            raise ValueError(f"invalid official agent profile: {profile!r}")
        if profile not in profiles:
            profiles.append(profile)
    return profiles


def _safe_member_path(root: Path, member_name: str) -> Path | None:
    if not member_name or "\x00" in member_name:
        return None
    candidate = (root / member_name.replace("\\", "/")).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _read_bundle_json(extract_dir: Path) -> dict[str, Any]:
    path = extract_dir / "agent.json"
    if not path.is_file():
        raise ValueError("official agent bundle is missing agent.json")
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("agent.json must contain an object")
    return data


def _snapshot_from_json(data: dict[str, Any]) -> AgentRepositorySnapshot:
    payload = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else data
    AgentRepositorySnapshot.model_rebuild(
        force=True,
        _types_namespace={"SkillZipEntry": _BundleSkillZipEntry},
    )
    return AgentRepositorySnapshot.model_validate(payload)


def _load_skill_entries(extract_dir: Path, snapshot: AgentRepositorySnapshot) -> list[_BundleSkillZipEntry]:
    declared = {
        skill_name
        for agent in snapshot.agent_info.values()
        for skill_name in (agent.skill_names or [])
        if skill_name
    }
    entries: list[_BundleSkillZipEntry] = []
    for skill_name in sorted(declared):
        if Path(skill_name).name != skill_name:
            raise ValueError(f"unsafe official skill name: {skill_name}")
        path = extract_dir / "skills" / f"{skill_name}.zip"
        if path.is_file():
            entries.append(_BundleSkillZipEntry(skill_name=skill_name, skill_zip_base64=__import__("base64").b64encode(path.read_bytes()).decode("ascii")))
    return entries


def _load_kb_documents(extract_dir: Path, data: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    raw_knowledge_bases = data.get("knowledge_bases", []) or []
    if isinstance(raw_knowledge_bases, dict):
        raw_knowledge_bases = [raw_knowledge_bases]
    for raw_kb in raw_knowledge_bases:
        if not isinstance(raw_kb, dict):
            continue
        logical_name = raw_kb.get("logical_index_name")
        if not isinstance(logical_name, str) or Path(logical_name).name != logical_name:
            raise ValueError("unsafe official knowledge base name")
        docs: list[dict[str, str]] = []
        kb_dir = extract_dir / "kb" / logical_name
        if kb_dir.is_dir():
            for path in sorted(kb_dir.iterdir()):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if path.suffix.lower() in {".md", ".txt", ".markdown"}:
                    docs.append(_seed_doc(path.name, content=path.read_text(encoding="utf-8")))
                else:
                    docs.append(_seed_doc(path.name, file_path=str(path)))
        if docs:
            result[logical_name] = docs
    return result


def _load_kb_metadata(data: dict[str, Any]) -> list[KnowledgeBaseSeed]:
    """Load bundle KB declarations, preserving their user-facing names."""
    raw_knowledge_bases = data.get("knowledge_bases", []) or []
    if isinstance(raw_knowledge_bases, dict):
        raw_knowledge_bases = [raw_knowledge_bases]
    if not isinstance(raw_knowledge_bases, list):
        raise ValueError("official knowledge_bases must be an object or list")
    return [KnowledgeBaseSeed.model_validate(item) for item in raw_knowledge_bases]


def _load_zip_bundle(profile: str, path: Path) -> OfficialAgentBundle | None:
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError("official agent bundle exceeds size limit")
    with tempfile.TemporaryDirectory(prefix="nexent-official-agent-") as temp_dir:
        extract_dir = Path(temp_dir)
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_BUNDLE_FILES:
                raise ValueError("official agent bundle contains too many files")
            for member in members:
                target = _safe_member_path(extract_dir, member.filename)
                if target is None:
                    raise ValueError("official agent bundle contains unsafe path")
                if member.file_size > MAX_BUNDLE_FILE_BYTES:
                    raise ValueError("official agent bundle contains oversized file")
            archive.extractall(extract_dir)
        data = _read_bundle_json(extract_dir)
        snapshot = _snapshot_from_json(data)
        knowledge_bases = _load_kb_metadata(data)
        skills = _load_skill_entries(extract_dir, snapshot)
        if skills:
            snapshot = snapshot.model_copy(update={"skills": skills})
        kb_docs = _load_kb_documents(extract_dir, data)
        return OfficialAgentBundle(
            profile=profile,
            name=path.stem,
            snapshot=snapshot,
            display_name=data.get("display_name"),
            description=data.get("description"),
            tags=data.get("tags"),
            icon=data.get("icon"),
            bundle_path=path,
            knowledge_bases=knowledge_bases,
            knowledge_base_documents=kb_docs,
        )


def load_official_bundles(base_dir: str | Path, profiles: Iterable[str]) -> list[OfficialAgentBundle]:
    """Load selected profiles, isolating invalid bundles and rejecting key collisions."""
    root = Path(base_dir).resolve()
    bundles: list[OfficialAgentBundle] = []
    seen_names: set[str] = set()
    selected_profiles = parse_official_agent_profiles(profiles)
    selected_profile_set = set(selected_profiles)
    available_profiles = {
        path.name
        for path in root.iterdir()
        if path.is_dir()
    } if root.is_dir() else set()
    for profile in selected_profiles:
        if profile not in available_profiles:
            logger.warning("Official agent profile directory not found: %s", profile)

    # Recursively scan only the configured root. User-selected profile names
    # are used for filtering scan results, never for path construction or
    # recursive traversal.
    bundle_paths = [
        path
        for path in root.rglob("*.zip")
        if path.parent.name != "skills"
        and path.relative_to(root).parts[0] in selected_profile_set
    ] if root.is_dir() else []
    bundle_dirs = [
        path.parent
        for path in root.rglob("agent.json")
        if path.is_file()
        and path.relative_to(root).parts[0] in selected_profile_set
    ] if root.is_dir() else []

    # Skill payloads are ZIP files too, but they are dependencies inside a
    # directory Bundle rather than standalone Agent Bundles. Do not attempt
    # to parse them as archives that must contain agent.json.
    for path in sorted(bundle_paths):
        profile = path.relative_to(root).parts[0]
        try:
            bundle = _load_zip_bundle(profile, path)
            if bundle is None:
                continue
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            logger.warning("Skipping official agent bundle %s: %s", path, exc)
            continue
        if bundle.name in seen_names:
            raise ValueError(f"duplicate official agent bundle: {bundle.name}")
        seen_names.add(bundle.name)
        bundles.append(bundle)
    for bundle_dir in sorted(bundle_dirs):
        profile = bundle_dir.parent.relative_to(root).parts[0]
        try:
            data = _read_bundle_json(bundle_dir)
            snapshot = _snapshot_from_json(data)
            knowledge_bases = _load_kb_metadata(data)
            skills = _load_skill_entries(bundle_dir, snapshot)
            if skills:
                snapshot = snapshot.model_copy(update={"skills": skills})
            kb_docs = _load_kb_documents(bundle_dir, data)
            bundle = OfficialAgentBundle(
                profile=profile,
                name=bundle_dir.name,
                snapshot=snapshot,
                display_name=data.get("display_name"),
                description=data.get("description"),
                tags=data.get("tags"),
                icon=data.get("icon"),
                bundle_path=bundle_dir,
                knowledge_bases=knowledge_bases,
                knowledge_base_documents=kb_docs,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Skipping official agent bundle %s: %s", bundle_dir, exc)
            continue
        if bundle.name in seen_names:
            raise ValueError(f"duplicate official agent bundle: {bundle.name}")
        seen_names.add(bundle.name)
        bundles.append(bundle)
    return sorted(bundles, key=lambda item: (item.profile, item.name))
