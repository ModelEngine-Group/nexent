"""Official agent bundle discovery, installation-status listing and install.

Official agents mirror the official-skills mechanism: platform bundles live in
``OFFICIAL_AGENTS_PATH`` as one JSON file per agent (``<name>.json``), each
carrying a full :class:`AgentRepositorySnapshot` plus official card fields and
optional knowledge base seed documents.

The install pipeline installs MCP servers, creates per-tenant knowledge bases
from seed documents, remaps the agent's KB tool references to the tenant's
generated index names, and imports the agent with its skills.
"""

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from consts.const import (
    OFFICIAL_AGENTS_PATH,
    OFFICIAL_AGENTS_REPO_REF,
    OFFICIAL_AGENTS_REPO_URL,
    SNAPSHOT_MAX_BYTES,
)
from consts.exceptions import RepoSourceError
from consts.model import (
    KnowledgeBaseSeedDoc,
    ModelConnectStatusEnum,
    OfficialAgentAgentInfo,
    OfficialAgentBundle,
    OfficialAgentGithubCategory,
    OfficialAgentGithubDiscoverResult,
    OfficialAgentGithubGroup,
    OfficialAgentGithubInstallResult,
    OfficialAgentInstallItem,
    OfficialAgentInstallStep,
    OfficialAgentKbPreview,
    OfficialAgentListItem,
    OfficialAgentMcpPreview,
    OfficialAgentSkillPreview,
    SkillZipEntry,
)

logger = logging.getLogger("official_agent_service")

# Tool classes that reference a knowledge base by params.index_names.
_KB_TOOL_CLASS_NAMES = frozenset({"KnowledgeBaseSearchTool", "DataMateSearchTool"})

# KB seed file suffixes treated as plain text (embedded via index_documents).
_TEXT_DOC_SUFFIXES = frozenset({".md", ".txt", ".markdown"})

# GitCode 固定源：目录发现与快照
_GITCODE_HOSTS = frozenset({"gitcode.com", "gitcode.net"})
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SNAPSHOT_ROOT = os.path.join(tempfile.gettempdir(), "official-agents-repo")
# 已知第一层分组；新增分组名默认归入 "其他"（容忍未来新增第一层目录）。
_KNOWN_GROUPS = frozenset({"行业智能体", "通用智能体"})


def _safe_path_under(root: str, *parts: str) -> Optional[str]:
    """Resolve a path and reject traversal or symlink escapes from ``root``."""
    if any(
        not isinstance(part, str)
        or not part
        or part in {".", ".."}
        or "/" in part
        or "\\" in part
        for part in parts
    ):
        return None
    root_path = Path(root).resolve()
    candidate = (root_path.joinpath(*parts)).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        return None
    return str(candidate)


def _safe_relative_path_under(root: str, relative_path: str) -> Optional[str]:
    """Resolve a validated slash-separated repository path under ``root``."""
    if not isinstance(relative_path, str) or not relative_path:
        return None
    parts = relative_path.replace("\\", "/").split("/")
    if any(not part for part in parts):
        return None
    return _safe_path_under(root, *parts)


def _list_bundle_files(base_dir: Optional[str] = None) -> List[str]:
    """Return sorted official bundle keys found under ``base_dir``.

    ``base_dir`` defaults to ``OFFICIAL_AGENTS_PATH``. A bundle is either a
    directory (``<name>/agent.json``) or a single JSON file (``<name>.json``) —
    mirroring the dual import-agent formats. Keys are top-level entries.
    """
    root = base_dir if base_dir is not None else OFFICIAL_AGENTS_PATH
    if not os.path.isdir(root):
        logger.warning(
            "Official agents bundle directory not found: %s",
            root,
        )
        return []
    try:
        names = set()
        for entry in os.listdir(root):
            entry_path = _safe_path_under(root, entry)
            agent_json_path = (
                _safe_path_under(entry_path, "agent.json")
                if entry_path is not None
                else None
            )
            if (
                entry_path is not None
                and os.path.isdir(entry_path)
                and agent_json_path is not None
                and os.path.isfile(agent_json_path)
            ):
                names.add(entry)
            elif entry.lower().endswith(".json") and entry[:-5]:
                names.add(entry[:-5])
        return sorted(names)
    except OSError as e:
        logger.warning("Failed to list official agents bundle directory: %s", e)
        return []


def _attach_skills_from_dir(bundle: OfficialAgentBundle, dir_path: str) -> None:
    """Attach skill ZIP payloads from ``<dir>/skills/*.zip``.

    The authoritative skill list comes from each agent's ``skill_names``; files
    are read by name and base64-encoded, matching the import-agent behaviour.
    """
    skills_dir = _safe_path_under(dir_path, "skills")
    if skills_dir is None:
        return
    skill_names = sorted(
        {
            skill_name
            for agent in bundle.agent_info.values()
            for skill_name in (getattr(agent, "skill_names", None) or [])
            if skill_name
        }
    )
    attached: List[SkillZipEntry] = []
    for skill_name in skill_names:
        zip_path = _safe_path_under(skills_dir, f"{skill_name}.zip")
        md_path = _safe_path_under(skills_dir, f"{skill_name}.md")
        if zip_path is None or md_path is None:
            logger.warning(
                "Official agent '%s' references an unsafe skill name '%s'",
                bundle.name,
                skill_name,
            )
            continue
        if os.path.isfile(zip_path):
            with open(zip_path, "rb") as f:
                zip_bytes = f.read()
        else:
            if not os.path.isfile(md_path):
                logger.warning(
                    "Official agent '%s' references skill '%s' but %s is missing",
                    bundle.name,
                    skill_name,
                    zip_path,
                )
                continue
            # Markdown skill: wrap the file as SKILL.md inside a minimal zip so
            # it flows through the standard skill import pipeline. An invalid
            # SKILL.md surfaces as a per-bundle install failure at install time.
            zip_bytes = _wrap_markdown_skill(md_path)
        attached.append(
            SkillZipEntry(
                skill_name=skill_name,
                skill_zip_base64=base64.b64encode(zip_bytes).decode("ascii"),
            )
        )
    if attached:
        bundle.skills = attached


def _wrap_markdown_skill(md_path: str) -> bytes:
    """Return a minimal skill zip containing the given markdown as SKILL.md."""
    from io import BytesIO
    import zipfile

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(md_path, "SKILL.md")
    return buffer.getvalue()


