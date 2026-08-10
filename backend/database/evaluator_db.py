"""Database operations for evaluator_t table."""

import logging
from typing import Any

from consts.error_code import ErrorCode
from consts.evaluation_status import EvalRunStatus
from consts.exceptions import AppException
from database.client import get_db_session


logger = logging.getLogger(__name__)


def list_evaluators(
    tenant_id: str,
    source: str | None = None,
    evaluator_type: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List evaluators. Builtin evaluators (tenant_id='') are always included."""
    with get_db_session() as session:
        from database.db_models import Evaluator

        query = session.query(Evaluator).filter(
            Evaluator.tenant_id.in_([tenant_id, ""]),
            Evaluator.is_current,
        )
        if source:
            query = query.filter(Evaluator.source == source)
        if evaluator_type:
            query = query.filter(Evaluator.evaluator_type == evaluator_type)
        if status:
            query = query.filter(Evaluator.status == status)

        results = query.order_by(Evaluator.evaluator_id).all()
        return [_to_dict(r) for r in results]


def get_evaluator(evaluator_id: int, tenant_id: str) -> dict[str, Any] | None:
    """Get a single evaluator by ID."""
    with get_db_session() as session:
        from database.db_models import Evaluator

        row = (
            session.query(Evaluator)
            .filter(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.tenant_id.in_([tenant_id, ""]),
            )
            .first()
        )
        return _to_dict(row) if row else None


def create_evaluator(
    tenant_id: str,
    user_id: str,
    name: str,
    description: str,
    evaluator_type: str,
    prompt: str | None,
    prompt_en: str | None = None,
    code: str | None = None,
    score_range_min: float = 0.0,
    score_range_max: float = 1.0,
    pass_threshold: float = 0.5,
    input_fields: list[dict[str, Any]] | None = None,
    source: str = "custom",
    model_id: int | None = None,
) -> dict[str, Any]:
    """Create a new custom evaluator."""
    with get_db_session() as session:
        from database.db_models import Evaluator

        row = Evaluator(
            tenant_id=tenant_id,
            name=name,
            description=description,
            evaluator_type=evaluator_type,
            source=source,
            prompt=prompt,
            prompt_en=prompt_en,
            code=code,
            score_range_min=score_range_min,
            score_range_max=score_range_max,
            pass_threshold=pass_threshold,
            input_fields=input_fields,
            status="DRAFT",
            version_no=1,
            version_group_id=None,
            is_current=True,
            model_id=model_id,
        )
        row.created_by = user_id
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_dict(row)


def update_evaluator(
    evaluator_id: int,
    tenant_id: str,
    **kwargs,
) -> dict[str, Any] | None:
    """Update evaluator fields (tenant-scoped).

    Behaviours by ``row.status``:

    * **DRAFT** — the row is updated **in place** because no active run
      ever references a DRAFT evaluator snapshot long-term (runs freeze
      the ``evaluator_ids`` list at task creation time against PUBLISHED
      rows only).
    * **PUBLISHED** — a brand new **DRAFT** row is cloned inside the same
      ``version_group_id`` with ``version_no += 1``.  The previous
      PUBLISHED row is retained as a historical record and
      ``is_current`` is flipped so the new DRAFT shows up in the list.
      ``model_id`` is explicitly copied from the published row to avoid
      silently dropping the LLM evaluator reference (which is a common
      regression when the Evaluator table grows new columns).

    A caller MUST own the matching ``tenant_id`` (both the in-use scan
    and the row lookup filter by it).  Active (PENDING/RUNNING) runs
    referencing the evaluator cause ``AGENT_EVALUATION_EVALUATOR_IN_USE``
    so that a running task never sees its judge mutate mid-flight.
    """
    with get_db_session() as session:
        from database.db_models import Evaluator

        # Tenant-aware in-use check — skips runs owned by other tenants so
        # cross-tenant activity never blocks an unrelated tenant.
        in_use = _check_evaluator_in_use(evaluator_id, session, tenant_id)
        if in_use:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_EVALUATOR_IN_USE,
                f"Evaluator is referenced by {len(in_use)} active evaluation run(s) and cannot be modified",
            )

        row = (
            session.query(Evaluator)
            .filter(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.tenant_id == tenant_id,
                Evaluator.source == "custom",
            )
            .first()
        )
        if not row:
            return None

        updatable = [
            "name",
            "description",
            "prompt",
            "prompt_en",
            "code",
            "score_range_min",
            "score_range_max",
            "pass_threshold",
            "input_fields",
        ]

        if row.status == "PUBLISHED":
            # Immutable published snapshot → clone a new DRAFT row and flip
            # is_current.  ``model_id`` is copied verbatim so an LLM-type
            # evaluator keeps its bound judge model across the fork.
            new_row = Evaluator(
                tenant_id=row.tenant_id,
                name=row.name,
                description=row.description,
                name_en=row.name_en,
                description_en=row.description_en,
                evaluator_type=row.evaluator_type,
                source=row.source,
                prompt=row.prompt,
                prompt_en=row.prompt_en,
                code=row.code,
                score_range_min=row.score_range_min,
                score_range_max=row.score_range_max,
                pass_threshold=row.pass_threshold,
                input_fields=row.input_fields,
                status="DRAFT",
                version_no=(row.version_no or 1) + 1,
                version_group_id=row.version_group_id or row.evaluator_id,
                is_current=True,
                model_id=row.model_id,
            )
            for key in updatable:
                if key in kwargs and kwargs[key] is not None:
                    setattr(new_row, key, kwargs[key])

            row.is_current = False
            session.add(new_row)
            session.flush()
            session.refresh(new_row)
            logger.info(
                "update_evaluator: tenant=%s evaluator_id=%s mode=published_clone "
                "new_version_no=%s old_current_flipped=True updated_fields=%s",
                tenant_id,
                evaluator_id,
                new_row.version_no,
                sorted([k for k in updatable if k in kwargs and kwargs[k] is not None]),
            )
            return _to_dict(new_row)

        # DRAFT: mutate the row directly — no new snapshot required since
        # DRAFT rows are not yet frozen into any evaluation run plan.
        touched = sorted(
            [k for k in updatable if k in kwargs and kwargs[k] is not None]
        )
        for key in updatable:
            if key in kwargs and kwargs[key] is not None:
                setattr(row, key, kwargs[key])

        session.commit()
        session.refresh(row)
        logger.info(
            "update_evaluator: tenant=%s evaluator_id=%s mode=draft_inplace version_no=%s updated_fields=%s",
            tenant_id,
            evaluator_id,
            row.version_no,
            touched,
        )
        return _to_dict(row)


def _check_evaluator_in_use(
    evaluator_id: int, session, tenant_id: str | None = None
) -> list[dict[str, Any]]:
    """Return active (PENDING/RUNNING) evaluation runs referencing this evaluator.

    ``tenant_id`` — when provided — scopes the scan to a single tenant so
    tenant A never blocks tenant B on a shared evaluator.  This also
    keeps the working set small on multi-tenant deployments where the
    ``agent_evaluation_t`` table can be very large.

    Matching strategy:
        ``agent_evaluation_t.evaluator_config.evaluator_ids`` is a JSONB
        list of evaluator-IDs frozen when the task is created.  We walk
        every active run and check membership (note: this is O(active_runs)
        on the tenant; acceptable because the population of truly active
        runs stays small).  The per-row loop intentionally has no
        per-row log to avoid log explosions.
    """
    from database.db_models import AgentEvaluation

    q = session.query(AgentEvaluation).filter(
        AgentEvaluation.status.in_([EvalRunStatus.PENDING, EvalRunStatus.RUNNING]),
    )
    # Tenant boundary — without this filter we would scan the union of all
    # tenants active runs and occasionally throw "evaluator in use" for a
    # run the caller does not even own.
    if tenant_id:
        q = q.filter(AgentEvaluation.tenant_id == tenant_id)
    runs = q.all()
    in_use = []
    for r in runs:
        config = r.evaluator_config or {}
        ids = config.get("evaluator_ids", []) if isinstance(config, dict) else []
        if evaluator_id in ids:
            in_use.append(
                {
                    "agent_evaluation_id": r.agent_evaluation_id,
                    "agent_name": getattr(r, "agent_name", None),
                    "status": r.status,
                }
            )
    logger.debug(
        "_check_evaluator_in_use: evaluator_id=%s tenant=%s scanned=%s matched=%s",
        evaluator_id,
        tenant_id or "<all>",
        len(runs),
        len(in_use),
    )
    return in_use


def delete_evaluator(evaluator_id: int, tenant_id: str) -> bool:
    """Hard-delete a custom evaluator. Refuses if referenced by active evaluation runs."""
    with get_db_session() as session:
        from database.db_models import Evaluator

        in_use = _check_evaluator_in_use(evaluator_id, session, tenant_id)
        if in_use:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_EVALUATOR_IN_USE,
                "Evaluator is referenced by active evaluation runs.",
                {"runs": in_use},
            )
        rows = (
            session.query(Evaluator)
            .filter(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.tenant_id == tenant_id,
                Evaluator.source == "custom",
            )
            .delete(synchronize_session=False)
        )
        session.commit()
        return rows > 0


def publish_evaluator(
    evaluator_id: int,
    tenant_id: str,
    version_name: str | None = None,  # noqa: S1172  # reserved for future version naming
    release_note: str | None = None,
) -> dict[str, Any] | None:
    """Publish a DRAFT evaluator. On first publish, sets version_group_id."""
    if release_note:
        logger.info("Publishing evaluator %s with note: %s", evaluator_id, release_note)
    with get_db_session() as session:
        from database.db_models import Evaluator

        row = (
            session.query(Evaluator)
            .filter(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.tenant_id == tenant_id,
                Evaluator.status == "DRAFT",
            )
            .first()
        )
        if not row:
            return None
        row.status = "PUBLISHED"
        if row.version_group_id is None:
            row.version_group_id = row.evaluator_id
        session.commit()
        session.refresh(row)
        return _to_dict(row)


def list_evaluator_versions(
    evaluator_id: int,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """List all versions of an evaluator (same version_group_id)."""
    with get_db_session() as session:
        from database.db_models import Evaluator

        current = (
            session.query(Evaluator)
            .filter(
                Evaluator.evaluator_id == evaluator_id,
                Evaluator.tenant_id.in_([tenant_id, ""]),
            )
            .first()
        )
        if not current or current.version_group_id is None:
            return [_to_dict(current)] if current else []

        rows = (
            session.query(Evaluator)
            .filter(
                Evaluator.version_group_id == current.version_group_id,
                Evaluator.tenant_id.in_([tenant_id, ""]),
            )
            .order_by(Evaluator.version_no.desc())
            .all()
        )
        return [_to_dict(r) for r in rows]


def restore_evaluator_version(
    version_id: int,
    tenant_id: str,
) -> dict[str, Any] | None:
    """Roll the "current" pointer of an evaluator version-group to a historical snapshot.

    Safety checks (in order):

    1. The target row must belong to ``tenant_id`` and be part of a real
       version lineage (``version_group_id`` not NULL).
    2. The row **currently flagged as current** (NOT the target!) must
       not be referenced by any active evaluation run — active runs pin
       evaluator IDs at creation time and the "in-use" test checks the
       row the run *actually resolved* when it started.
    3. The flip is implemented as a two-step mutation:
       ``UPDATE SET is_current = False WHERE version_group_id = X`` (bulk
       blanket reset) followed by ``target.is_current = True``.  This
       guarantees exactly one ``is_current`` per group even if stale rows
       previously violated the invariant.

    The ``tenant_id.in_([tenant_id, ""])`` predicate is used for group
    queries (steps 2 & 3) to include builtin evaluators with
    ``tenant_id = ""`` — those are global but a tenant restoring a
    custom fork still needs to touch them as part of the same lineage.
    """
    with get_db_session() as session:
        from database.db_models import Evaluator

        target = (
            session.query(Evaluator)
            .filter(
                Evaluator.evaluator_id == version_id,
                Evaluator.tenant_id == tenant_id,
                Evaluator.source == "custom",
            )
            .first()
        )
        if not target or target.version_group_id is None:
            return None

        # Check if the CURRENT version is in use (not the target version).
        # Changing the current version affects any active runs referencing it.
        # ``tenant_id.in_`` is required so we do not misidentify a built-in
        # row that shares the same version_group_id with the lineage.
        current = (
            session.query(Evaluator)
            .filter(
                Evaluator.version_group_id == target.version_group_id,
                Evaluator.tenant_id.in_([tenant_id, ""]),
                Evaluator.is_current,
            )
            .first()
        )
        if current:
            in_use = _check_evaluator_in_use(current.evaluator_id, session, tenant_id)
            if in_use:
                raise AppException(
                    ErrorCode.AGENT_EVALUATION_EVALUATOR_IN_USE,
                    f"Evaluator is referenced by {len(in_use)} active evaluation run(s) and cannot restore version",
                )

        # Bulk clear is_current on all rows of the lineage, then flip
        # exactly one row to True.  This is intentionally not "SET ... WHERE
        # evaluator_id = X" so we repair any pre-existing multiple-current
        # corruption as a side effect.
        flipped_rows = (
            session.query(Evaluator)
            .filter(
                Evaluator.version_group_id == target.version_group_id,
                Evaluator.tenant_id.in_([tenant_id, ""]),
            )
            .update({"is_current": False}, synchronize_session=False)
        )

        target.is_current = True
        session.commit()
        session.refresh(target)
        logger.info(
            "restore_evaluator_version: tenant=%s version_group_id=%s "
            "target_version_id=%s target_version_no=%s reset_rows=%s",
            tenant_id,
            target.version_group_id,
            target.evaluator_id,
            target.version_no,
            flipped_rows,
        )
        return _to_dict(target)


def delete_evaluator_version(
    version_id: int,
    tenant_id: str,
) -> bool:
    """Hard-delete a historical evaluator version.

    Two independent guards prevent accidental data loss:

    * **is_current guard** (checked first) — you must restore a
      different snapshot before you can drop the one the UI defaults to.
      This avoids the "my evaluator vanished" UX pitfall if the caller
      blindly deletes the only published version.
    * **in_use guard** — the historical row must not be pinned by any
      active evaluation run owned by this tenant.

    Passed both guards the row is removed with ``session.delete``; since
    the delete is a single row, it cannot cause a log storm.
    """
    with get_db_session() as session:
        from database.db_models import Evaluator

        row = (
            session.query(Evaluator)
            .filter(
                Evaluator.evaluator_id == version_id,
                Evaluator.tenant_id == tenant_id,
                Evaluator.source == "custom",
            )
            .first()
        )
        if not row:
            return False
        if row.is_current:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_EVALUATOR_IN_USE,
                "Cannot delete the current version. Restore another version first.",
            )

        in_use = _check_evaluator_in_use(version_id, session, tenant_id)
        if in_use:
            raise AppException(
                ErrorCode.AGENT_EVALUATION_EVALUATOR_IN_USE,
                "Evaluator is referenced by active evaluation runs.",
                {"runs": in_use},
            )

        session.delete(row)
        session.commit()
        logger.info(
            "delete_evaluator_version: tenant=%s version_id=%s version_group_id=%s version_no=%s removed=True",
            tenant_id,
            version_id,
            getattr(row, "version_group_id", None),
            getattr(row, "version_no", None),
        )
        return True


def _to_dict(row: Any) -> dict[str, Any]:
    """Convert an Evaluator ORM object to a dict."""
    return {
        "evaluator_id": row.evaluator_id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "name_en": row.name_en,
        "description_en": row.description_en,
        "evaluator_type": row.evaluator_type,
        "source": row.source,
        "prompt": row.prompt,
        "code": row.code,
        "score_range_min": row.score_range_min,
        "score_range_max": row.score_range_max,
        "pass_threshold": row.pass_threshold,
        "input_fields": row.input_fields,
        "status": row.status,
        "version_no": row.version_no,
        "version_group_id": row.version_group_id,
        "is_current": bool(row.is_current) if row.is_current is not None else True,
        "created_by": row.created_by,
        "create_time": str(row.create_time) if row.create_time else None,
        "update_time": str(row.update_time) if row.update_time else None,
    }
