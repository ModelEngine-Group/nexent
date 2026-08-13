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
import json
import logging
import os
from typing import Dict, List, Optional

from consts.const import OFFICIAL_AGENTS_PATH
from consts.model import (
    KnowledgeBaseSeedDoc,
    ModelConnectStatusEnum,
    OfficialAgentAgentInfo,
    OfficialAgentBundle,
    OfficialAgentInstallItem,
    OfficialAgentInstallStep,
    OfficialAgentListItem,
    OfficialAgentMcpPreview,
    SkillZipEntry,
)

logger = logging.getLogger("official_agent_service")

# Tool classes that reference a knowledge base by params.index_names.
_KB_TOOL_CLASS_NAMES = frozenset({"KnowledgeBaseSearchTool", "DataMateSearchTool"})

# KB seed file suffixes treated as plain text (embedded via index_documents).
_TEXT_DOC_SUFFIXES = frozenset({".md", ".txt", ".markdown"})


def _list_bundle_files() -> List[str]:
    """Return sorted official bundle keys found under OFFICIAL_AGENTS_PATH.

    A bundle is either a directory (``<name>/agent.json``) or a single JSON file
    (``<name>.json``) — mirroring the dual import-agent formats.
    """
    if not os.path.isdir(OFFICIAL_AGENTS_PATH):
        logger.warning(
            "Official agents bundle directory not found: %s",
            OFFICIAL_AGENTS_PATH,
        )
        return []
    try:
        names = set()
        for entry in os.listdir(OFFICIAL_AGENTS_PATH):
            entry_path = os.path.join(OFFICIAL_AGENTS_PATH, entry)
            if os.path.isdir(entry_path) and os.path.isfile(
                os.path.join(entry_path, "agent.json")
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
    skills_dir = os.path.join(dir_path, "skills")
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
        zip_path = os.path.join(skills_dir, f"{skill_name}.zip")
        if not os.path.isfile(zip_path):
            logger.warning(
                "Official agent '%s' references skill '%s' but %s is missing",
                bundle.name,
                skill_name,
                zip_path,
            )
            continue
        with open(zip_path, "rb") as f:
            zip_bytes = f.read()
        attached.append(
            SkillZipEntry(
                skill_name=skill_name,
                skill_zip_base64=base64.b64encode(zip_bytes).decode("ascii"),
            )
        )
    if attached:
        bundle.skills = attached


def _attach_kb_docs_from_dir(bundle: OfficialAgentBundle, dir_path: str) -> None:
    """Attach knowledge base seed documents from ``<dir>/kb/<logical_index_name>/*``.

    Text files (.md/.txt) are read into ``content``; other files (docx/pdf/...)
    are kept as ``file_path`` pointing at the real file so the install pipeline
    can upload and process them like a normal knowledge base document.
    """
    kb_dir = os.path.join(dir_path, "kb")
    if not os.path.isdir(kb_dir):
        return
    for kb in bundle.knowledge_bases or []:
        logical_dir = os.path.join(kb_dir, kb.logical_index_name)
        if not os.path.isdir(logical_dir):
            continue
        docs: List[KnowledgeBaseSeedDoc] = []
        try:
            for file_name in sorted(os.listdir(logical_dir)):
                file_path = os.path.join(logical_dir, file_name)
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


def _load_bundle(name: str) -> Optional[OfficialAgentBundle]:
    """Load a bundle by key, supporting both directory and single-file layouts.

    Directory layout: ``<name>/agent.json`` + ``skills/`` + ``kb/`` (skills and
    KB documents are attached from files). Single-file layout: ``<name>.json``
    with skills/documents inline. The key is treated as the authoritative name.
    """
    dir_path = os.path.join(OFFICIAL_AGENTS_PATH, name)
    if os.path.isdir(dir_path) and os.path.isfile(
        os.path.join(dir_path, "agent.json")
    ):
        try:
            with open(os.path.join(dir_path, "agent.json"), encoding="utf-8") as f:
                data = json.load(f)
            bundle = OfficialAgentBundle.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Skip invalid official agent bundle '%s': %s", name, e)
            return None
        bundle.name = name
        _attach_skills_from_dir(bundle, dir_path)
        _attach_kb_docs_from_dir(bundle, dir_path)
        return bundle

    single_path = os.path.join(OFFICIAL_AGENTS_PATH, f"{name}.json")
    if os.path.isfile(single_path):
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
    only when a server with the same name AND url already exists.
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
            )
        )
    return previews


async def list_official_agents_with_status(
    tenant_id: str,
) -> List[OfficialAgentListItem]:
    """List all official agents with their installation status for a tenant.

    Status priority: installed > needs_model > installable.
    """
    items: List[OfficialAgentListItem] = []
    for name in _list_bundle_files():
        bundle = _load_bundle(name)
        if bundle is None:
            continue

        has_knowledge = bool(bundle.knowledge_bases)
        missing_models = await _missing_model_types(bundle, tenant_id)

        if _is_agent_installed(bundle, tenant_id):
            status = "installed"
        elif missing_models:
            status = "needs_model"
        else:
            status = "installable"

        items.append(
            OfficialAgentListItem(
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
            )
        )
    return items


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