def _attach_kb_docs_from_dir(bundle: OfficialAgentBundle, dir_path: str) -> None:
    """Attach knowledge base seed documents from ``<dir>/kb/<logical_index_name>/*``.

    Text files (.md/.txt) are read into ``content``; other files (docx/pdf/...)
    are kept as ``file_path`` pointing at the real file so the install pipeline
    can upload and process them like a normal knowledge base document.
    """
    kb_dir = _safe_path_under(dir_path, "kb")
    if kb_dir is None:
        return
    if not os.path.isdir(kb_dir):
        return
    for kb in bundle.knowledge_bases or []:
        logical_dir = _safe_path_under(kb_dir, kb.logical_index_name)
        if logical_dir is None:
            logger.warning(
                "Official agent '%s' references an unsafe knowledge-base name '%s'",
                bundle.name,
                kb.logical_index_name,
            )
            continue
        if not os.path.isdir(logical_dir):
            continue
        docs: List[KnowledgeBaseSeedDoc] = []
        try:
            for file_name in sorted(os.listdir(logical_dir)):
                file_path = _safe_path_under(logical_dir, file_name)
                if file_path is None:
                    logger.warning(
                        "Skipping unsafe KB file '%s' for official agent '%s'",
                        file_name,
                        bundle.name,
                    )
                    continue
                if not os.path.isfile(file_path):
                    continue
                suffix = os.path.splitext(file_name)[1].lower()
                if suffix in _TEXT_DOC_SUFFIXES:
                    with open(file_path, encoding="utf-8") as f:
                        docs.append(
                            KnowledgeBaseSeedDoc(
                                file_name=file_name,
                                content=f.read(),
                            )
                        )
                else:
                    # binary seed: keep the real file for the install pipeline
                    docs.append(
                        KnowledgeBaseSeedDoc(
                            file_name=file_name,
                            file_path=file_path,
                        )
                    )
        except OSError as e:
            logger.warning(
                "Failed to read KB docs for '%s/%s': %s",
                bundle.name,
                kb.logical_index_name,
                e,
            )
            continue
        if docs:
            kb.documents = docs


def _load_bundle(
    name: str, base_dir: Optional[str] = None
) -> Optional[OfficialAgentBundle]:
    """Load a bundle by key, supporting both directory and single-file layouts.

    ``base_dir`` defaults to ``OFFICIAL_AGENTS_PATH``; ``name`` may be a
    relative path (e.g. ``行业智能体/医疗/体检报告解读助手``) when loading from a
    remote repository snapshot.

    Directory layout: ``<name>/agent.json`` + ``skills/`` + ``kb/`` (skills and
    KB documents are attached from files). Single-file layout: ``<name>.json``
    with skills/documents inline. The key is treated as the authoritative name.
    """
    root = base_dir if base_dir is not None else OFFICIAL_AGENTS_PATH
    dir_path = _safe_relative_path_under(root, name)
    agent_json_path = (
        _safe_path_under(dir_path, "agent.json") if dir_path is not None else None
    )
    if (
        dir_path is not None
        and os.path.isdir(dir_path)
        and agent_json_path is not None
        and os.path.isfile(agent_json_path)
    ):
        try:
            with open(agent_json_path, encoding="utf-8") as f:
                data = json.load(f)
            bundle = OfficialAgentBundle.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Skip invalid official agent bundle '%s': %s", name, e)
            return None
        bundle.name = name
        _attach_skills_from_dir(bundle, dir_path)
        _attach_kb_docs_from_dir(bundle, dir_path)
        return bundle

    single_path = _safe_relative_path_under(root, f"{name}.json")
    if single_path is not None and os.path.isfile(single_path):
        try:
            with open(single_path, encoding="utf-8") as f:
                data = json.load(f)
            bundle = OfficialAgentBundle.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Skip invalid official agent bundle '%s': %s", name, e)
            return None
        bundle.name = name
        return bundle

    return None


def _is_agent_installed(bundle: OfficialAgentBundle, tenant_id: str) -> bool:
    """Return whether the bundle's root agent already exists in the tenant.

    ``search_agent_id_by_agent_name`` raises ValueError when the agent is
    absent, so absence is detected via the exception rather than a None return.
    """
    root_agent = bundle.agent_info.get(str(bundle.agent_id))
    if root_agent is None:
        return False
    name = getattr(root_agent, "name", None)
    if not name:
        return False

    from database.agent_db import search_agent_id_by_agent_name

    try:
        search_agent_id_by_agent_name(name, tenant_id)
        return True
    except ValueError:
        return False


async def _first_available_embedding_model_id(tenant_id: str) -> Optional[int]:
    """Return the model_id of the first usable embedding model for a tenant.

    Matches the availability criteria used by knowledge base creation
    (model_type in embedding/multi_embedding and connect_status available).
    Returns None when the tenant has no usable embedding model.
    """
    from services.model_management_service import list_models_for_tenant

    models = await list_models_for_tenant(tenant_id)
    for model in models:
        if (
            model.get("model_type") in ("embedding", "multi_embedding")
            and model.get("connect_status") == ModelConnectStatusEnum.AVAILABLE.value
        ):
            return model.get("model_id")
    return None


async def _has_available_embedding_model(tenant_id: str) -> bool:
    """Return whether the tenant has a usable embedding model."""
    return await _first_available_embedding_model_id(tenant_id) is not None


async def _missing_model_types(
    bundle: OfficialAgentBundle,
    tenant_id: str,
) -> List[str]:
    """Return the model types the tenant must configure before installing.

    Checks ``llm`` (any usable chat model — the agent cannot run without one),
    ``embedding`` (when the bundle carries knowledge bases) and ``rerank``
    (when a KB search tool enables rerank). Returns a stable list of model type
    strings; empty when the tenant has everything the bundle needs.
    """
    from services.model_management_service import list_models_for_tenant

    models = await list_models_for_tenant(tenant_id)
    available = {
        m.get("model_type")
        for m in models
        if m.get("connect_status") == ModelConnectStatusEnum.AVAILABLE.value
    }

    missing: List[str] = []

    if not available.intersection(("llm", "vlm")):
        missing.append("llm")

    if bundle.knowledge_bases and not available.intersection(
        ("embedding", "multi_embedding")
    ):
        missing.append("embedding")

    if (
        bundle.knowledge_bases
        and _kb_needs_rerank(bundle)
        and "rerank" not in available
    ):
        missing.append("rerank")

    return missing


