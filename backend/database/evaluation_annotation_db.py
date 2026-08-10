"""Database operations for evaluation annotation tables."""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import tuple_

from database.client import get_db_session
from database.db_models import (
    AgentEvaluationCase,
    EvaluationAnnotation,
    EvaluationAnnotationSchema,
)


logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Schema CRUD
# ══════════════════════════════════════════════════════════════════════

def list_annotation_schemas(tenant_id: str) -> List[Dict[str, Any]]:
    with get_db_session() as session:

        rows = session.query(EvaluationAnnotationSchema).filter(
            EvaluationAnnotationSchema.tenant_id == tenant_id,

        ).order_by(EvaluationAnnotationSchema.schema_id).all()
        return [_schema_to_dict(r) for r in rows]


def create_annotation_schema(
    tenant_id: str, user_id: str, name: str, description: str,
    annotation_type: str, options: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    with get_db_session() as session:

        row = EvaluationAnnotationSchema(
            tenant_id=tenant_id, name=name, description=description,
            annotation_type=annotation_type, options=options,
        )
        row.created_by = user_id
        session.add(row)
        session.commit()
        session.refresh(row)
        return _schema_to_dict(row)


def update_annotation_schema(
    schema_id: int, tenant_id: str, **kwargs,
) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:

        row = session.query(EvaluationAnnotationSchema).filter(
            EvaluationAnnotationSchema.schema_id == schema_id,
            EvaluationAnnotationSchema.tenant_id == tenant_id,

        ).first()
        if not row:
            return None
        for key in ("name", "description", "options"):
            if key in kwargs and kwargs[key] is not None:
                setattr(row, key, kwargs[key])
        session.commit()
        session.refresh(row)
        return _schema_to_dict(row)


def count_annotations_for_schema(schema_id: int, tenant_id: str) -> int:
    """Return the number of annotations referencing the given schema."""
    with get_db_session() as session:
        return session.query(EvaluationAnnotation).filter(
            EvaluationAnnotation.tenant_id == tenant_id,
            EvaluationAnnotation.schema_id == schema_id,
        ).count()


def delete_annotation_schema(schema_id: int, tenant_id: str) -> bool:
    """Delete an annotation schema by id. Returns True if a row was deleted.

    Callers should check count_annotations_for_schema before calling this
    if they want to prevent deletion of schemas that are still in use.
    """
    with get_db_session() as session:
        rows = session.query(EvaluationAnnotationSchema).filter(
            EvaluationAnnotationSchema.schema_id == schema_id,
            EvaluationAnnotationSchema.tenant_id == tenant_id,
        ).delete(synchronize_session=False)
        session.commit()
        return rows > 0


# ══════════════════════════════════════════════════════════════════════
# Annotation CRUD
# ══════════════════════════════════════════════════════════════════════

def list_annotations_by_evaluation_id(
    tenant_id: str, agent_evaluation_id: int,
) -> Dict[int, List[Dict[str, Any]]]:
    """Return annotations for all cases in an evaluation, grouped by case_id."""
    with get_db_session() as session:
        rows = session.query(EvaluationAnnotation).join(
            AgentEvaluationCase,
            EvaluationAnnotation.case_id == AgentEvaluationCase.agent_evaluation_case_id,
        ).filter(
            EvaluationAnnotation.tenant_id == tenant_id,
            AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,

        ).all()
        result: Dict[int, List[Dict]] = {}
        for r in rows:
            result.setdefault(r.case_id, []).append(_annotation_to_dict(r))
        return result


def list_annotations_by_case_ids(
    tenant_id: str, case_ids: List[int],
) -> Dict[int, List[Dict[str, Any]]]:
    """Return annotations grouped by case_id."""
    if not case_ids:
        return {}
    with get_db_session() as session:

        rows = session.query(EvaluationAnnotation).filter(
            EvaluationAnnotation.tenant_id == tenant_id,
            EvaluationAnnotation.case_id.in_(case_ids),

        ).all()
        result: Dict[int, List[Dict]] = {}
        for r in rows:
            result.setdefault(r.case_id, []).append(_annotation_to_dict(r))
        return result


def batch_upsert_annotations(
    tenant_id: str, user_id: str, annotations: List[Dict[str, Any]],
) -> None:
    """Upsert annotations. Each item: {case_id, schema_id, value}.

    Existing annotations with the same (case_id, schema_id) are updated;
    new ones are inserted. Annotations not in the list are NOT deleted.

    Uses 3 queries total: resolve case_id -> agent_evaluation_id, batch-check
    existing annotations, then one final commit after Python-loop decisions.
    """
    if not annotations:
        return
    with get_db_session() as session:
        # 1. Batch-resolve case_id -> agent_evaluation_id
        distinct_case_ids = list({ann["case_id"] for ann in annotations})
        case_id_to_eval_id: Dict[int, int] = {}
        if distinct_case_ids:
            case_rows = session.query(
                AgentEvaluationCase.agent_evaluation_case_id,
                AgentEvaluationCase.agent_evaluation_id,
            ).filter(
                AgentEvaluationCase.tenant_id == tenant_id,
                AgentEvaluationCase.agent_evaluation_case_id.in_(distinct_case_ids),
            ).all()
            case_id_to_eval_id = {
                row.agent_evaluation_case_id: row.agent_evaluation_id
                for row in case_rows
            }

        # 2. Batch-check which (case_id, schema_id) pairs already exist
        pairs = [(ann["case_id"], ann["schema_id"]) for ann in annotations]
        existing_rows = session.query(EvaluationAnnotation).filter(
            EvaluationAnnotation.tenant_id == tenant_id,
            tuple_(EvaluationAnnotation.case_id, EvaluationAnnotation.schema_id).in_(pairs),
        ).all()
        existing_map = {(row.case_id, row.schema_id): row for row in existing_rows}

        # 3. Decide update vs insert in Python, one commit at the end
        for ann in annotations:
            key = (ann["case_id"], ann["schema_id"])
            existing = existing_map.get(key)
            if existing:
                existing.value = ann["value"]
                existing.updated_by = user_id
            else:
                agent_evaluation_id = case_id_to_eval_id.get(ann["case_id"])
                row = EvaluationAnnotation(
                    tenant_id=tenant_id,
                    agent_evaluation_id=agent_evaluation_id,
                    case_id=ann["case_id"],
                    schema_id=ann["schema_id"],
                    value=ann["value"],
                )
                row.created_by = user_id
                session.add(row)
        session.commit()


def get_annotation_values(
    tenant_id: str, agent_evaluation_id: int, schema_id: int,
) -> List[str]:
    """Return raw annotation values for a given schema within a run.

    Stats computation (Counter / most_common / ratio) is done by the caller
    so that the DB layer stays focused on data access.
    """
    with get_db_session() as session:
        rows = session.query(EvaluationAnnotation.value).join(
            AgentEvaluationCase,
            EvaluationAnnotation.case_id == AgentEvaluationCase.agent_evaluation_case_id,
        ).filter(
            EvaluationAnnotation.tenant_id == tenant_id,
            EvaluationAnnotation.schema_id == schema_id,
            AgentEvaluationCase.agent_evaluation_id == agent_evaluation_id,
        ).all()
        return [r.value for r in rows]


def delete_annotations_by_evaluation_schema(
    tenant_id: str, agent_evaluation_id: int, schema_id: int,
) -> int:
    """Delete all annotations for a given schema within a run.

    Scoped by (tenant_id, agent_evaluation_id, schema_id) so that disabling a
    label on one evaluation task never touches another task's data. Returns the
    number of rows deleted. Pure data access — no business exceptions.
    """
    with get_db_session() as session:
        deleted = session.query(EvaluationAnnotation).filter(
            EvaluationAnnotation.tenant_id == tenant_id,
            EvaluationAnnotation.schema_id == schema_id,
            EvaluationAnnotation.agent_evaluation_id == agent_evaluation_id,
        ).delete(synchronize_session=False)
        session.commit()
        return deleted


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _schema_to_dict(row) -> Dict[str, Any]:
    return {
        "schema_id": row.schema_id, "tenant_id": row.tenant_id,
        "name": row.name, "description": row.description,
        "annotation_type": row.annotation_type, "options": row.options,
        "created_by": row.created_by,
        "create_time": str(row.create_time) if row.create_time else None,
        "update_time": str(row.update_time) if row.update_time else None,
    }


def _annotation_to_dict(row) -> Dict[str, Any]:
    return {
        "annotation_id": row.annotation_id, "tenant_id": row.tenant_id,
        "case_id": row.case_id, "schema_id": row.schema_id,
        "value": row.value,
        "create_time": str(row.create_time) if row.create_time else None,
        "update_time": str(row.update_time) if row.update_time else None,
    }
