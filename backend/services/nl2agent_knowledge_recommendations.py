# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private UI recommendations over currently authorized selectable KB metadata."""

from contracts.constants.environment import NL2AGENT_KNOWLEDGE_MIN_SIMILARITY
from contracts.nl2agent_resources import KnowledgeRecommendationsRequest
from management.services.agent import nl2agent as legacy
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.knowledge_base.recommendation import load_visible_knowledge, rank_knowledge, selection_values
from nexent.core.concurrency import run_blocking
from services import nl2agent_semantic_retrieval as semantic
from services.nl2agent_state_service import ResourceStateError, read_resource_state, require_current_card


def _models(tenant_id):
    return {kind: tenant_config_manager.get_model_config(key=key, tenant_id=tenant_id) or {}
            for kind, key in (("embedding", "EMBEDDING_ID"), ("multi_embedding", "MULTI_EMBEDDING_ID"))}


def _public_models(models):
    result = {}
    for kind, model in models.items():
        result[f"{kind}_model_id"] = model.get("model_id")
        result[f"{kind}_model_name"] = model.get("display_name") or model.get("model_name")
    return result


async def _tools(scope):
    return await legacy._load_installed_resource_catalog(tenant_id=scope.tenant_id, user_id=scope.user_id)


def _saved(scope):
    return {f"tool:{row['tool_id']}": row.get("params") or {} for row in legacy.query_all_enabled_tool_instances(
        agent_id=scope.agent_id, tenant_id=scope.tenant_id, version_no=0)}


def _catalog(name, scope):
    rows = load_visible_knowledge(name, user_id=scope.user_id, tenant_id=scope.tenant_id)
    if name == "aidp_search" or not rows:
        return rows
    from management.services.knowledge_base.common import get_vector_db_core
    stats = get_vector_db_core().get_indices_detail([row["binding_value"] for row in rows])
    return [{**row, "document_count": max(
        stats.get(row["binding_value"], {}).get("base_info", {}).get("doc_count", 0) or 0,
        stats.get(row["binding_value"], {}).get("base_info", {}).get("chunk_count", 0) or 0,
    )} for row in rows]


def _selectable(rows, name, models, multimodal):
    if name == "aidp_search":
        return rows
    selected = []
    for row in rows:
        if not row.get("document_count"):
            continue
        model_id = row.get("embedding_model_id")
        is_multi = bool(row.get("is_multimodal")) or (
            model_id is not None and model_id == models["multi_embedding"].get("model_id"))
        current = models["multi_embedding" if is_multi else "embedding"]
        if multimodal is not None and bool(multimodal) != is_multi:
            continue
        if not model_id or not current.get("model_id") or model_id != current["model_id"]:
            continue
        selected.append({**row, "is_multimodal": is_multi})
    return selected


async def _read_catalog(name, scope):
    try:
        return await run_blocking("knowledge-recommendation-catalog", _catalog, name, scope,
                                  lane="control-io", owner=__name__)
    except ResourceStateError:
        raise
    except Exception as exc:
        raise ResourceStateError("knowledge_recommendations_unavailable", retryable=True) from exc


def _projection(row, name):
    return {"candidate_ref": f"knowledge:{name}:{row['id']}", "resource_type": "knowledge_base",
            "source": "KNOWLEDGE_METADATA", "name": row["name"],
            "description": "\n".join(str(row.get(key) or "") for key in ("description", "summary"))}


def _revision(row):
    return semantic.digest([row.get(key) for key in (
        "id", "binding_value", "name", "description", "summary", "embedding_model_id", "is_multimodal")])


