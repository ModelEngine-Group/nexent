# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Search, verify and confirm the resources used by a single NL2Agent draft."""

import asyncio
import hashlib
import json
import logging
from uuid import uuid4

from nexent.core.concurrency import run_blocking

from contracts.nl2agent_resources import (
    MAX_REQUIREMENTS,
    MAX_REQUIREMENTS_PER_VERIFICATION_BATCH,
    MAX_REFS_PER_REQUIREMENT_BATCH,
    BilingualSearchQueries,
    RequirementDiscoveryInput,
    RequirementEdit,
    RequirementInput,
    ResourceCardAction,
    ResourceInstallationRequest,
    ResourceInstallationAttemptRequest,
    ResourceLinkRequest,
    ResourcePurpose,
    VerificationCheck,
)
from management.services.agent import nl2agent as legacy
from services import nl2agent_semantic_retrieval as semantic
from services.nl2agent_retrieval_progress import ProgressPublisher
from services.nl2agent_state_service import (
    ResourceScope,
    ResourceState,
    ResourceStateError,
    issue_card,
    read_resource_state,
    require_current_card,
    require_current_run,
    update_resource_state,
)
from management.services.agent.nl2agent_tools import ResourceCandidate, ResourceRequirement

logger = logging.getLogger(__name__)


class VerificationBatchRetry(ResourceStateError):
    """Carry authorized feedback for retrying the current verification batch."""

    def __init__(self, code: str, result: dict):
        super().__init__(code, retryable=True)
        self.result = result


async def _progress(publisher, stage):
    await run_blocking("nl2agent-retrieval-progress", publisher.publish, stage,
                       lane="control-io", owner=__name__)


def _new_requirement(row: RequirementInput) -> dict:
    return {"query": row.query, "required": True}


def apply_requirement_edits(state: ResourceState, edits: list[RequirementEdit]) -> dict:
    """Retain results for unchanged queries and assign IDs only to new rows."""
    previous = state["requirements"]
    requirements = {}
    client_keys = {}
    next_requirement_id = state.get("next_requirement_id", 1)
    for edit in edits:
        if edit.requirement_id is not None:
            current = previous.get(edit.requirement_id)
            if current is None:
                raise ResourceStateError("unknown_requirement")
            row = _new_requirement(edit)
            legacy_gap = (
                "installed" in current and current.get("accepted") == []
                and not current.get("search_queries")
                and not current.get("linked_refs") and not current.get("repository_tool_refs")
            )
            if current["query"] == edit.query and not legacy_gap:
                row = {**current, **row}
            if current.get("linked_refs"):
                row["linked_refs"] = current["linked_refs"]
            if row.pop("needs_link_verification", False):
                for key in ("accepted", "installed", "installable"):
                    row.pop(key, None)
            requirements[edit.requirement_id] = row
        else:
            requirement_id = f"r{next_requirement_id}"
            next_requirement_id += 1
            client_keys[edit.client_key] = requirement_id
            linked = state.get("pending_links", {}).get(edit.client_key, [])
            requirements[requirement_id] = {
                **_new_requirement(edit),
                **({"linked_refs": linked} if linked else {}),
            }
    return {**state, "requirements": requirements, "client_keys": client_keys,
            "next_requirement_id": next_requirement_id,
            "pending_links": {}, "batch": None}


def _candidate(resource: dict, score: float) -> dict:
    return {
        "candidate_ref": resource["candidate_ref"],
        "resource_type": resource["resource_type"],
        "source": resource["source"],
        "name": resource["name"],
        "description": resource["description"],
        "retrieval_score": round(max(0.0, min(1.0, score)), 4),
        "capability_evidence": "installed_declaration" if resource["installed"] else "repository_declaration",
    }


def _rank(
    requirement_id: str, query: str, catalog: list[dict], *,
    search_query: str | None = None, minimum_score: float = legacy.MINIMUM_RESOURCE_SCORE,
    search_queries: dict[str, str] | None = None,
) -> list[dict]:
    # Prepared capability phrases own recall; the full request stays for verification.
    routes = dict.fromkeys(list(search_queries.values()) if search_queries else [search_query or query])
    selected: set[str] = set()
    best: dict[str, tuple[float, dict]] = {}
    catalog = list({item["candidate_ref"]: item for item in catalog}.values())
    budget = semantic.candidate_budget(len(catalog))
    for route_index, route in enumerate(routes):
        if not route:
            continue
        requirement = ResourceRequirement(requirement_id=requirement_id, query=route)
        scored = [(legacy._score_resource_requirement(requirement, resource), resource) for resource in catalog]
        scored.sort(key=lambda item: (-item[0], item[1]["candidate_ref"]))
        for score, resource in scored:
            ref = resource["candidate_ref"]
            if ref not in best or score > best[ref][0]:
                best[ref] = (score, resource)
        admitted = [(score, resource) for score, resource in scored[:budget] if score >= minimum_score]
        selected.update(resource["candidate_ref"] for score, resource in admitted)
        logger.info("event=nl2agent_text_recall requirement_id=%s route=%s catalog_size=%s "
                    "budget=%s cutoff=%.4f selected_refs=%s", requirement_id, route_index,
                    len(catalog), budget, minimum_score, [item["candidate_ref"] for _, item in admitted])
    return [_candidate(resource, score) for score, resource in sorted(
        (best[ref] for ref in selected), key=lambda item: (-item[0], item[1]["candidate_ref"]),
    )]


def _text_candidates(missing, installed, installable):
    return {key: {label: _rank(key, row["query"], group, search_query=row.get("search_query"),
                              search_queries=row.get("search_queries"))
                  for label, group in (("installed", installed), ("installable", installable))}
            for key, row in missing.items()}


