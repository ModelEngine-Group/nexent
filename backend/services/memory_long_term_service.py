"""Scope-oriented long-term Markdown memory service."""

from typing import Any, Dict, List, Optional

from database import memory_long_term_db
from database.memory_dreaming_db import try_scope_lock

MAX_LONG_TERM_CHARS = 10_000


class LongTermMemoryError(Exception): pass
class LongTermMemoryConflict(LongTermMemoryError): pass


def subject_id_for(scope: str, tenant_id: str, user_id: str) -> str:
    if scope == "tenant": return tenant_id
    if scope == "user": return user_id
    raise LongTermMemoryError("scope must be tenant or user")


class LongTermMemoryService:
    def get_active(self, tenant_id: str, user_id: str, scope: str) -> Optional[Dict[str, Any]]:
        return memory_long_term_db.get_active(tenant_id, scope, subject_id_for(scope, tenant_id, user_id))

    def get_version(self, tenant_id: str, user_id: str, scope: str, version_id: int):
        return memory_long_term_db.get_version(tenant_id, scope, subject_id_for(scope, tenant_id, user_id), version_id)

    def list_versions(self, tenant_id: str, user_id: str, scope: str, limit: int = 100) -> List[Dict[str, Any]]:
        return memory_long_term_db.list_versions(tenant_id, scope, subject_id_for(scope, tenant_id, user_id), limit)

    def create_manual(self, tenant_id: str, user_id: str, scope: str, content: str,
                      expected_active_version_id: Optional[int]):
        if len(content) > MAX_LONG_TERM_CHARS: raise LongTermMemoryError("content exceeds 10000 characters")
        subject_id = subject_id_for(scope, tenant_id, user_id)
        with try_scope_lock(tenant_id, subject_id, f"long-term:{scope}") as acquired:
            if not acquired: raise LongTermMemoryConflict("scope is busy")
            value = memory_long_term_db.create_and_activate(
                tenant_id=tenant_id, scope=scope, subject_id=subject_id, content=content,
                source="manual", actor_user_id=user_id,
                expected_active_version_id=expected_active_version_id)
            if value is None: raise LongTermMemoryConflict("active version changed")
            return value

    def activate(self, tenant_id: str, user_id: str, scope: str, version_id: int,
                 expected_active_version_id: Optional[int]):
        subject_id = subject_id_for(scope, tenant_id, user_id)
        with try_scope_lock(tenant_id, subject_id, f"long-term:{scope}") as acquired:
            if not acquired: raise LongTermMemoryConflict("scope is busy")
            status, value = memory_long_term_db.activate(
                tenant_id, scope, subject_id, version_id, user_id, expected_active_version_id)
            if status == "conflict": raise LongTermMemoryConflict("active version changed")
            return value


_service = LongTermMemoryService()
def get_memory_long_term_service() -> LongTermMemoryService: return _service