async def recommend(scope, request: KnowledgeRecommendationsRequest):
    from services.nl2agent_resource_flow import coverage_rows, require_recommendation_current

    state = require_current_card(await read_resource_state(scope), scope, "requirement_resources", request)
    require_recommendation_current(state)
    rows = coverage_rows(state)
    tools = {row["candidate_ref"]: row for row in await _tools(scope)}
    models = await run_blocking("knowledge-recommendation-models", _models, scope.tenant_id, lane="control-io", owner=__name__)
    saved = await run_blocking("knowledge-recommendation-saved", _saved, scope, lane="control-io", owner=__name__)
    groups = {}
    for row in rows:
        for resource in row["covered_resources"]:
            ref = resource["candidate_ref"]
            actual = tools.get(ref)
            if actual is None:
                raise ResourceStateError("resource_not_visible")
            name = next((name for name in actual.get("names", [actual["name"]])
                         if name in {"knowledge_base_search", "aidp_search"}), None)
            if name:
                group = groups.setdefault(ref, {"name": name, "actual": actual, "queries": {}})
                group["queries"][row["requirement_id"]] = row["query"]
    catalogs = {}
    result = []
    for ref, group in groups.items():
        name, actual, queries = group["name"], group["actual"], group["queries"]
        values = saved.get(ref, {})
        defaults = {param["name"]: param.get("value") for param in actual.get("config", [])}
        multimodal = values.get("multimodal", defaults.get("multimodal", False))
        if name not in catalogs:
            catalogs[name] = await _read_catalog(name, scope)
        candidates = _selectable(catalogs[name], name, models, multimodal)
        by_ref = {_projection(row, name)["candidate_ref"]: row for row in candidates}
        lexical = rank_knowledge(candidates, list(queries.values()), [], tool_name=name, multimodal=multimodal)
        ranked = {f"knowledge:{name}:{row['id']}": row["score"] for row in lexical}
        mode = "text"
        if candidates:
            try:
                model = await semantic.resolve_model(scope.tenant_id)
                if model:
                    matches = await semantic.retrieve(scope.tenant_id, model, queries,
                        [_projection(row, name) for row in candidates], [], None,
                        minimum_similarity=NL2AGENT_KNOWLEDGE_MIN_SIMILARITY)
                    mode = "hybrid"
                    for match in matches.values():
                        for score, resource in match["installed"]:
                            key = resource["candidate_ref"]
                            if key in by_ref and score >= NL2AGENT_KNOWLEDGE_MIN_SIMILARITY:
                                ranked[key] = max(ranked.get(key, 0), score)
            except Exception:
                # Catalog/authentication failures are handled outside semantic fallback.
                mode = "fallback"
        fresh = _selectable(await _read_catalog(name, scope), name, models, multimodal)
        fresh_by_ref = {_projection(row, name)["candidate_ref"]: row for row in fresh}
        suggestions = [{**{key: by_ref[key_ref][key] for key in ("id", "binding_value", "name")}, "score": round(score, 4)}
            for key_ref, score in sorted(ranked.items(), key=lambda pair: (-pair[1], pair[0]))
            if key_ref in fresh_by_ref and _revision(fresh_by_ref[key_ref]) == _revision(by_ref[key_ref])][:5]
        field = "kds_list" if name == "aidp_search" else "index_names"
        selected = selection_values(values.get(field)) if ref in saved else [row["binding_value"] for row in suggestions]
        allowed = {row["binding_value"] for row in fresh}
        selected = [value for value in selected if value in allowed]
        result.append({"candidate_ref": ref, "tool_name": name, "recommendations": suggestions,
            "selected_values": selected, "selection_source": "saved" if ref in saved else "recommended",
            "settings": {key: value for key, value in values.items() if key in {"top_k", "multimodal"}},
            "models": _public_models(models), "mode": mode})
    if await run_blocking("knowledge-recommendation-model-recheck", _models, scope.tenant_id,
                          lane="control-io", owner=__name__) != models:
        raise ResourceStateError("knowledge_model_changed", retryable=True)
    state = require_current_card(await read_resource_state(scope), scope, "requirement_resources", request)
    require_recommendation_current(state)
    visible = {row["candidate_ref"] for row in await _tools(scope)}
    if not set(groups).issubset(visible):
        raise ResourceStateError("resource_not_visible")
    return {"resources": result}
