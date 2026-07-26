import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from database.client import as_dict, filter_property, get_db_session
from database.db_models import EvaluationSet, EvaluationSetCase

logger = logging.getLogger("evaluation_set_db")


def create_evaluation_set(
    tenant_id: str,
    name: str,
    description: Optional[str],
    source_filename: Optional[str],
    created_by: Optional[str],
) -> Dict[str, Any]:
    with get_db_session() as session:
        rec = EvaluationSet(
            tenant_id=tenant_id,
            name=name,
            description=description,
            source_filename=source_filename,
            created_by=created_by,
            updated_by=created_by,
            delete_flag="N",
        )
        session.add(rec)
        session.flush()
        return as_dict(rec)


def update_evaluation_set_case_count(evaluation_set_id: int, case_count: int, updated_by: Optional[str] = None) -> None:
    with get_db_session() as session:
        session.query(EvaluationSet).filter(
            EvaluationSet.evaluation_set_id == evaluation_set_id,
            EvaluationSet.delete_flag == "N",
        ).update({"case_count": case_count, "updated_by": updated_by}, synchronize_session=False)


def list_evaluation_sets(tenant_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        q = (
            session.query(EvaluationSet)
            .filter(EvaluationSet.tenant_id == tenant_id, EvaluationSet.delete_flag == "N")
            .order_by(EvaluationSet.update_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return [as_dict(x) for x in q.all()]


def get_evaluation_set(evaluation_set_id: int, tenant_id: str) -> Dict[str, Any]:
    with get_db_session() as session:
        rec = session.query(EvaluationSet).filter(
            EvaluationSet.evaluation_set_id == evaluation_set_id,
            EvaluationSet.tenant_id == tenant_id,
            EvaluationSet.delete_flag == "N",
        ).first()
        if not rec:
            raise ValueError("evaluation set not found")
        return as_dict(rec)


def insert_evaluation_set_cases(
    tenant_id: str,
    evaluation_set_id: int,
    cases: List[Dict[str, Any]],
    created_by: Optional[str],
) -> int:
    """Insert cases. Each case must have: inputs(dict), label(dict), optional case_id(str).

    Returns inserted count.
    """
    with get_db_session() as session:
        inserted = 0
        for i, c in enumerate(cases):
            rec = EvaluationSetCase(
                tenant_id=tenant_id,
                evaluation_set_id=evaluation_set_id,
                case_id=c.get("case_id"),
                inputs=c["inputs"],
                label=c["label"],
                order_no=int(c.get("order_no", i)),
                created_by=created_by,
                updated_by=created_by,
                delete_flag="N",
            )
            session.add(rec)
            inserted += 1
        session.flush()
        return inserted


def list_evaluation_set_cases(
    evaluation_set_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        q = (
            session.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.delete_flag == "N",
            )
            .order_by(EvaluationSetCase.order_no.asc(), EvaluationSetCase.evaluation_set_case_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return [as_dict(x) for x in q.all()]


def get_evaluation_set_cases_all(evaluation_set_id: int, tenant_id: str) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        q = (
            session.query(EvaluationSetCase)
            .filter(
                EvaluationSetCase.evaluation_set_id == evaluation_set_id,
                EvaluationSetCase.tenant_id == tenant_id,
                EvaluationSetCase.delete_flag == "N",
            )
            .order_by(EvaluationSetCase.order_no.asc(), EvaluationSetCase.evaluation_set_case_id.asc())
        )
        return [as_dict(x) for x in q.all()]


def soft_delete_evaluation_set(
    evaluation_set_id: int,
    tenant_id: str,
    deleted_by: str,
) -> None:
    """Soft-delete an evaluation set by setting delete_flag='Y'.

    Raises ``ValueError`` when the set is not found or has already been deleted.
    """
    with get_db_session() as session:
        rows = session.query(EvaluationSet).filter(
            EvaluationSet.evaluation_set_id == evaluation_set_id,
            EvaluationSet.tenant_id == tenant_id,
            EvaluationSet.delete_flag == "N",
        ).update(
            {"delete_flag": "Y", "updated_by": deleted_by},
            synchronize_session=False,
        )
        if rows == 0:
            raise ValueError("evaluation set not found or already deleted")