def _merge_candidates(text, vectors):
    """Keep each route's ordering and score without another union cutoff."""
    refs = set()
    merged = []
    for row in [*text, *(_candidate(resource, score) for score, resource in vectors)]:
        if row["candidate_ref"] not in refs:
            merged.append(row)
            refs.add(row["candidate_ref"])
    return merged


def _next_batch(state: ResourceState) -> dict | None:
    pending = [key for key, row in state["requirements"].items() if "accepted" not in row]
    return {"id": uuid4().hex, "requirements": pending[:MAX_REQUIREMENTS_PER_VERIFICATION_BATCH]} if pending else None


def _candidates_in_batch(row: dict) -> list[dict]:
    candidates = row["installed"] + row["installable"]
    start = row.get("verification_offset", 0)
    return candidates[start:start + MAX_REFS_PER_REQUIREMENT_BATCH]


def coverage_rows(state: ResourceState) -> list[dict]:
    rows = []
    for requirement_id, row in state["requirements"].items():
        accepted = set(row.get("accepted", []))
        installed = [item for item in row.get("installed", []) if item["candidate_ref"] in accepted]
        installed = sorted(installed, key=lambda item: (-item.get("retrieval_score", -1), item["candidate_ref"]))
        installable = sorted(
            [item for item in row.get("installable", []) if item["candidate_ref"] in accepted],
            key=lambda item: (-item.get("retrieval_score", -1), item["candidate_ref"]),
        )
        status = "covered" if installed else "installable" if installable else "uncovered"
        rows.append({
            "requirement_id": requirement_id,
            "query": row["query"],
            **({"search_queries": row["search_queries"]} if row.get("search_queries") else {}),
            "required": True,
            "coverage_status": status,
            "covered_resources": installed,
            "installable_resources": [] if installed else installable,
        })
    return rows


def _batch_result(state: ResourceState) -> dict:
    batch = state["batch"]
    if batch is None:
        return {"status": "success", "requirements": coverage_rows(state), "verification_batch_id": None}
    return {
        "status": "success",
        "next_step": "verify_resources",
        "verification_batch_id": batch["id"],
        "requirements": [
            {
                "requirement_id": key,
                "query": state["requirements"][key]["query"],
                **({"verification_policy": "all_qualified"}
                   if state["requirements"][key].get("verification_policy") == "all_qualified" else {}),
                "installed_candidates": [
                    item for item in _candidates_in_batch(state["requirements"][key])
                    if item["capability_evidence"] == "installed_declaration"
                ],
                "installable_candidates": [
                    item for item in _candidates_in_batch(state["requirements"][key])
                    if item["capability_evidence"] == "repository_declaration"
                ],
            }
            for key in batch["requirements"]
        ],
    }


async def _authorized_batch_result(
    scope: ResourceScope, state: ResourceState, *, catalogs: dict[str, list[dict]] | None = None,
) -> dict:
    """Cached batches must pass current source authorization before disclosure."""
    result = _batch_result(state)
    rows = [item for row in result["requirements"]
            for field in ("installed_candidates", "installable_candidates",
                          "covered_resources", "installable_resources")
            for item in row.get(field, [])]
    if not rows:
        return result
    identity = {"tenant_id": scope.tenant_id, "user_id": scope.user_id}
    # Reuse only source reads from this call; callers must not retain catalogs across stages.
    if catalogs is None:
        catalogs = {}
    actual = []
    if any(row["capability_evidence"] == "installed_declaration" for row in rows):
        if "installed" not in catalogs:
            catalogs["installed"] = await legacy._load_installed_resource_catalog(**identity)
        actual.extend(catalogs["installed"])
    if any(row["capability_evidence"] == "repository_declaration" for row in rows):
        if "installable" not in catalogs:
            catalogs["installable"] = await legacy._load_internal_uninstalled_resource_catalog(**identity)
        actual.extend(catalogs["installable"])
    latest = {row["candidate_ref"]: row for row in actual}
    revisions = {}
    for row in state["requirements"].values():
        for ref, revision in row.get("resource_revisions", {}).items():
            revisions.setdefault(ref, set()).add(revision)
    if any(item["candidate_ref"] not in latest or
           _candidate(latest[item["candidate_ref"]], item["retrieval_score"]) != item or
           (item["candidate_ref"] in revisions and
            {semantic.resource_revision(latest[item["candidate_ref"]])} != revisions[item["candidate_ref"]])
           for item in rows):
        raise ResourceStateError("resource_evidence_changed", retryable=True)
    return result


