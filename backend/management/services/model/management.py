# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from typing import Any, Dict, List, Optional

from nexent.core.models.sampling import resolve_sampling

from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.model import ModelConnectStatusEnum
from contracts.model_names import add_repo_to_name
from infrastructure.rdb.model_records import get_created_model_ids as _ids_for_created_models
from management.db.configuration.tenant import get_single_config_info, insert_config, update_config_by_tenant_config_id
from management.db.model.repository import get_model_by_model_id, get_model_records
from management.services.model.reasoning import _enrich_model_reasoning_capability

# Default-model slots that may be auto-configured after a create/import.
# Maps MODEL_CONFIG_MAPPING keys to the model_type each slot consumes. Only
# slots whose tenant_config row does NOT exist yet are filled, so anything a
# user has ever configured (even if the value was later cleared) is never
# touched -- this also protects embedding swaps that would break existing
# knowledge-base index compatibility.
_AUTO_CONFIGURABLE_MODEL_SLOTS = {
    "llm": "llm",
    "embedding": "embedding",
    "multiEmbedding": "multi_embedding",
    "rerank": "rerank",
    "vlm": "vlm",
    "vlm2": "vlm2",
    "vlm3": "vlm3",
    "vlm4": "vlm4",
    "stt": "stt",
    "tts": "tts",
}


def _default_model_candidate_sort_key(record: Dict[str, Any]):
    """Rank candidates for auto-configuring a default-model slot.

    Preference order: available models first, then larger context windows,
    then stable model_id ordering for determinism.
    """
    is_available = (
        1
        if record.get("connect_status") == ModelConnectStatusEnum.AVAILABLE.value
        else 0
    )
    context_tokens = record.get("context_window_tokens") or 0
    return (-is_available, -int(context_tokens or 0), record.get("model_id") or 0)


def _resolve_existing_slot_config(tenant_id: str, config_key: str):
    """Classify a default-model slot's existing config row.

    Returns (live_model_id, stale_row):
    - live_model_id set: the slot is occupied by a live model (user- or
      system-configured) -- backfill must never touch it.
    - stale_row set: a row exists but its model has been deleted (dangling
      default) -- backfill repairs that row in place.
    - both None: the slot is empty (never configured or cleared by the
      user) -- backfill fills it from the current call's new models.
    """
    row = get_single_config_info(tenant_id, config_key)
    # Note: the DB helper returns {} (not None) when no row matches.
    if not row:
        return None, None
    raw_id = row.get("config_value")
    try:
        model_id = int(raw_id) if raw_id else None
    except (TypeError, ValueError):
        model_id = None
    if model_id is not None and get_model_by_model_id(model_id, tenant_id):
        return model_id, None
    return None, row