def _kb_needs_rerank(bundle: OfficialAgentBundle) -> bool:
    """Return whether any KB search tool in the bundle enables rerank."""
    for agent in bundle.agent_info.values():
        for tool in agent.tools or []:
            if tool.class_name not in _KB_TOOL_CLASS_NAMES:
                continue
            if (tool.params or {}).get("rerank") is True:
                return True
    return False


def _agent_infos(bundle: OfficialAgentBundle) -> List[OfficialAgentAgentInfo]:
    """Return the bundle's agent name/display_name list (root + sub-agents)."""
    infos: List[OfficialAgentAgentInfo] = []
    for agent in bundle.agent_info.values():
        infos.append(
            OfficialAgentAgentInfo(
                name=agent.name,
                display_name=getattr(agent, "display_name", None),
            )
        )
    return infos


def _mcp_previews(
    bundle: OfficialAgentBundle,
    tenant_id: str,
) -> List[OfficialAgentMcpPreview]:
    """Return the bundle's MCP declarations with per-tenant install state.

    ``installed`` mirrors the install dedup rule: an MCP is considered installed
    only when a server with the same name AND url already exists. ``conflict`` is
    True when the name is taken by a different url (the user must rename or skip
    it during install).
    """
    from database.remote_mcp_db import get_mcp_server_by_name_and_tenant

    previews: List[OfficialAgentMcpPreview] = []
    for mcp in bundle.mcp_info or []:
        existing_url = get_mcp_server_by_name_and_tenant(
            mcp.mcp_server_name, tenant_id
        )
        previews.append(
            OfficialAgentMcpPreview(
                mcp_server_name=mcp.mcp_server_name,
                mcp_url=mcp.mcp_url,
                installed=existing_url == mcp.mcp_url,
                conflict=bool(existing_url) and existing_url != mcp.mcp_url,
            )
        )
    return previews


def _skill_previews(
    bundle: OfficialAgentBundle,
    tenant_id: str,
) -> List[OfficialAgentSkillPreview]:
    """Return the bundle's skills with per-tenant name-conflict state.

    ``exists`` is True when a skill with the same name already exists in the
    tenant, which drives the reuse-vs-rename choice during install.
    """
    from database import skill_db

    existing_names = {
        s.get("name") for s in skill_db.list_skills(tenant_id) if s.get("name")
    }
    previews: List[OfficialAgentSkillPreview] = []
    for entry in bundle.skills or []:
        previews.append(
            OfficialAgentSkillPreview(
                name=entry.skill_name,
                exists=entry.skill_name in existing_names,
            )
        )
    return previews


def _kb_previews(
    bundle: OfficialAgentBundle,
    tenant_id: str,
) -> List[OfficialAgentKbPreview]:
    """Return the bundle's knowledge bases with per-tenant name-conflict state.

    ``exists`` is True when a knowledge base with the same display name already
    exists in the tenant (the reuse key used by the install pipeline).
    """
    from database.knowledge_db import get_knowledge_record

    previews: List[OfficialAgentKbPreview] = []
    for kb in bundle.knowledge_bases or []:
        kb_name = kb.display_name or kb.logical_index_name
        existing = get_knowledge_record(
            {"knowledge_name": kb_name, "tenant_id": tenant_id}
        )
        previews.append(
            OfficialAgentKbPreview(
                logical_index_name=kb.logical_index_name,
                display_name=kb.display_name,
                # get_knowledge_record returns {} (falsy) when nothing matches,
                # so use truthiness, not `is not None`, to detect a real conflict.
                exists=bool(existing),
            )
        )
    return previews


async def _status_item_for_bundle(
    bundle: OfficialAgentBundle, tenant_id: str
) -> OfficialAgentListItem:
    """Build the catalog item for one loaded bundle.

    Status priority: installed > needs_model > installable. Shared by the local
    (OFFICIAL_AGENTS_PATH) and GitCode sources.
    """
    has_knowledge = bool(bundle.knowledge_bases)
    missing_models = await _missing_model_types(bundle, tenant_id)

    if _is_agent_installed(bundle, tenant_id):
        status = "installed"
    elif missing_models:
        status = "needs_model"
    else:
        status = "installable"

    return OfficialAgentListItem(
        name=bundle.name,
        display_name=bundle.display_name,
        description=bundle.description,
        icon=bundle.icon,
        tags=bundle.tags,
        version_label=bundle.version_label,
        status=status,
        has_knowledge=has_knowledge,
        mcp_count=len(bundle.mcp_info or []),
        skill_count=len(bundle.skills or []),
        kb_count=len(bundle.knowledge_bases or []),
        missing_models=missing_models,
        agents=_agent_infos(bundle),
        mcps=_mcp_previews(bundle, tenant_id),
        skills=_skill_previews(bundle, tenant_id),
        knowledge_bases=_kb_previews(bundle, tenant_id),
    )


async def _list_bundles_with_status(
    base_dir: Optional[str], tenant_id: str
) -> List[OfficialAgentListItem]:
    """List bundles under ``base_dir`` with per-tenant installation status.

    Shared by the local path (OFFICIAL_AGENTS_PATH) and the GitCode snapshot
    directory, so a remote catalog and the local catalog behave identically.
    """
    items: List[OfficialAgentListItem] = []
    for name in _list_bundle_files(base_dir):
        bundle = _load_bundle(name, base_dir)
        if bundle is None:
            continue
        items.append(await _status_item_for_bundle(bundle, tenant_id))
    return items


async def list_official_agents_with_status(
    tenant_id: str,
) -> List[OfficialAgentListItem]:
    """List all official agents with their installation status for a tenant.

    Status priority: installed > needs_model > installable.
    """
    return await _list_bundles_with_status(OFFICIAL_AGENTS_PATH, tenant_id)


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