async def discover(
    scope: ResourceScope, requirements: list[RequirementDiscoveryInput] | None, purpose: ResourcePurpose,
    search_queries: dict[str, BilingualSearchQueries | dict[str, str]] | None = None,
) -> dict:
    if requirements is not None and search_queries is not None:
        raise ResourceStateError("invalid_search_queries")
    if requirements is not None:
        def begin(previous):
            if previous and previous["run_id"] == scope.run_id:
                raise ResourceStateError("resource_discovery_already_started")
            return {
                "version": (previous["version"] if previous else 0) + 1,
                "conversation_id": scope.conversation_id, "run_id": scope.run_id, "purpose": purpose,
                "requirements": {
                    f"r{index}": {
                        **_new_requirement(row),
                        **({"search_query": row.search_query} if row.search_query else {}),
                        **({"search_queries": row.search_queries.model_dump()} if row.search_queries else {}),
                    }
                    for index, row in enumerate(requirements, 1)
                },
                "next_requirement_id": len(requirements) + 1,
                "card": None, "batch": None,
                "installation_attempts": previous.get("installation_attempts", {}) if previous else {},
            }

        state = await update_resource_state(scope, begin)
    else:
        state = require_current_run(await read_resource_state(scope), scope)
    if state["card"] is not None:
        raise ResourceStateError("resource_card_waiting")
    if search_queries is not None:
        def enrich(current):
            current = require_current_run(current, scope)
            if current["card"] is not None:
                raise ResourceStateError("resource_card_waiting")
            rows = {**current["requirements"]}
            for key, pair in search_queries.items():
                pair = BilingualSearchQueries.model_validate(pair).model_dump()
                row = rows.get(key)
                if row is None or (row.get("search_queries") != pair and (
                    "installed" in row or row.get("search_queries") is not None
                )):
                    raise ResourceStateError("invalid_search_queries")
                rows[key] = {**row, "search_queries": pair}
            return {**current, "requirements": rows}

        state = await update_resource_state(scope, enrich)
    missing = {
        key: row for key, row in state["requirements"].items() if "installed" not in row
    }
    if not missing:
        return await _authorized_batch_result(scope, state)
    untranslated = [
        {"requirement_id": key, "query": row["query"]} for key, row in missing.items()
        if not row.get("search_queries") and not row.get("linked_refs") and not row.get("repository_tool_refs")
    ]
    if untranslated:
        return {"status": "success", "next_step": "prepare_search_queries", "requirements": untranslated}
    publisher = ProgressPublisher(scope)
    model = None
    try:
        if state.get("embedding_fallback_run_id") != scope.run_id:
            model = await semantic.resolve_model(scope.tenant_id)
    except Exception as exc:
        logger.warning("NL2Agent embedding resolution failed; using text retrieval (%s)", type(exc).__name__)
        await update_resource_state(scope, lambda current: {
            **require_current_run(current, scope), "embedding_fallback_run_id": scope.run_id,
        })
        # Resolution failure does not prove that semantic retrieval was configured.
        await _progress(publisher, "searching_text")
    identity = {"tenant_id": scope.tenant_id, "user_id": scope.user_id}
    installed, installable = await asyncio.gather(
        legacy._load_installed_resource_catalog(**identity),
        legacy._load_internal_uninstalled_resource_catalog(**identity),
    )
    original_revisions = {item["candidate_ref"]: semantic._text(item)
                          for item in [*installed, *installable]}
    semantic_results = None
    await _progress(publisher, "searching_hybrid" if model is not None else "searching_text")
    text_task = asyncio.create_task(run_blocking(
        "nl2agent-text-retrieval", _text_candidates, missing, installed, installable, owner=__name__))
    if model is not None:
        try:
            semantic_results = await semantic.retrieve(scope.tenant_id, model,
                {key: row.get("search_queries") or row["query"] for key, row in missing.items()},
                installed, installable, publisher.publish)
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                logger.warning("event=nl2agent_semantic_timeout phase=%s threshold_seconds=%s "
                               "exception_type=%s", getattr(exc, "phase", "retrieval"),
                               getattr(exc, "threshold_seconds", semantic.RETRIEVAL_TIMEOUT),
                               type(exc).__name__)
            else:
                logger.warning("NL2Agent semantic retrieval failed; using text retrieval (%s)", type(exc).__name__)
            await update_resource_state(scope, lambda current: {
                **require_current_run(current, scope), "embedding_fallback_run_id": scope.run_id,
            })
            await _progress(publisher, "fallback_to_text")
        except BaseException:
            text_task.cancel()
            await asyncio.gather(text_task, return_exceptions=True)
            raise
    text_results = await text_task
    # Sources, not the search index, authorize disclosure after awaited work.
    current_installed, current_installable = await asyncio.gather(
        legacy._load_installed_resource_catalog(**identity),
        legacy._load_internal_uninstalled_resource_catalog(**identity),
    )
    current_groups = {"installed": current_installed, "installable": current_installable}
    for label, current in current_groups.items():
        allowed = {item["candidate_ref"]: item for item in current
                   if original_revisions.get(item["candidate_ref"]) == semantic._text(item)}
        for key in missing:
            if any(item["candidate_ref"] not in allowed for item in text_results[key][label]):
                raise ResourceStateError("resource_evidence_changed", retryable=True)
            if semantic_results is not None and any(
                    item["candidate_ref"] not in allowed for _, item in semantic_results[key][label]):
                raise ResourceStateError("resource_evidence_changed", retryable=True)
            text_results[key][label] = [item for item in text_results[key][label]
                                        if item["candidate_ref"] in allowed]
            if semantic_results is not None:
                semantic_results[key][label] = [(score, allowed[item["candidate_ref"]])
                    for score, item in semantic_results[key][label] if item["candidate_ref"] in allowed]
    installed = [item for item in current_installed
                 if original_revisions.get(item["candidate_ref"]) == semantic._text(item)]
    installable = [item for item in current_installable
                   if original_revisions.get(item["candidate_ref"]) == semantic._text(item)]
    if semantic_results is None:
        await _progress(publisher, "searching_text")
    ranked = {
        key: {
            **row,
            "installed": _merge_candidates(text_results[key]["installed"],
                                            semantic_results[key]["installed"] if semantic_results else []),
            "installable": _merge_candidates(text_results[key]["installable"],
                                              semantic_results[key]["installable"] if semantic_results else []),
            "retrieval_method": "hybrid" if semantic_results is not None else "text",
            "verification_policy": "all_qualified",
            "retrieval_evidence": {
                label: {"text_refs": [item["candidate_ref"] for item in text_results[key][label]],
                        "semantic_refs": [item["candidate_ref"] for _, item in semantic_results[key][label]]
                        if semantic_results is not None else []}
                for label in ("installed", "installable")
            },
        }
        for key, row in missing.items()
    }
    for key, row in ranked.items():
        linked_refs = set(row.get("linked_refs", []))
        repository_refs = row.pop("repository_tool_refs", [])
        priority_refs = linked_refs.union(repository_refs)
        search_query = row.get("search_query")
        requirement = ResourceRequirement(
            requirement_id=key, query=row["query"], search_terms=[search_query] if search_query else [],
        )
        linked_candidates = [
            _candidate(item, legacy._score_resource_requirement(requirement, item))
            for item in installed if item["candidate_ref"] in priority_refs
        ]
        row["installed"] = linked_candidates + [
            item for item in row["installed"] if item["candidate_ref"] not in priority_refs
        ]
        candidate_refs = {item["candidate_ref"] for label in ("installed", "installable") for item in row[label]}
        row["resource_revisions"] = {
            item["candidate_ref"]: semantic.resource_revision(item)
            for item in [*installed, *installable] if item["candidate_ref"] in candidate_refs
        }

    for row in ranked.values():
        row.pop("knowledge_validation", None)
        row.pop("knowledge_preference", None)
        row.pop("source_preference", None)

    def store(current):
        current = require_current_run(current, scope)
        if current["version"] != state["version"]:
            raise ResourceStateError("resource_state_conflict")
        if current["batch"] is not None:
            return current
        updated = {**current, "requirements": {**current["requirements"], **ranked}}
        return {**updated, "batch": _next_batch(updated)}

    result = await _authorized_batch_result(scope, await update_resource_state(scope, store), catalogs={
        "installed": current_installed, "installable": current_installable,
    })
    await _progress(publisher, "verifying_capabilities")
    return result


