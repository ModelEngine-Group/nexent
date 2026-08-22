---
globs: backend/database/**/*.py
description: Database layer standards for models, CRUD, transactions, and exceptions
---

# Database Layer Standards

Scope: all Python under `backend/database/**/*.py`. Concise standards for models, CRUD, transactions, and exceptions.

- Models: define in [backend/database/db_models.py](mdc:backend/database/db_models.py).
- Sessions: use `get_db_session()` from [backend/database/client.py](mdc:backend/database/client.py).
- Exceptions: share a DB exception type in [backend/consts/exceptions.py](mdc:backend/consts/exceptions.py).
- SQLAlchemy Core: prefer `insert`/`update`/`select` with `session.execute()`/`session.scalars()`; ORM `session.add()` is allowed but not default.

## 1) Models and audit fields
- Inherit all models from `TableBase`.
- Shared fields: `create_time`, `update_time`, `created_by`, `updated_by`, `delete_flag` (`Y`/`N`).
- Never re-declare shared fields; add only table-specific columns.

## 2) CRUD and audit
- Create: set `created_by`, `updated_by`, default `delete_flag='N'`; timestamps are server-managed.
- Update: set `updated_by`; do not change `create_time`/`created_by`.
- Delete: soft-delete only (`delete_flag='Y'`, set `updated_by`). Cascade by soft-deleting children in same transaction when needed.
- Read: exclude soft-deleted rows by default (`delete_flag='N'`).

## 3) Transactions and sessions
- Always use `with get_db_session() as session:`.
- Never call `commit()`, `rollback()`, or `close()` in DB-layer code.
- The context manager centrally handles commit/rollback/close.

## 4) Exceptions
- Do not catch DB exceptions in `backend/database/**`; let them propagate.
- Central handling occurs in `get_db_session()`.
- Services that must proceed non-blockingly may catch a shared type (e.g., `DatabaseOperationError`).

## 5) Exception flow (inside get_db_session)
- On exception: `rollback` → re-raise → `close` → propagate to callers.

## 6) Reference patterns (Core; no explicit commit/rollback)
```python
from sqlalchemy import insert, update, select
from database.client import get_db_session, as_dict

def create_entity(data: dict):
    with get_db_session() as session:
        return session.execute(
            insert(SomeModel).values(**data).returning(SomeModel.id)
        ).scalar_one()

def update_entity(entity_id: int, updates: dict, actor: str):
    with get_db_session() as session:
        session.execute(
            update(SomeModel)
            .where(SomeModel.id == entity_id, SomeModel.delete_flag == 'N')
            .values(**updates, updated_by=actor)
        )

def soft_delete_entity(entity_id: int, actor: str):
    with get_db_session() as session:
        session.execute(
            update(SomeModel)
            .where(SomeModel.id == entity_id, SomeModel.delete_flag == 'N')
            .values(delete_flag='Y', updated_by=actor)
        )

def read_active_entity(entity_id: int):
    with get_db_session() as session:
        record = session.scalars(
            select(SomeModel).where(
                SomeModel.id == entity_id,
                SomeModel.delete_flag == 'N',
            )
        ).first()
        return None if record is None else as_dict(record)
```

## 7) Validation checklist
- All models inherit `TableBase`; no duplicated audit fields.
- Deletes are soft deletes (`delete_flag='Y'`) and set `updated_by`.
- No direct `commit`/`rollback`/`close` outside `get_db_session()`.
- No DB exception catching in `backend/database/` modules.
- Reads default to `delete_flag='N'`.
- Services that must proceed on failure catch a shared DB exception type in `consts.exceptions`.