async def _install_mcp_servers(
    bundle: OfficialAgentBundle,
    tenant_id: str,
    user_id: str,
) -> None:
    """Install the bundle's MCP servers that are missing in the tenant.

    An MCP is skipped only when a server with the same name AND url already
    exists (matching the agent-config import behaviour). A server whose name is
    taken by a different URL is a genuine conflict and aborts the install with
    a clear message, so the agent's tools never point at the wrong server.

    Official MCP endpoints are trusted platform-provided URLs, so health checks
    are skipped.
    """
    from database.remote_mcp_db import get_mcp_server_by_name_and_tenant
    from services.remote_mcp_service import add_mcp_service

    for mcp in bundle.mcp_info or []:
        existing_url = get_mcp_server_by_name_and_tenant(
            mcp.mcp_server_name, tenant_id
        )
        if existing_url == mcp.mcp_url:
            logger.info(
                "MCP server '%s' already exists for tenant %s with the same "
                "URL, skipping",
                mcp.mcp_server_name,
                tenant_id,
            )
            continue
        if existing_url:
            raise ValueError(
                f"MCP server name '{mcp.mcp_server_name}' already exists for "
                f"tenant {tenant_id} but with a different URL "
                f"('{existing_url}' != '{mcp.mcp_url}'). Remove or rename the "
                f"existing server before installing."
            )
        await add_mcp_service(
            tenant_id=tenant_id,
            user_id=user_id,
            name=mcp.mcp_server_name,
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
            mcp.mcp_server_name,
            tenant_id,
        )


async def _create_knowledge_bases(
    bundle: OfficialAgentBundle,
    tenant_id: str,
    user_id: str,
    embedding_model_id: int,
    authorization: str,
) -> Dict[str, str]:
    """Create the bundle's knowledge bases for the tenant and index seed docs.

    Each knowledge base is created as an independent per-tenant instance (the
    vector index name is generated per KB, so tenants never share indices).
    Returns a mapping ``logical_index_name -> actual tenant index_name``. A KB
    whose logical index name already exists in the tenant is reused unchanged.
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

    for kb in bundle.knowledge_bases or []:
        logical = kb.logical_index_name
        kb_name = kb.display_name or logical
        # Reuse by display name (matching the KB page's per-tenant uniqueness),
        # not by the logical key: logical keys never match a real index_name, so
        # name-based reuse avoids creating a duplicate KB on re-install.
        existing = get_knowledge_record(
            {"knowledge_name": kb_name, "tenant_id": tenant_id}
        )
        if existing:
            existing_index = existing.get("index_name") or logical
            logger.info(
                "Knowledge base '%s' already exists for tenant %s, reusing "
                "(index %s)",
                kb_name,
                tenant_id,
                existing_index,
            )
            mapping[logical] = existing_index
            continue

        created = ElasticSearchService.create_knowledge_base(
            knowledge_name=kb.display_name or logical,
            embedding_dim=None,
            vdb_core=vdb_core,
            user_id=user_id,
            tenant_id=tenant_id,
            embedding_model_id=embedding_model_id,
        )
        actual_index = created["id"]

        if kb.documents:
            text_docs = [doc for doc in kb.documents if doc.content]
            file_docs = [doc for doc in kb.documents if doc.file_path]
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
                "Failed to upload KB seed file '%s' for index %s",
                doc.file_name,
                index_name,
            )
            continue
        files_to_process.append(
            {
                "path_or_url": uploaded_file_paths[0],
                "filename": doc.file_name,
            }
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
) -> Optional[int]:
    """Install one official agent bundle, returning the new main agent id.

    Order matters: MCP servers first (with the tool list refresh folded in),
    then skills, then knowledge bases (with KB tool reference remapping), then
    the agent import (which validates that every referenced tool exists).

    Skill names already present in the tenant are reused (not re-created), so
    installing into a tenant that already has a same-name skill succeeds.

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
        await _install_mcp_servers(bundle, tenant_id, user_id)
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


async def install_official_agents(
    agent_names: List[str],
    tenant_id: str,
    user_id: str,
    authorization: str,
    renames: Optional[Dict[str, str]] = None,
    model_ids: Optional[Dict[str, int]] = None,
    embedding_model_ids: Optional[Dict[str, int]] = None,
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
    model when omitted).
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

        root_agent = bundle.agent_info.get(str(bundle.agent_id))
        root_name = getattr(root_agent, "name", None) if root_agent else None
        root_renamed = bool(renames) and bool(root_name) and root_name in renames
        if not root_renamed and _is_agent_installed(bundle, tenant_id):
            results.append(
                OfficialAgentInstallItem(name=name, status="already_installed")
            )
            continue

        missing_models = await _missing_model_types(bundle, tenant_id)
        if missing_models:
            results.append(
                OfficialAgentInstallItem(
                    name=name,
                    status="needs_model",
                    missing_models=missing_models,
                    message="缺少模型: " + ", ".join(missing_models),
                )
            )
            continue

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
            )
            results.append(
                OfficialAgentInstallItem(
                    name=name, status="installed", steps=steps, agent_id=agent_id
                )
            )
        except Exception as e:
            logger.exception(
                "Failed to install official agent '%s' for tenant %s",
                name,
                tenant_id,
            )
            results.append(
                OfficialAgentInstallItem(
                    name=name, status="failed", message=str(e), steps=steps
                )
            )
    return results