def validate_checks(state: ResourceState, batch_id: str, checks: list[VerificationCheck]) -> dict:
    batch = state["batch"]
    if batch is None or batch["id"] != batch_id:
        raise ResourceStateError("verification_batch_stale")
    by_id = {check.requirement_id: check for check in checks}
    if len(by_id) != len(checks) or set(by_id) != set(batch["requirements"]):
        raise ResourceStateError("verification_requirements_incomplete")
    accepted = {}
    for key, check in by_id.items():
        row = state["requirements"][key]
        expected = {item["candidate_ref"] for item in _candidates_in_batch(row)}
        if check.checked is not None and (set(check.checked) != expected or len(check.checked) != len(expected)):
            raise ResourceStateError("verification_candidates_incomplete")
        if len(set(check.accepted)) != len(check.accepted) or not set(check.accepted) <= expected:
            raise ResourceStateError("invalid_verified_candidate")
        if check.assessments is None:
            if row.get("verification_policy") == "all_qualified":
                raise ResourceStateError("verification_assessments_required", retryable=True)
        else:
            refs = [item.candidate_ref for item in check.assessments]
            if len(refs) != len(set(refs)) or set(refs) != expected:
                raise ResourceStateError("verification_assessments_incomplete", retryable=True)
            positive = {item.candidate_ref for item in check.assessments if item.satisfies}
            if set(check.accepted) != positive:
                raise ResourceStateError("verification_acceptance_mismatch", retryable=True)
        accepted[key] = check.accepted
    return accepted


def _verification_signature(checks: list[VerificationCheck], offered_refs: dict[str, list[str]]) -> list:
    signature = []
    for check in checks:
        entry = [check.requirement_id,
                 sorted(offered_refs.get(check.requirement_id, []) if check.checked is None else check.checked),
                 sorted(check.accepted)]
        if check.assessments is not None:
            entry.append([[item.candidate_ref, item.satisfies, item.reason] for item in sorted(
                check.assessments, key=lambda item: item.candidate_ref)])
        signature.append(entry)
    return sorted(signature)


async def _verification_retry_feedback(
    scope: ResourceScope, state: ResourceState, checks: list[VerificationCheck],
) -> dict:
    result = await _authorized_batch_result(scope, state)
    submitted = {
        check.requirement_id: {assessment.candidate_ref for assessment in check.assessments or []}
        for check in checks
    }
    missing = []
    for row in result["requirements"]:
        requirement_id = row["requirement_id"]
        expected = {
            candidate["candidate_ref"]
            for candidate in row["installed_candidates"] + row["installable_candidates"]
        }
        omitted = sorted(expected - submitted.get(requirement_id, set()))
        if omitted or requirement_id not in submitted:
            missing.append({"requirement_id": requirement_id, "missing_candidate_refs": omitted})
    return {
        **result,
        "missing_assessments": missing,
        "retry_instruction": (
            "Call nl2a_verify_requirements again with this verification_batch_id. Resubmit all requirements in "
            "this batch, keep valid assessments, and add one assessment for each missing candidate under its "
            "requirement_id, including uninstalled and non-matching candidates. Use each current candidate_ref "
            "exactly once and set accepted to exactly the refs whose satisfies value is true."
        ),
    }