def _backfill_default_model_slots(
    user_id: str,
    tenant_id: str,
    new_model_ids: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Auto-configure default-model slots after models are created.

    Slot handling:
    - An OCCUPIED slot (any live model, whether the user picked it or an
      earlier backfill did) is never touched: adding more models later must
      not move an existing default. Batch imports therefore mark their
      per-row creates with skip_default_backfill and finalize once after the
      whole batch, so the first row no longer permanently claims the slot.
    - An EMPTY slot (never configured, or deliberately cleared by the user)
      is filled ONLY from the models created in the current call
      (new_model_ids). Resurrecting an older model the user passed over
      (e.g. after clearing a default) would silently override that choice.
      Legacy callers that omit new_model_ids keep the old all-candidates
      behaviour.
    - Dangling rows (model deleted) are repaired from the full candidate
      pool: the previous choice is gone, so the best remaining replacement
      is appropriate.

    Failures are logged and skipped so backfill can never break the create
    flow.

    Returns a list of {"config_key", "model_id", "display_name", "model_type"}
    entries describing what was auto-configured (empty when nothing changed).
    """
    auto_configured: List[Dict[str, Any]] = []
    try:
        for slot_name, model_type in _AUTO_CONFIGURABLE_MODEL_SLOTS.items():
            config_key = MODEL_CONFIG_MAPPING[slot_name]
            live_model_id, row = _resolve_existing_slot_config(tenant_id, config_key)
            if live_model_id is not None:
                # Occupied by a live model (user- or system-configured):
                # never touch it.
                continue

            candidates = get_model_records({"model_type": model_type}, tenant_id)

            if row is None and new_model_ids is not None:
                # Empty slot: only consider what this create call added.
                candidates = [m for m in candidates if m["model_id"] in new_model_ids]
            if not candidates:
                continue

            if row is not None:
                # Dangling row (model deleted): repair it in place instead of
                # appending another row to the key's history.
                repair = sorted(candidates, key=_default_model_candidate_sort_key)[0]
                success = update_config_by_tenant_config_id(
                    row["tenant_config_id"], str(repair["model_id"])
                )
            else:
                insert_pick = sorted(candidates, key=_default_model_candidate_sort_key)[
                    0
                ]
                success = insert_config(
                    {
                        "tenant_id": tenant_id,
                        "config_key": config_key,
                        "config_value": str(insert_pick["model_id"]),
                        "created_by": user_id,
                        "updated_by": user_id,
                    }
                )
            if not success:
                logging.warning(
                    "Auto-configure default model failed: write returned "
                    "False for key=%s tenant=%s",
                    config_key,
                    tenant_id,
                )
                continue

            picked = repair if row is not None else insert_pick
            logging.info(
                "Auto-configured default %s model to '%s' (model_id=%s) for tenant %s",
                model_type,
                picked.get("display_name"),
                picked["model_id"],
                tenant_id,
            )
            auto_configured.append(
                {
                    "config_key": config_key,
                    "model_id": picked["model_id"],
                    "display_name": picked.get("display_name"),
                    "model_type": model_type,
                }
            )
    except Exception as exc:
        # Backfill is a best-effort enhancement: never fail the create flow.
        logging.error("Default-model backfill failed for tenant %s: %s", tenant_id, exc)
    return auto_configured


async def list_models_for_tenant(tenant_id: str):
    """Get detailed information for all models for a tenant with normalized fields."""
    try:
        records = get_model_records(None, tenant_id)
        result: List[Dict[str, Any]] = []

        # Type mapping for backwards compatibility (chat -> llm for frontend)
        type_map = {
            "chat": "llm",
        }

        for record in records:
            _enrich_model_reasoning_capability(record)
            record["model_name"] = add_repo_to_name(
                model_repo=record["model_repo"],
                model_name=record["model_name"],
            )
            record["connect_status"] = ModelConnectStatusEnum.get_value(
                record.get("connect_status")
            )

            # Map model_type if necessary (for ModelEngine compatibility)
            if record.get("model_type") in type_map:
                record["model_type"] = type_map[record["model_type"]]

            if record.get("model_type") == "llm":
                # Display metadata must never fill persisted configuration fields.
                record["effective_sampling"] = resolve_sampling(record.get("temperature"), record.get("top_p"))

            result.append(record)

        logging.debug("Successfully retrieved model list")
        return result
    except Exception as e:
        logging.error(f"Failed to retrieve model list: {str(e)}")
        raise Exception(f"Failed to retrieve model list: {str(e)}")


async def list_llm_models_for_tenant(tenant_id: str):
    """Get detailed information for all models for a tenant with normalized fields."""
    try:
        records = get_model_records({"model_type": "llm"}, tenant_id)
        result: List[Dict[str, Any]] = []
        for record in records:
            _enrich_model_reasoning_capability(record)
            result.append(
                {
                    "model_id": record["model_id"],
                    "model_name": add_repo_to_name(
                        model_repo=record["model_repo"],
                        model_name=record["model_name"],
                    ),
                    "model_type": record.get("model_type", "llm"),
                    "connect_status": ModelConnectStatusEnum.get_value(
                        record.get("connect_status")
                    ),
                    "display_name": record["display_name"],
                    "api_key": record.get("api_key", ""),
                    "base_url": record.get("base_url", ""),
                    "max_tokens": record.get("max_tokens", 4096),
                    "extra_params": record.get("extra_params"),
                    **(
                        {"reasoning_capability": record["reasoning_capability"]}
                        if record.get("reasoning_capability") is not None
                        else {}
                    ),
                }
            )

        logging.debug("Successfully retrieved model list")
        return result
    except Exception as e:
        logging.error(f"Failed to retrieve model list: {str(e)}")
        raise Exception(f"Failed to retrieve model list: {str(e)}")


async def list_models_for_admin(
    tenant_id: str, model_type: Optional[str] = None, page: int = 1, page_size: int = 20
) -> Dict[str, Any]:
    """Get models for a specified tenant (admin operation) with pagination.

    Args:
        tenant_id: Target tenant ID to query models for
        model_type: Optional model type filter (e.g., 'llm', 'embedding')
        page: Page number for pagination (1-indexed)
        page_size: Number of items per page

    Returns:
        Dict containing tenant_id, tenant_name, paginated models list, and pagination info
    """
    try:
        # Build filters
        filters = None
        if model_type:
            filters = {"model_type": model_type}

        # Get model records for the specified tenant
        records = get_model_records(filters, tenant_id)

        # Type mapping for backwards compatibility
        type_map = {
            "chat": "llm",
        }

        # Normalize model records
        normalized_models: List[Dict[str, Any]] = []
        for record in records:
            record["model_name"] = add_repo_to_name(
                model_repo=record["model_repo"],
                model_name=record["model_name"],
            )
            record["connect_status"] = ModelConnectStatusEnum.get_value(
                record.get("connect_status")
            )

            # Map model_type if necessary
            if record.get("model_type") in type_map:
                record["model_type"] = type_map[record["model_type"]]

            normalized_models.append(record)

        # Calculate pagination
        total = len(normalized_models)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        paginated_models = normalized_models[start_index:end_index]

        # Get tenant name
        from management.services.permission.identity.tenants import get_tenant_info

        try:
            tenant_info = get_tenant_info(tenant_id)
            tenant_name = tenant_info.get("tenant_name", "")
        except Exception:
            tenant_name = ""

        result = {
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "models": paginated_models,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

        logging.debug(
            f"Successfully retrieved admin model list for tenant: {tenant_id}, page: {page}, page_size: {page_size}"
        )
        return result
    except Exception as e:
        logging.error(f"Failed to retrieve admin model list: {str(e)}")
        raise Exception(f"Failed to retrieve admin model list: {str(e)}")