async def _install_mcp_servers(
    bundle: OfficialAgentBundle,
    tenant_id: str,
    user_id: str,
    mcp_renames: Optional[Dict[str, str]] = None,
    mcp_skips: Optional[List[str]] = None,
) -> None:
    """Install the bundle's MCP servers that are missing in the tenant.

    An MCP is skipped only when a server with the same name AND url already
    exists (matching the agent-config import behaviour). A server whose name is
    taken by a different URL is a conflict; unlike the previous hard abort, the
    user resolves it up front: ``mcp_renames`` maps the original name to a new
    name to install under, and ``mcp_skips`` lists original names to skip
    entirely (its tools would be missing).

    Official MCP endpoints are trusted platform-provided URLs, so health checks
    are skipped.
    """
    from database.remote_mcp_db import get_mcp_server_by_name_and_tenant
    from services.remote_mcp_service import add_mcp_service

    renames = mcp_renames or {}
    skips = set(mcp_skips or [])

    for mcp in bundle.mcp_info or []:
        if mcp.mcp_server_name in skips:
            logger.warning(
                "Skipping MCP server '%s' for tenant %s (user requested skip)",
                mcp.mcp_server_name,
                tenant_id,
            )
            continue
        effective_name = renames.get(mcp.mcp_server_name, mcp.mcp_server_name)
        existing_url = get_mcp_server_by_name_and_tenant(
            effective_name, tenant_id
        )
        if existing_url == mcp.mcp_url:
            logger.info(
                "MCP server '%s' already exists for tenant %s with the same "
                "URL, skipping",
                effective_name,
                tenant_id,
            )
            continue
        # effective_name resolves a previous name-conflict (user renamed): it no
        # longer collides, so create it fresh. Without a rename the conflict was
        # meant to be surfaced in the resources step, so do not silently proceed.
        if existing_url and effective_name == mcp.mcp_server_name:
            raise ValueError(
                f"MCP server name '{effective_name}' already exists for "
                f"tenant {tenant_id} but with a different URL "
                f"('{existing_url}' != '{mcp.mcp_url}'). Rename or skip it to "
                f"continue."
            )
        await add_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=effective_name,
            description=None,
            source="local",
            server_url=mcp.mcp_url,
            tags=[],
            authorization_token=None,
            container_config=None,
            registry_json=None,
            skip_health_check=True,
            enabled=True,
        )
        logger.info(
            "Installed official MCP server '%s' for tenant %s",
            effective_name,
            tenant_id,
        )