async def verify(scope: ResourceScope, batch_id: str, checks: list[VerificationCheck]) -> dict:
    snapshot = require_current_run(await read_resource_state(scope), scope)
    previous = snapshot.get("submitted_batches", {}).get(batch_id)
    if previous is not None:
        if previous != _verification_signature(checks, {entry[0]: entry[1] for entry in previous}):
            raise ResourceStateError("verification_batch_conflict")
        return await _authorized_batch_result(scope, snapshot)
    try:
        accepted = validate_checks(snapshot, batch_id, checks)
    except ResourceStateError as error:
        if error.code not in {
            "verification_requirements_incomplete", "verification_assessments_required",
            "verification_assessments_incomplete", "invalid_verified_candidate",
        }:
            raise
        feedback = await _verification_retry_feedback(scope, snapshot, checks)
        raise VerificationBatchRetry(error.code, feedback) from error
    signature = _verification_signature(checks, {
        key: [item["candidate_ref"] for item in _candidates_in_batch(snapshot["requirements"][key])]
        for key in accepted
    })
    selected = {
        item["candidate_ref"]: item
        for key, refs in accepted.items()
        for item in snapshot["requirements"][key]["installed"] + snapshot["requirements"][key]["installable"]
        if item["candidate_ref"] in refs
    }
    identity = {"tenant_id": scope.tenant_id, "user_id": scope.user_id}
    catalogs = {}
    actual = []
    if any(item["capability_evidence"] == "installed_declaration" for item in selected.values()):
        catalogs["installed"] = await legacy._load_installed_resource_catalog(**identity)
        actual.extend(catalogs["installed"])
    if any(item["capability_evidence"] == "repository_declaration" for item in selected.values()):
        catalogs["installable"] = await legacy._load_internal_uninstalled_resource_catalog(**identity)
        actual.extend(catalogs["installable"])
    latest = {item["candidate_ref"]: item for item in actual}
    if any(
        ref not in latest or _candidate(latest[ref], old["retrieval_score"]) != old
        for ref, old in selected.items()
    ):
        raise ResourceStateError("resource_evidence_changed", retryable=True)

    def store(current):
        state = require_current_run(current, scope)
        previous_result = state.get("submitted_batches", {}).get(batch_id)
        if previous_result is not None:
            if previous_result != signature:
                raise ResourceStateError("verification_batch_conflict")
            return state
        results = validate_checks(state, batch_id, checks)
        assessments = {check.requirement_id: check.assessments for check in checks}
        requirements = {**state["requirements"]}
        for key, refs in results.items():
            row = {**requirements[key]}
            row.pop("knowledge_validation", None)
            row.pop("knowledge_preference", None)
            row.pop("source_preference", None)
            if assessments[key] is not None:
                row["candidate_assessments"] = {
                    **row.get("candidate_assessments", {}),
                    **{item.candidate_ref: {"satisfies": item.satisfies, "reason": item.reason}
                       for item in assessments[key]},
                }
            all_accepted = [*row.get("partial_accepted", []), *refs]
            offset = row.get("verification_offset", 0) + len(_candidates_in_batch(row))
            if offset >= len(row["installed"]) + len(row["installable"]):
                row["accepted"] = all_accepted
                row.pop("partial_accepted", None)
                row.pop("verification_offset", None)
            else:
                row["partial_accepted"] = all_accepted
                row["verification_offset"] = offset
            requirements[key] = row
        updated = {**state, "requirements": requirements,
                   "submitted_batches": {**state.get("submitted_batches", {}), batch_id: signature}}
        return {**updated, "batch": _next_batch(updated)}

    return await _authorized_batch_result(scope, await update_resource_state(scope, store), catalogs=catalogs)


async def _visible_repository_mcps(scope: ResourceScope, refs: set[str]) -> dict[str, list[dict]]:
    if not refs:
        return {}

    from management.services.mcp.service import list_visible_mcp_records
    from nexent.core.concurrency import run_blocking

    records, _ = await run_blocking(
        "nl2agent-visible-mcps", list_visible_mcp_records, scope.tenant_id, scope.user_id,
        lane="control-io", owner="services.nl2agent_resource_flow",
    )
    matched = {}
    for record in records:
        ref = f'tenant_mcp_repository:{record.get("market_id")}'
        if ref in refs:
            matched.setdefault(ref, []).append(record)
    return matched


async def _repository_mcp_installation_status(scope: ResourceScope, candidates: list[dict]) -> dict[str, str]:
    refs = {candidate["candidate_ref"] for candidate in candidates if candidate["source"] == "TENANT_MCP_REPOSITORY"}
    records = await _visible_repository_mcps(scope, refs)
    return {
        ref: "installed" if any(record.get("enabled") for record in group) else "disabled"
        for ref, group in records.items()
    }


async def _repository_tools_to_recheck(
    scope: ResourceScope, state: ResourceState, edits: list[RequirementEdit],
) -> dict[str, list[str]]:
    """Resume coverage for unchanged rows when actual tools from a verified MCP appear."""
    retained = {edit.requirement_id: edit.query for edit in edits}
    refs_by_requirement = {
        row["requirement_id"]: [
            item["candidate_ref"] for item in row["installable_resources"]
            if item["source"] == "TENANT_MCP_REPOSITORY"
        ]
        for row in coverage_rows(state)
        if retained.get(row["requirement_id"]) == row["query"]
    }
    records = await _visible_repository_mcps(scope, {ref for refs in refs_by_requirement.values() for ref in refs})
    enabled_names = {
        ref: {record["mcp_name"] for record in group if record.get("enabled") and record.get("mcp_name")}
        for ref, group in records.items()
    }
    if not any(enabled_names.values()):
        return {}
    catalog = await legacy._load_installed_resource_catalog(tenant_id=scope.tenant_id, user_id=scope.user_id)
    rechecks = {}
    for key, refs in refs_by_requirement.items():
        names = {name for ref in refs for name in enabled_names.get(ref, ())}
        row = state["requirements"][key]
        tools = [
            item for item in catalog
            if item["source"] == "MCP_TOOL" and item.get("mcp_service_name") in names
        ]
        candidates = _rank(key, row["query"], tools, search_query=row.get("search_query"), minimum_score=0,
                           search_queries=row.get("search_queries"))
        preferred = [item["candidate_ref"] for item in candidates]
        previous = {item["candidate_ref"] for item in row.get("installed", [])}
        if any(ref not in previous for ref in preferred):
            rechecks[key] = preferred
    return rechecks


def card_payload(scope: ResourceScope, state: ResourceState, rows: list[dict] | None = None) -> dict:
    return {
        "protocol_version": 2, "agent_id": scope.agent_id, "conversation_id": scope.conversation_id,
        "run_id": state["run_id"], "subtype": state["card"]["subtype"], "purpose": state["purpose"],
        "card_id": state["card"]["id"], "state_version": state["version"],
        **({"previous_card_id": state["previous_card_id"]} if state.get("previous_card_id") else {}),
        "requirements": coverage_rows(state) if rows is None else rows,
    }


