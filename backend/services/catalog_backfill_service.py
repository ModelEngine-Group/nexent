"""Automatic catalog-driven capacity backfill for bare model_record_t rows.

Reads the approved capability_profiles.CATALOG and fills NULL capacity
columns on matching LLM/VLM rows at backend startup. This makes the
catalog the single source of truth — no manual SQL migration scripts
needed when new models are added to the catalog.

Idempotent: only writes when the target column IS NULL.
Safe: enforces max_output < context_window when filling defaults.
Cross-tenant: backfills all tenants' bare rows in one pass.
"""
import logging

from sqlalchemy import func, or_, select, update

from consts.capability_profiles import CATALOG, CATALOG_REVISION
from database.client import get_db_session
from database.db_models import ModelRecord

logger = logging.getLogger(__name__)

LLM_VLM_TYPES = {"llm", "vlm", "vlm2", "vlm3"}

DEFAULT_CONTEXT_WINDOW = 32_768
DEFAULT_MAX_OUTPUT = 4_096
DEFAULT_RESERVE = 4_096


def backfill_capacity_from_catalog() -> dict:
    """Backfill bare-capacity LLM/VLM rows from the approved catalog.

    For each catalog entry, find model_record_t rows with matching
    (model_factory, model_name) where capacity columns are NULL, and
    fill them with catalog values. Rows not in the catalog get safe
    defaults (32K context, 4K output).

    Returns a summary dict with counts.
    """
    catalog_updated = 0
    default_updated = 0
    reconcile_updated = 0

    with get_db_session() as session:
        # Phase 1: backfill rows that match a catalog entry
        for (provider, model_name), profile in CATALOG.items():
            stmt = (
                select(ModelRecord)
                .where(
                    ModelRecord.delete_flag == "N",
                    func.lower(ModelRecord.model_factory) == provider.lower(),
                    ModelRecord.model_name == model_name,
                    ModelRecord.model_type.in_(list(LLM_VLM_TYPES)),
                    or_(
                        ModelRecord.context_window_tokens.is_(None),
                        ModelRecord.max_output_tokens.is_(None),
                    ),
                )
            )
            records = session.scalars(stmt).all()

            for record in records:
                ctx = record.context_window_tokens
                mout = record.max_output_tokens

                new_ctx = ctx if ctx is not None else max(
                    profile.context_window_tokens,
                    (mout or 0) + 1,
                )
                new_mout = mout if mout is not None else min(
                    profile.max_output_tokens,
                    (ctx or profile.context_window_tokens) - 1,
                )
                new_reserve = (
                    record.default_output_reserve_tokens
                    if record.default_output_reserve_tokens is not None
                    else profile.default_output_reserve_tokens
                )

                update_stmt = (
                    update(ModelRecord)
                    .where(ModelRecord.model_id == record.model_id)
                    .values(
                        context_window_tokens=new_ctx,
                        max_output_tokens=new_mout,
                        default_output_reserve_tokens=new_reserve,
                        capacity_source=record.capacity_source or "profile",
                        capability_profile_version=(
                            record.capability_profile_version
                            or profile.capability_profile_version
                        ),
                        update_time=func.current_timestamp(),
                    )
                )
                session.execute(update_stmt)
                catalog_updated += 1

        # Phase 2: backfill remaining bare LLM/VLM rows with safe defaults
        bare_stmt = (
            select(ModelRecord)
            .where(
                ModelRecord.delete_flag == "N",
                ModelRecord.model_type.in_(list(LLM_VLM_TYPES)),
                or_(
                    ModelRecord.context_window_tokens.is_(None),
                    ModelRecord.max_output_tokens.is_(None),
                ),
            )
        )
        bare_records = session.scalars(bare_stmt).all()

        for record in bare_records:
            ctx = record.context_window_tokens
            mout = record.max_output_tokens

            new_ctx = ctx if ctx is not None else max(
                DEFAULT_CONTEXT_WINDOW, (mout or 0) + 1,
            )
            new_mout = mout if mout is not None else min(
                DEFAULT_MAX_OUTPUT, (ctx or DEFAULT_CONTEXT_WINDOW) - 1,
            )
            new_reserve = (
                record.default_output_reserve_tokens
                if record.default_output_reserve_tokens is not None
                else DEFAULT_RESERVE
            )

            update_stmt = (
                update(ModelRecord)
                .where(ModelRecord.model_id == record.model_id)
                .values(
                    context_window_tokens=new_ctx,
                    max_output_tokens=new_mout,
                    default_output_reserve_tokens=new_reserve,
                    capacity_source=record.capacity_source or "operator",
                    update_time=func.current_timestamp(),
                )
            )
            session.execute(update_stmt)
            default_updated += 1

        # Phase 3: reconcile legacy max_tokens with max_output_tokens
        reconcile_stmt = (
            update(ModelRecord)
            .where(
                ModelRecord.delete_flag == "N",
                ModelRecord.max_output_tokens.isnot(None),
                func.coalesce(ModelRecord.max_tokens, -1)
                != ModelRecord.max_output_tokens,
                func.coalesce(ModelRecord.model_type, "").notin_(
                    ["embedding", "multi_embedding"]
                ),
            )
            .values(
                max_tokens=ModelRecord.max_output_tokens,
                update_time=func.current_timestamp(),
            )
        )
        result = session.execute(reconcile_stmt)
        reconcile_updated = result.rowcount

    summary = {
        "catalog_revision": CATALOG_REVISION,
        "catalog_entries": len(CATALOG),
        "catalog_backfilled": catalog_updated,
        "default_backfilled": default_updated,
        "max_tokens_reconciled": reconcile_updated,
    }
    logger.info("Catalog capacity backfill complete: %s", summary)
    return summary