async def _create_knowledge_bases(
    bundle: OfficialAgentBundle,
    tenant_id: str,
    user_id: str,
    embedding_model_id: int,
    authorization: str,
    kb_renames: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Create the bundle's knowledge bases for the tenant and index seed docs.

    Each knowledge base is created as an independent per-tenant instance (the
    vector index name is generated per KB, so tenants never share indices).
    Returns a mapping ``logical_index_name -> actual tenant index_name``. A KB
    whose display name already exists in the tenant is reused unchanged, unless
    ``kb_renames`` maps its logical index name to a new display name (then it is
    created fresh under the new name).
    """
    from database.knowledge_db import get_knowledge_record
    from services.vectordatabase_service import (
        ElasticSearchService,
        get_embedding_model_by_id,
        get_vector_db_core,
    )

    vdb_core = get_vector_db_core()
    embedding_model, _ = get_embedding_model_by_id(tenant_id, embedding_model_id)
    mapping: Dict[str, str] = {}
    renames = kb_renames or {}

    for kb in bundle.knowledge_bases or []:
        logical = kb.logical_index_name
        kb_name = renames.get(logical) or kb.display_name or logical
        logger.info(
            "[KB-DEBUG] bundle=%s logical=%r kb_name=%r documents=%d",
            bundle.name, logical, kb_name, len(kb.documents or []),
        )
        # Reuse by display name (matching the KB page's per-tenant uniqueness),
        # not by the logical key: logical keys never match a real index_name, so
        # name-based reuse avoids creating a duplicate KB on re-install.
        existing = get_knowledge_record(
            {"knowledge_name": kb_name, "tenant_id": tenant_id}
        )
        if existing:
            existing_index = existing.get("index_name") or logical
            logger.info(
                "[KB-DEBUG] '%s' already exists, reusing index %s",
                kb_name,
                existing_index,
            )
            mapping[logical] = existing_index
            continue

        created = ElasticSearchService.create_knowledge_base(
            knowledge_name=kb_name,
            embedding_dim=None,
            vdb_core=vdb_core,
            user_id=user_id,
            tenant_id=tenant_id,
            embedding_model_id=embedding_model_id,
        )
        actual_index = created["id"]
        logger.info(
            "[KB-DEBUG] created new KB name=%r index=%s", kb_name, actual_index,
        )

        if kb.documents:
            text_docs = [doc for doc in kb.documents if doc.content]
            file_docs = [doc for doc in kb.documents if doc.file_path]
            logger.info(
                "[KB-DEBUG] index=%s text_docs=%d file_docs=%d",
                actual_index, len(text_docs), len(file_docs),
            )
            if text_docs:
                data = [
                    {
                        "content": doc.content,
                        "path_or_url": doc.file_name,
                        "source_type": "local",
                        "filename": doc.file_name,
                        "metadata": {"title": doc.file_name},
                    }
                    for doc in text_docs
                ]
                ElasticSearchService.index_documents(
                    embedding_model=embedding_model,
                    index_name=actual_index,
                    data=data,
                    vdb_core=vdb_core,
                    model_id=embedding_model_id,
                )
                logger.info(
                    "Indexed %d text seed document(s) into knowledge base '%s'",
                    len(text_docs),
                    actual_index,
                )
            if file_docs:
                await _index_binary_docs(
                    actual_index,
                    file_docs,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    embedding_model_id=embedding_model_id,
                    authorization=authorization,
                )
                logger.info(
                    "Uploaded %d file seed document(s) for processing into "
                    "knowledge base '%s'",
                    len(file_docs),
                    actual_index,
                )
        mapping[logical] = actual_index

    return mapping


async def _index_binary_docs(
    index_name: str,
    docs: List[KnowledgeBaseSeedDoc],
    *,
    tenant_id: str,
    user_id: str,
    embedding_model_id: int,
    authorization: str,
) -> None:
    """Upload binary seed docs (docx/pdf/...) and trigger the platform pipeline.

    Reuses the same file pipeline as the knowledge base page: upload to MinIO,
    then trigger async data processing which parses, chunks and embeds the
    documents. Processing runs in the background; the KB is searchable once it
    completes.
    """
    from io import BytesIO

    from starlette.datastructures import UploadFile

    from consts.model import ProcessParams
    from services.file_management_service import upload_files_impl
    from utils.file_management_utils import trigger_data_process

    files_to_process: List[Dict[str, str]] = []
    for doc in docs:
        with open(doc.file_path, "rb") as f:
            file_bytes = f.read()
        upload_file = UploadFile(
            filename=os.path.basename(doc.file_path),
            file=BytesIO(file_bytes),
        )
        _, uploaded_file_paths, _ = await upload_files_impl(
            destination="minio",
            file=[upload_file],
            folder="knowledge_base",
            index_name=index_name,
            user_id=user_id,
            uploader_tenant_id=tenant_id,
        )
        if not uploaded_file_paths:
            logger.warning(
                "[KB-DEBUG] upload returned empty paths for '%s' index %s",
                doc.file_name,
                index_name,
            )
            continue
        logger.info(
            "[KB-DEBUG] uploaded '%s' -> %s", doc.file_name, uploaded_file_paths[0],
        )
        files_to_process.append(
            {
                "path_or_url": uploaded_file_paths[0],
                "filename": doc.file_name,
            }
        )

    logger.info(
        "[KB-DEBUG] index=%s trigger_data_process over %d file(s)",
        index_name, len(files_to_process),
    )
    if files_to_process:
        await trigger_data_process(
            files_to_process,
            ProcessParams(
                chunking_strategy="basic",
                source_type="minio",
                index_name=index_name,
                model_id=embedding_model_id,
                authorization=authorization,
            ),
        )


def _remap_kb_refs(
    bundle: OfficialAgentBundle,
    mapping: Dict[str, str],
) -> None:
    """Rewrite KB tool ``params.index_names`` from logical keys to real index names.

    The bundle's tools reference knowledge bases by their logical index names;
    after per-tenant KB creation those names must point at the generated tenant
    index names or the search tool would look up a non-existent index.
    """
    for agent in bundle.agent_info.values():
        for tool in agent.tools or []:
            if tool.class_name not in _KB_TOOL_CLASS_NAMES:
                continue
            params = tool.params or {}
            index_names = params.get("index_names")
            if isinstance(index_names, list):
                params["index_names"] = [
                    mapping.get(str(index_name), index_name)
                    for index_name in index_names
                ]


async def _install_bundle(
    bundle: OfficialAgentBundle,
    tenant_id: str,
    user_id: str,
    authorization: str,
    embedding_model_id: Optional[int] = None,
    steps: Optional[List[OfficialAgentInstallStep]] = None,
    skill_renames: Optional[Dict[str, str]] = None,
    kb_renames: Optional[Dict[str, str]] = None,
    mcp_renames: Optional[Dict[str, str]] = None,
    mcp_skips: Optional[List[str]] = None,
) -> Optional[int]:
    """Install one official agent bundle, returning the new main agent id.

    Order matters: MCP servers first (with the tool list refresh folded in),
    then skills, then knowledge bases (with KB tool reference remapping), then
    the agent import (which validates that every referenced tool exists).

    Skill names already present in the tenant are reused (not re-created), so
    installing into a tenant that already has a same-name skill succeeds.
    ``skill_renames`` / ``kb_renames`` map original names to new names for the
    resources the user chose to rename instead of reuse.

    Each step's outcome (ok/failed + reason) is appended to ``steps`` so the
    caller can surface exactly where an install failed.
    """
    if steps is None:
        steps = []

    async def _run_step(name: str, coroutine):
        try:
            result = await coroutine
        except Exception as e:
            steps.append(
                OfficialAgentInstallStep(name=name, status="failed", message=str(e))
            )
            raise
        steps.append(OfficialAgentInstallStep(name=name, status="ok"))
        return result

    async def _install_mcp_and_tools():
        await _install_mcp_servers(
            bundle,
            tenant_id,
            user_id,
            mcp_renames=mcp_renames,
            mcp_skips=mcp_skips,
        )
        from services.tool_configuration_service import update_tool_list

        await update_tool_list(tenant_id=tenant_id, user_id=user_id)

    await _run_step("mcp", _install_mcp_and_tools())

    from services.agent_service import (
        _create_skills_for_install,
        _import_agent_with_skill_links,
        import_agent_impl,
    )

    skill_name_to_id: Dict[str, int] = {}
    if bundle.skills:
        skill_name_to_id = await _run_step(
            "skill",
            _create_skills_for_install(
                bundle.skills,
                tenant_id,
                user_id,
                reuse_existing_skills=True,
                skill_renames=skill_renames,
            ),
        )

    if bundle.knowledge_bases:
        if embedding_model_id is None:
            embedding_model_id = await _first_available_embedding_model_id(tenant_id)
        if embedding_model_id is None:
            raise ValueError(
                "Official agent '%s' carries knowledge bases but the tenant has "
                "no available embedding model" % bundle.name
            )
        kb_mapping = await _run_step(
            "knowledge_base",
            _create_knowledge_bases(
                bundle,
                tenant_id,
                user_id,
                embedding_model_id,
                authorization=authorization,
                kb_renames=kb_renames,
            ),
        )
        _remap_kb_refs(bundle, kb_mapping)

    if bundle.skills:
        agent_id_mapping = await _run_step(
            "agent",
            _import_agent_with_skill_links(
                bundle,
                skill_name_to_id,
                authorization,
                tenant_id=tenant_id,
                user_id=user_id,
            ),
        )
    else:
        agent_id_mapping = await _run_step(
            "agent",
            import_agent_impl(
                bundle,
                authorization,
                tenant_id=tenant_id,
                user_id=user_id,
            ),
        )

    return agent_id_mapping.get(bundle.agent_id)


def _apply_install_options(
    bundle: OfficialAgentBundle,
    renames: Optional[Dict[str, str]] = None,
    model_ids: Optional[Dict[str, int]] = None,
) -> None:
    """Apply user-selected renames and model ids to a loaded bundle in place.

    ``renames`` maps an existing agent name to a new name; every agent in the
    bundle whose name is a key is renamed before import. ``model_ids`` maps a
    bundle key to a tenant model_id applied to every agent in the bundle
    (unified, mirroring the agent-config import wizard), resolved against the
    tenant catalog by the import flow.
    """
    for agent in bundle.agent_info.values():
        new_name = (renames or {}).get(agent.name)
        if new_name:
            agent.name = new_name
    if model_ids and bundle.name in model_ids:
        selected = model_ids[bundle.name]
        for agent in bundle.agent_info.values():
            agent.model_ids = [selected]


async def _install_one_bundle(
    bundle: OfficialAgentBundle,
    name: str,
    tenant_id: str,
    user_id: str,
    authorization: str,
    renames: Optional[Dict[str, str]] = None,
    model_ids: Optional[Dict[str, int]] = None,
    embedding_model_ids: Optional[Dict[str, int]] = None,
    skill_renames: Optional[Dict[str, str]] = None,
    kb_renames: Optional[Dict[str, str]] = None,
    mcp_renames: Optional[Dict[str, str]] = None,
    mcp_skips: Optional[List[str]] = None,
) -> OfficialAgentInstallItem:
    """Install one loaded bundle, returning its per-agent result item.

    Shared by the local and GitCode install paths. ``name`` is the bundle key
    (used for ``model_ids``/``embedding_model_ids`` lookups). A failure on this
    bundle is captured in the returned item and never raised.
    """
    root_agent = bundle.agent_info.get(str(bundle.agent_id))
    root_name = getattr(root_agent, "name", None) if root_agent else None
    root_renamed = bool(renames) and bool(root_name) and root_name in renames
    if not root_renamed and _is_agent_installed(bundle, tenant_id):
        return OfficialAgentInstallItem(name=name, status="already_installed")

    missing_models = await _missing_model_types(bundle, tenant_id)
    if missing_models:
        return OfficialAgentInstallItem(
            name=name,
            status="needs_model",
            missing_models=missing_models,
            message="缺少模型: " + ", ".join(missing_models),
        )

    _apply_install_options(bundle, renames, model_ids)

    embedding_model_id: Optional[int] = None
    if bundle.knowledge_bases:
        embedding_model_id = (embedding_model_ids or {}).get(name)
        if embedding_model_id is None:
            embedding_model_id = await _first_available_embedding_model_id(
                tenant_id
            )

    steps: List[OfficialAgentInstallStep] = []
    try:
        agent_id = await _install_bundle(
            bundle,
            tenant_id,
            user_id,
            authorization,
            embedding_model_id=embedding_model_id,
            steps=steps,
            skill_renames=skill_renames,
            kb_renames=kb_renames,
            mcp_renames=mcp_renames,
            mcp_skips=mcp_skips,
        )
        return OfficialAgentInstallItem(
            name=name, status="installed", steps=steps, agent_id=agent_id
        )
    except Exception as e:
        logger.exception(
            "Failed to install official agent '%s' for tenant %s",
            name,
            tenant_id,
        )
        return OfficialAgentInstallItem(
            name=name, status="failed", message=str(e), steps=steps
        )


async def install_official_agents(
    agent_names: List[str],
    tenant_id: str,
    user_id: str,
    authorization: str,
    renames: Optional[Dict[str, str]] = None,
    model_ids: Optional[Dict[str, int]] = None,
    embedding_model_ids: Optional[Dict[str, int]] = None,
    skill_renames: Optional[Dict[str, str]] = None,
    kb_renames: Optional[Dict[str, str]] = None,
    mcp_renames: Optional[Dict[str, str]] = None,
    mcp_skips: Optional[List[str]] = None,
) -> List[OfficialAgentInstallItem]:
    """Install the requested official agents for a tenant.

    Each agent is processed independently: a failure on one does not affect the
    others. Agents already present in the tenant are skipped, unless the root
    agent name is being renamed via ``renames`` (the user explicitly asked for a
    differently-named copy).

    ``renames`` maps an existing agent name inside a bundle to a new name;
    ``model_ids`` maps a bundle key to a tenant LLM model_id for the root agent;
    ``embedding_model_ids`` maps a bundle key to a tenant embedding model_id used
    to create its knowledge bases (falls back to the first available embedding
    model when omitted). ``skill_renames`` / ``kb_renames`` map original resource
    names to new names for the resources the user chose to rename instead of
    reuse. ``mcp_renames`` maps a conflicting MCP name to a new name, and
    ``mcp_skips`` lists conflicting MCP names to skip entirely.
    """
    results: List[OfficialAgentInstallItem] = []
    for name in agent_names:
        bundle = _load_bundle(name)
        if bundle is None:
            results.append(
                OfficialAgentInstallItem(
                    name=name,
                    status="not_found",
                    message=f"Official agent bundle '{name}' not found",
                )
            )
            continue
        results.append(
            await _install_one_bundle(
                bundle,
                name,
                tenant_id,
                user_id,
                authorization,
                renames=renames,
                model_ids=model_ids,
                embedding_model_ids=embedding_model_ids,
                skill_renames=skill_renames,
                kb_renames=kb_renames,
                mcp_renames=mcp_renames,
                mcp_skips=mcp_skips,
            )
        )
    return results


# ---------------------------------------------------------------------------
# GitCode 固定源：快照获取 / 目录发现 / 安装
# ---------------------------------------------------------------------------


def _resolve_repo_source(ref: Optional[str] = None):
    """Resolve the fixed GitCode source into ``(url, owner, repo, ref)``.

    Validates that the configured URL points at gitcode.com and that the
    ``owner/repo`` path is well-formed. Raises ``RepoSourceError`` on any
    configuration problem.
    """
    url = (OFFICIAL_AGENTS_REPO_URL or "").strip().rstrip("/")
    if not url:
        raise RepoSourceError("repo_source_not_configured", "仓库源未配置")
    parsed = urlparse(url)
    if parsed.hostname not in _GITCODE_HOSTS:
        raise RepoSourceError(
            "repo_source_not_configured",
            f"仓库源域名不受支持: {parsed.hostname}",
        )
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or not (
        _REPO_NAME_RE.fullmatch(parts[0]) and _REPO_NAME_RE.fullmatch(parts[1])
    ):
        raise RepoSourceError(
            "repo_source_not_configured", f"仓库地址格式不合法: {url}"
        )
    owner, repo = parts[0], parts[1]
    effective_ref = ref or OFFICIAL_AGENTS_REPO_REF or "main"
    return url, owner, repo, effective_ref


def _git_clone_snapshot(url: str, ref: str, snapshot_dir: str) -> str:
    """Shallow-clone ``url@ref`` into ``snapshot_dir`` and return the commit SHA.

    Raises ``RepoSourceError`` when git is unavailable or the clone fails.
    """
    if shutil.which("git") is None:
        raise RepoSourceError(
            "git_binary_missing", "服务器缺少 git 环境，无法从仓库源拉取智能体"
        )
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, url, snapshot_dir],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        commit = subprocess.run(
            ["git", "-C", snapshot_dir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RepoSourceError(
            "repo_clone_failed",
            f"仓库拉取失败: {(e.stderr or e.stdout or str(e))[-500:]}",
        )
    except subprocess.TimeoutExpired:
        raise RepoSourceError("repo_network_error", "仓库拉取超时")
    except OSError as e:
        raise RepoSourceError("repo_network_error", f"仓库拉取失败: {e}")
    return commit


def _snapshot_size_bytes(path: str) -> int:
    """Return the total size of files under ``path`` (used for the cap check)."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def _ensure_repo_snapshot(url: str, ref: str):
    """Return ``(snapshot_dir, commit)`` for ``url@ref``, cloning when needed.

    Snapshots are cached under the temp dir keyed by ``(url, ref)`` so discover
    and install reuse the exact same commit within a session. Clone is staged to
    a unique dir first (size cap check) then moved into the cache key.
    """
    key = hashlib.sha1(f"{url}@{ref}".encode("utf-8")).hexdigest()[:16]
    snapshot_dir = os.path.join(_SNAPSHOT_ROOT, key)
    commit_file = os.path.join(_SNAPSHOT_ROOT, f"{key}.commit")

    if os.path.isdir(snapshot_dir) and os.path.isfile(commit_file):
        try:
            with open(commit_file, encoding="utf-8") as f:
                cached_commit = f.read().strip()
            if cached_commit:
                return snapshot_dir, cached_commit
        except OSError:
            pass

    staging = f"{snapshot_dir}.tmp-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    commit = _git_clone_snapshot(url, ref, staging)
    size = _snapshot_size_bytes(staging)
    if size > SNAPSHOT_MAX_BYTES:
        shutil.rmtree(staging, ignore_errors=True)
        raise RepoSourceError(
            "snapshot_too_large",
            f"仓库包大小 {size} 超过上限 {SNAPSHOT_MAX_BYTES}",
        )

    shutil.rmtree(snapshot_dir, ignore_errors=True)
    shutil.move(staging, snapshot_dir)
    try:
        with open(commit_file, "w", encoding="utf-8") as f:
            f.write(commit)
    except OSError:
        logger.warning("Failed to persist GitCode snapshot commit for %s", url)
    return snapshot_dir, commit


def clear_repo_snapshot_cache() -> None:
    """Clear the GitCode snapshot cache (test / ops helper)."""
    shutil.rmtree(_SNAPSHOT_ROOT, ignore_errors=True)


def _discover_bundles_in_dir(base_dir: str) -> List[str]:
    """Return relative-path bundle keys under ``base_dir`` (directory-only rule).

    A bundle root is a directory that directly contains ``agent.json``. Loose
    ``*.json`` files are ignored: the AgentsHub repo carries stray bundle-shaped
    JSON files that must not be surfaced as installable agents.
    """
    keys: List[str] = []
    for dirpath, dirnames, filenames in os.walk(base_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if "agent.json" not in filenames:
            continue
        rel = os.path.relpath(dirpath, base_dir).replace("\\", "/")
        if rel == ".":
            continue
        keys.append(rel)
    return sorted(keys)


def _group_and_categorize(bundle_keys: List[str]):
    """Group bundle keys into ``{group: {category: [keys]}}``.

    The first path segment is the group (unknown groups fall into ``其他``) and
    the second is the category.
    """
    grouped: Dict[str, Dict[str, List[str]]] = {}
    for key in bundle_keys:
        parts = key.split("/")
        group = parts[0] if parts else "其他"
        if group not in _KNOWN_GROUPS:
            group = "其他"
        category = parts[1] if len(parts) >= 2 else "其他"
        grouped.setdefault(group, {}).setdefault(category, []).append(key)
    return grouped


def _gitcode_api_base(owner: str, repo: str) -> str:
    """Return the GitCode v5 API base for a repository."""
    return f"https://api.gitcode.com/api/v5/repos/{quote(owner)}/{quote(repo)}"


def _gitcode_api_get(path: str, params: Dict[str, str]):
    """GET and decode a public GitCode API response.

    This intentionally uses the repository API instead of cloning the repo. A
    token can be added later at the HTTP boundary if the repository becomes
    private; discovery itself remains path-only.
    """
    query = urlencode(params)
    request = Request(
        f"{path}?{query}",
        headers={"Accept": "application/json", "User-Agent": "Nexent"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("GitCode API request failed for %s: %s", path, exc)
        raise RepoSourceError("repo_api_failed", f"仓库目录读取失败: {exc}") from exc


def _gitcode_file_paths(owner: str, repo: str, ref: str) -> List[str]:
    """List all repository file paths without downloading file contents."""
    payload = _gitcode_api_get(
        f"{_gitcode_api_base(owner, repo)}/file_list", {"ref_name": ref}
    )
    entries = payload
    if isinstance(payload, dict):
        entries = (
            payload.get("data")
            or payload.get("files")
            or payload.get("tree")
            or []
        )
    if not isinstance(entries, list):
        raise RepoSourceError("repo_api_failed", "仓库目录读取失败: 返回格式无效")

    paths: List[str] = []
    for entry in entries:
        path = (
            entry.get("path") or entry.get("file_name") or entry.get("name")
            if isinstance(entry, dict)
            else entry
        )
        if isinstance(path, str) and path:
            paths.append(path.strip("/"))
    return sorted(paths)


def _gitcode_bundle_keys(repo_paths: List[str]) -> List[str]:
    """Derive bundle directories from the repository file paths."""
    bundle_keys = {
        os.path.dirname(path).replace("\\", "/")
        for path in repo_paths
        if path.lower().endswith("/agent.json")
        and os.path.dirname(path) not in ("", ".")
    }
    return sorted(bundle_keys)


def _is_remote_bundle_installed(bundle_key: str, tenant_id: str) -> bool:
    """Check installation state using the folder name."""
    from database.agent_db import search_agent_id_by_agent_name

    agent_name = os.path.basename(bundle_key)
    try:
        search_agent_id_by_agent_name(agent_name, tenant_id)
        return True
    except ValueError:
        return False


def _gitcode_agent_names(owner: str, repo: str, ref: str, bundle_key: str) -> List[str]:
    """Read only one bundle's metadata to resolve its installed root name."""
    try:
        raw = _gitcode_raw_file(owner, repo, ref, f"{bundle_key}/agent.json")
        payload = json.loads(raw.decode("utf-8"))
        agent_info = payload.get("agent_info", {})
        if not isinstance(agent_info, dict):
            return []
        return [
            str(agent.get("name"))
            for agent in agent_info.values()
            if isinstance(agent, dict) and agent.get("name")
        ]
    except (RepoSourceError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        logger.warning("Unable to read metadata for remote bundle '%s'", bundle_key)
        return []


def _is_remote_bundle_installed_with_names(
    bundle_key: str, tenant_id: str, agent_names: List[str]
) -> bool:
    """Check a remote bundle using both folder and serialized agent names."""
    from database.agent_db import search_agent_id_by_agent_name

    candidates = [os.path.basename(bundle_key), *agent_names]
    for agent_name in dict.fromkeys(candidates):
        try:
            search_agent_id_by_agent_name(agent_name, tenant_id)
            return True
        except ValueError:
            continue
    return False


def _gitcode_raw_file(owner: str, repo: str, ref: str, path: str) -> bytes:
    """Download one selected bundle file from GitCode."""
    endpoint = f"{_gitcode_api_base(owner, repo)}/raw/{quote(path, safe='/')}"
    query = urlencode({"ref": ref})
    request = Request(
        f"{endpoint}?{query}",
        headers={"Accept": "application/octet-stream", "User-Agent": "Nexent"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("GitCode raw file request failed for %s: %s", path, exc)
        raise RepoSourceError("repo_api_failed", f"智能体文件下载失败: {path}") from exc


def _download_gitcode_bundle(
    owner: str, repo: str, ref: str, bundle_key: str, repo_paths: List[str]
) -> str:
    """Download one bundle into a temporary directory and return its root."""
    bundle_paths = [
        path
        for path in repo_paths
        if path == bundle_key or path.startswith(f"{bundle_key}/")
    ]
    if not bundle_paths:
        raise FileNotFoundError(bundle_key)

    staging_dir = tempfile.mkdtemp(prefix="official-agent-")
    try:
        total_bytes = 0
        for path in bundle_paths:
            content = _gitcode_raw_file(owner, repo, ref, path)
            total_bytes += len(content)
            if total_bytes > SNAPSHOT_MAX_BYTES:
                raise RepoSourceError(
                    "bundle_too_large",
                    f"智能体包大小超过上限 {SNAPSHOT_MAX_BYTES} 字节",
                )
            target = _safe_relative_path_under(staging_dir, path)
            if target is None:
                raise RepoSourceError("repo_api_failed", "智能体文件路径无效")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as file:
                file.write(content)
        return staging_dir
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


async def discover_from_gitcode(
    tenant_id: str, ref: Optional[str] = None
) -> OfficialAgentGithubDiscoverResult:
    """Discover the fixed GitCode repo into a group -> category -> bundle catalog.

    Only the repository file list is requested. The UI currently needs the
    bundle directory name, so downloading every agent.json (or cloning the
    repository) during discovery is unnecessary.
    """
    _, owner, repo, effective_ref = _resolve_repo_source(ref)
    repo_paths = _gitcode_file_paths(owner, repo, effective_ref)
    keys = _gitcode_bundle_keys(repo_paths)
    grouped = _group_and_categorize(keys)

    groups: List[OfficialAgentGithubGroup] = []
    for group_name in sorted(grouped):
        categories: List[OfficialAgentGithubCategory] = []
        for cat_name in sorted(grouped[group_name]):
            bundles = [
                OfficialAgentListItem(
                    name=key,
                    display_name=os.path.basename(key),
                    status=(
                        "installed"
                        if _is_remote_bundle_installed_with_names(
                            key,
                            tenant_id,
                            _gitcode_agent_names(owner, repo, effective_ref, key),
                        )
                        else "installable"
                    ),
                    has_knowledge=False,
                    mcp_count=0,
                    skill_count=0,
                    kb_count=0,
                )
                for key in grouped[group_name][cat_name]
            ]
            categories.append(
                OfficialAgentGithubCategory(name=cat_name, bundles=bundles)
            )
        groups.append(OfficialAgentGithubGroup(name=group_name, categories=categories))

    return OfficialAgentGithubDiscoverResult(
        repo=f"{owner}/{repo}",
        ref=effective_ref,
        commit=None,
        groups=groups,
    )


async def install_from_gitcode(
    agent_names: List[str],
    tenant_id: str,
    user_id: str,
    authorization: str,
    renames: Optional[Dict[str, str]] = None,
    model_ids: Optional[Dict[str, int]] = None,
    embedding_model_ids: Optional[Dict[str, int]] = None,
    ref: Optional[str] = None,
    skill_renames: Optional[Dict[str, str]] = None,
    kb_renames: Optional[Dict[str, str]] = None,
    mcp_renames: Optional[Dict[str, str]] = None,
    mcp_skips: Optional[List[str]] = None,
) -> OfficialAgentGithubInstallResult:
    """Install remote official agents by their relative bundle keys.

    Downloads only the selected bundle and installs it through the shared
    ``_install_one_bundle`` pipeline. The repository itself is never cloned.
    """
    _, owner, repo, effective_ref = _resolve_repo_source(ref)
    repo_paths = _gitcode_file_paths(owner, repo, effective_ref)
    available = set(_gitcode_bundle_keys(repo_paths))

    results: List[OfficialAgentInstallItem] = []
    for name in agent_names:
        if name not in available:
            results.append(
                OfficialAgentInstallItem(
                    name=name,
                    status="not_found",
                    message=f"Remote agent bundle '{name}' not found",
                )
            )
            continue
        staging_dir = _download_gitcode_bundle(
            owner, repo, effective_ref, name, repo_paths
        )
        try:
            bundle = _load_bundle(name, staging_dir)
            if bundle is None:
                results.append(
                    OfficialAgentInstallItem(
                        name=name,
                        status="not_found",
                        message=f"Remote agent bundle '{name}' is invalid",
                    )
                )
                continue
            results.append(
                await _install_one_bundle(
                    bundle,
                    name,
                    tenant_id,
                    user_id,
                    authorization,
                    renames=renames,
                    model_ids=model_ids,
                    embedding_model_ids=embedding_model_ids,
                    skill_renames=skill_renames,
                    kb_renames=kb_renames,
                    mcp_renames=mcp_renames,
                    mcp_skips=mcp_skips,
                )
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
    return OfficialAgentGithubInstallResult(
        repo=f"{owner}/{repo}", commit=None, results=results
    )