async def show_card(scope: ResourceScope) -> dict | None:
    state = require_current_run(await read_resource_state(scope), scope)
    if state["batch"]:
        raise VerificationBatchRetry("verification_incomplete", await _authorized_batch_result(scope, state))
    if any("accepted" not in row for row in state["requirements"].values()):
        raise ResourceStateError("verification_incomplete")
    catalogs = {}
    await _authorized_batch_result(scope, state, catalogs=catalogs)
    rows = coverage_rows(state)
    if not rows and state["purpose"] != "recommend":
        return None
    subtype = "requirement_resources"
    statuses = await _repository_mcp_installation_status(
        scope, [item for row in rows for item in row["installable_resources"]],
    )
    for row in rows:
        row["installable_resources"] = [
            {**item, "installation_status": statuses[item["candidate_ref"]]}
            if item["candidate_ref"] in statuses else item
            for item in row["installable_resources"]
        ]

    resources = []
    if rows:
        candidates: dict[str, ResourceCandidate] = {}
        recommended = set()
        for row in rows:
            if row["covered_resources"]:
                recommended.add(row["covered_resources"][0]["candidate_ref"])
            for item in row["covered_resources"]:
                ref = item["candidate_ref"]
                if ref in candidates:
                    candidates[ref].requirement_ids.append(row["requirement_id"])
                else:
                    candidates[ref] = ResourceCandidate(
                        candidate_ref=ref, resource_type=item["resource_type"], source=item["source"],
                        name=item["name"], description=item["description"],
                        requirement_ids=[row["requirement_id"]], score=item["retrieval_score"],
                        knowledge_queries=[row["query"]],
                    )
        if candidates:
            binding_facts = {}
            output = await legacy.recommend_installed_resources_impl(
                agent_id=scope.agent_id, candidates=list(candidates.values()), recommended_refs=list(recommended),
                tenant_id=scope.tenant_id, user_id=scope.user_id,
                include_knowledge_recommendations=False,
                catalog=catalogs["installed"], binding_facts=binding_facts,
            )
            resources = [
                {
                    **resource.model_dump(mode="json", exclude={"installation_options", "default_option_id"}),
                    **binding_facts.get(resource.candidate.candidate_ref, {}),
                    "config": [], "has_config": bool(resource.config),
                    "configuration_revision": hashlib.sha256(json.dumps([{k: v for k, v in param.items() if k not in {"value", "default"}} for param in resource.config], sort_keys=True).encode()).hexdigest(),
                }
                for resource in output.resources
            ]

    def publish(current):
        current = require_current_run(current, scope)
        if current["version"] != state["version"] or current["card"] is not None:
            raise ResourceStateError("resource_state_conflict")
        return issue_card(current, subtype)

    updated = await update_resource_state(scope, publish)
    return {**card_payload(scope, updated, rows), "resources": resources}


async def apply_card_action(
    scope: ResourceScope, subtype: str, action: str, data: ResourceCardAction, *, resume_confirmation: bool = False,
    validate_only: bool = False,
) -> dict:
    if subtype != "requirement_resources":
        raise ResourceStateError("resource_card_stale")
    if action == "return_requirements":
        raise ResourceStateError("invalid_resource_action")
    if action in {"continue", "retry_generation"}:
        current_state = await read_resource_state(scope)
        if current_state and current_state.get("purpose") == "recommend":
            raise ResourceStateError("invalid_resource_action")
    if subtype == "requirement_resources" and action == "retry_generation":
        def retry(current):
            if not current or current["conversation_id"] != scope.conversation_id or current["card"] is not None:
                raise ResourceStateError("resource_card_stale")
            if current.get("continuation") != {"id": data.card_id, "version": data.state_version}:
                raise ResourceStateError("resource_card_stale")
            return {**current, "run_id": scope.run_id}

        if validate_only:
            retry(await read_resource_state(scope))
            return {"validated": True}
        updated = await update_resource_state(scope, retry)
        return {"purpose": updated["purpose"], "action": "continue", "retry_prompt": True,
                "confirmed_requirements": updated.get("confirmed_requirements", [])}
    state = await read_resource_state(scope)
    if (
        resume_confirmation and action == "confirm_requirements"
        and subtype == "requirement_resources"
        and state and state["card"] is None
    ):
        def resume(current):
            # The creator has already matched the exact retry to the most recent failed turn.
            if (not current or current["conversation_id"] != scope.conversation_id
                    or current["version"] != data.state_version + 1 or current["card"] is not None):
                raise ResourceStateError("resource_card_stale")
            return {**current, "run_id": scope.run_id}

        if validate_only:
            resume(state)
            return {"validated": True}
        updated = await update_resource_state(scope, resume)
        return await _continue_confirmed_requirements(scope, updated, action)

    state = require_current_card(state, scope, subtype, data)
    repository_rechecks = (
        await _repository_tools_to_recheck(scope, state, data.requirements)
        if action == "confirm_requirements" and data.requirements else {}
    )
    if subtype == "requirement_resources" and action == "continue":
        await _authorized_batch_result(scope, state)
        if any("accepted" not in row or row.get("needs_link_verification") for row in state["requirements"].values()):
            raise ResourceStateError("verification_incomplete")
        if data.selected_resource_refs is None:
            raise ResourceStateError("invalid_resource_action")
        rows = coverage_rows(state)
        allowed = {item["candidate_ref"] for row in rows for item in row["covered_resources"]}
        _, bound = await legacy._load_verified_nl2agent_state(
            agent_id=scope.agent_id, tenant_id=scope.tenant_id, user_id=scope.user_id,
        )
        actual = {f'{item["resource_type"]}:{item["resource_id"]}' for item in bound}
        confirmed_requirements = [
            {"query": row["query"], "required": row["required"],
             "bound": any(item["candidate_ref"] in actual for item in row["covered_resources"])}
            for row in rows
        ]
        selected = set(data.selected_resource_refs)
        if not selected <= allowed or not selected <= actual:
            raise ResourceStateError("binding_not_ready")
        if any(not row["bound"] for row in confirmed_requirements):
            raise ResourceStateError("required_resource_not_bound")

    def accept(current):
        current = require_current_card(current, scope, subtype, data)
        current = {**current, "run_id": scope.run_id}
        if subtype == "requirement_resources" and action == "confirm_requirements":
            if data.requirements is None:
                raise ResourceStateError("invalid_resource_action")
            current = apply_requirement_edits(current, data.requirements)
            for key, refs in repository_rechecks.items():
                row = current["requirements"][key]
                row["repository_tool_refs"] = refs
                for field in ("accepted", "installed", "installable"):
                    row.pop(field, None)
        elif subtype == "requirement_resources" and action == "use_recommendation":
            if current["purpose"] != "recommend":
                raise ResourceStateError("invalid_resource_action")
            current = {**current, "purpose": "bind"}
        elif subtype == "requirement_resources" and action == "continue":
            current = {**current, "continuation": {"id": data.card_id, "version": data.state_version},
                       "confirmed_requirements": confirmed_requirements}
        elif action != "continue":
            raise ResourceStateError("invalid_resource_action")
        return {**current, "previous_card_id": data.card_id, "card": None, "submitted_batches": {}, "version": current["version"] + 1}

    if validate_only:
        accept(state)
        return {"validated": True}
    updated = await update_resource_state(scope, accept)
    if action in {"confirm_requirements", "use_recommendation"}:
        return await _continue_confirmed_requirements(scope, updated, action)
    return {"purpose": updated["purpose"], "action": action,
            **({"confirmed_requirements": updated["confirmed_requirements"]} if action == "continue" else {})}


