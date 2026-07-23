from http import HTTPStatus

from fastapi import HTTPException

from services.vectordatabase_service import ElasticSearchService


def require_knowledge_base_edit_permission(index_name: str, user_id: str, tenant_id: str) -> None:
    try:
        ElasticSearchService.require_knowledge_base_edit_permission(
            index_name=index_name,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))


def require_knowledge_base_read_permission(index_name: str, user_id: str, tenant_id: str) -> None:
    """FastAPI adapter: raise 404 if KB is missing, 403 if the user cannot read it."""
    try:
        ElasticSearchService.require_knowledge_base_read_permission(
            index_name=index_name,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))