async def _continue_confirmed_requirements(scope: ResourceScope, state: ResourceState, action: str) -> dict:
    if any("accepted" not in row for row in state["requirements"].values()):
        return {"purpose": state["purpose"], "action": action, "next_step": "verify_resources"}
    card = await show_card(scope)
    if card is not None:
        return {"card": card}
    if state["purpose"] == "generate":
        return {"purpose": "generate", "action": action, "confirmed_requirements": [],
                "next_step": "generate_prompt"}
    return {"purpose": state["purpose"], "action": action}


def _installable_candidate(state: ResourceState, requirement_id: str, candidate_ref: str) -> dict:
    for row in coverage_rows(state):
        if row["requirement_id"] != requirement_id:
            continue
        for candidate in row["installable_resources"]:
            if candidate["candidate_ref"] == candidate_ref:
                return candidate
    raise ResourceStateError("resource_not_available_for_installation")


async def installation_details(scope: ResourceScope, request: ResourceInstallationRequest) -> dict:
    state = require_current_card(await read_resource_state(scope), scope, "requirement_resources", request)
    if state["purpose"] == "recommend":
        raise ResourceStateError("invalid_resource_action")
    candidate = _installable_candidate(state, request.requirement_id, request.candidate_ref)
    statuses = await _repository_mcp_installation_status(scope, [candidate])
    if status := statuses.get(request.candidate_ref):
        return {"subtype": "suggested_resource_installation", "agent_id": scope.agent_id,
                "resources": [], "installation_status": status}
    result = await legacy.recommend_uninstalled_resources_impl(
        candidates=[ResourceCandidate(
            candidate_ref=candidate["candidate_ref"], resource_type=candidate["resource_type"],
            source=candidate["source"], name=candidate["name"], description=candidate["description"],
            requirement_ids=[request.requirement_id], score=candidate["retrieval_score"],
        )],
        recommended_refs=[request.candidate_ref],
        tenant_id=scope.tenant_id, user_id=scope.user_id,
    )
    return {"subtype": "suggested_resource_installation", "agent_id": scope.agent_id,
            "resources": [resource.model_dump(mode="json") for resource in result.resources]}


def _lookup_installation(scope: ResourceScope, candidate: dict, target_name: str) -> dict | None:
    source = candidate["source"]
    if source == "NEXENT_OFFICIAL_SKILL":
        from management.services.skill.transfer import get_official_skills_with_status

        for row in get_official_skills_with_status(tenant_id=scope.tenant_id):
            if row.get("name") == target_name and row.get("status") == "installed" and row.get("skill_id"):
                return {"resource_type": "skill", "resource_id": row["skill_id"]}
        return None
    if source == "TENANT_SKILL_REPOSITORY":
        from management.db.skill.repository import get_skill_by_name

        row = get_skill_by_name(target_name, scope.tenant_id)
        if row is None:
            return None
        if row.get("source") == "repository" and row.get("created_by") == scope.user_id:
            return {"resource_type": "skill", "resource_id": row["skill_id"]}
    else:
        from management.db.mcp.remote import get_mcp_records_by_tenant

        rows = get_mcp_records_by_tenant(scope.tenant_id)
        row = next((item for item in rows if item.get("mcp_name") == target_name), None)
        if row is None:
            return None
        market_id = int(candidate["candidate_ref"].split(":", 1)[1])
        if row.get("market_id") == market_id and row.get("created_by") == scope.user_id:
            return {"resource_type": "mcp_server", "resource_id": row["mcp_id"]}
    raise ResourceStateError("installation_name_conflict")


async def installation_attempt(scope: ResourceScope, request: ResourceInstallationAttemptRequest) -> dict:
    """Only the first authorized claim can start a write. Recovery is read-only."""
    from nexent.core.concurrency import run_blocking

    state = require_current_card(await read_resource_state(scope), scope, "requirement_resources", request)
    candidate = _installable_candidate(state, request.requirement_id, request.candidate_ref)
    key = request.candidate_ref
    previous = state.get("installation_attempts", {}).get(key)
    if previous is None and request.operation != "claim":
        return {"status": "not_started"}
    if previous:
        target_name = previous["target_name"]
    elif candidate["source"] == "NEXENT_OFFICIAL_SKILL":
        target_name = candidate["name"]
    else:
        suffix = hashlib.sha256(f"{scope.key}:{key}".encode()).hexdigest()[:12]
        target_name = request.target_name or f"nl2a-{suffix}"
    result = await run_blocking(
        "nl2agent-installation-lookup", _lookup_installation, scope, candidate, target_name,
        lane="control-io", owner="services.nl2agent_resource_flow",
    )
    if result:
        if previous is None and candidate["source"] != "NEXENT_OFFICIAL_SKILL" and request.target_name:
            raise ResourceStateError("installation_name_conflict")
        return {"status": "installed", **result}
    if previous and request.operation != "release":
        return {"status": "pending", "target_name": target_name}
    claim_id = uuid4().hex

    def reserve(current):
        current = require_current_card(current, scope, "requirement_resources", request)
        attempts = dict(current.get("installation_attempts", {}))
        existing = attempts.get(key)
        if request.operation == "release":
            if existing and existing["attempt_id"] == request.attempt_id:
                attempts.pop(key)
        elif existing is None:
            attempts[key] = {"target_name": target_name, "attempt_id": claim_id}
        return {**current, "installation_attempts": attempts}

    updated = await update_resource_state(scope, reserve)
    attempt = updated["installation_attempts"].get(key)
    if attempt is None:
        return {"status": "not_started"}
    if attempt["attempt_id"] != claim_id:
        return {"status": "pending", "target_name": attempt["target_name"]}
    return {"status": "claimed", **attempt}


async def link_installed_resource(scope: ResourceScope, request: ResourceLinkRequest) -> None:
    from nexent.core.concurrency import run_blocking

    def validate_target(current):
        subtype = (current.get("card") or {}).get("subtype") if current else None
        if subtype != "requirement_resources":
            raise ResourceStateError("resource_card_stale")
        current = require_current_card(current, scope, subtype, request)
        if current["purpose"] == "recommend":
            raise ResourceStateError("invalid_resource_action")
        if request.requirement_id is not None and request.requirement_id not in current["requirements"]:
            raise ResourceStateError("unknown_requirement")
        if request.candidate_ref is not None:
            candidate = _installable_candidate(current, request.requirement_id, request.candidate_ref)
            if candidate["resource_type"] != request.resource_type:
                raise ResourceStateError("invalid_resource_link")
        return current

    state = validate_target(await read_resource_state(scope))
    if request.candidate_ref is not None:
        candidate = _installable_candidate(state, request.requirement_id, request.candidate_ref)
        attempt = state.get("installation_attempts", {}).get(request.candidate_ref)
        target_name = attempt["target_name"] if attempt else candidate["name"]
        if attempt is None and candidate["source"] != "NEXENT_OFFICIAL_SKILL":
            raise ResourceStateError("invalid_resource_link")
        actual = await run_blocking(
            "nl2agent-linked-installation", _lookup_installation, scope, candidate, target_name,
            lane="control-io", owner="services.nl2agent_resource_flow",
        )
        if actual is None:
            raise ResourceStateError("installed_resource_not_visible", retryable=True)
        if actual["resource_id"] != request.resource_id:
            raise ResourceStateError("invalid_resource_link")
    installed = await legacy._load_installed_resource_catalog(tenant_id=scope.tenant_id, user_id=scope.user_id)
    if request.resource_type == "mcp_server":
        from management.db.mcp.remote import get_mcp_record_by_id_and_tenant

        mcp = await run_blocking(
            "nl2agent-linked-mcp", get_mcp_record_by_id_and_tenant, request.resource_id, scope.tenant_id,
            lane="control-io", owner="services.nl2agent_resource_flow",
        )
        service_name = mcp.get("mcp_name") if mcp and mcp.get("created_by") == scope.user_id else None
        linked = [
            item["candidate_ref"] for item in installed
            if service_name and item["source"] == "MCP_TOOL" and item.get("mcp_service_name") == service_name
        ]
        config = mcp.get("config_json") if service_name else None
        if isinstance(config, dict) and "openapi" in config:
            from management.db.tool.outer_api import query_available_openapi_services

            services = await run_blocking(
                "nl2agent-openapi-services", query_available_openapi_services, scope.tenant_id,
                lane="control-io", owner="services.nl2agent_resource_flow",
            )
            namespace = f"{service_name}_"
            other_namespaces = tuple(f"{row['mcp_service_name']}_" for row in services
                                     if str(row["mcp_service_name"]).startswith(namespace))
            for item in installed:
                if item["source"] == "MCP_TOOL" and item.get("mcp_service_name") == "outer-apis":
                    origin = item["names"][-1]
                    if origin.startswith(namespace) and not origin.startswith(other_namespaces):
                        linked.append(item["candidate_ref"])
    else:
        ref = f"{request.resource_type}:{request.resource_id}"
        linked = [ref] if any(item["candidate_ref"] == ref for item in installed) else []
    if not linked:
        raise ResourceStateError("installed_resource_not_visible", retryable=True)

    def store(current):
        current = validate_target(current)
        if request.client_key is not None:
            pending = dict(current.get("pending_links", {}))
            if request.client_key not in pending and len(pending) >= MAX_REQUIREMENTS:
                raise ResourceStateError("requirements_limit_exceeded")
            pending[request.client_key] = list(dict.fromkeys([*pending.get(request.client_key, []), *linked]))
            return {**current, "pending_links": pending}
        requirements = {**current["requirements"]}
        row = {**requirements[request.requirement_id]}
        row["linked_refs"] = list(dict.fromkeys([*row.get("linked_refs", []), *linked]))
        row["needs_link_verification"] = True
        requirements[request.requirement_id] = row
        return {**current, "requirements": requirements}

    await update_resource_state(scope, store)
