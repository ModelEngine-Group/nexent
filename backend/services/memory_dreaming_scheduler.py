"""Compatibility facade for the former Phase 2 Dreaming placeholder."""

try:
    from services.memory_dreaming_service import get_memory_dreaming_service
except (ImportError, ModuleNotFoundError):  # package-style unit-test imports
    from .memory_dreaming_service import get_memory_dreaming_service


def run_once(*, tenant_id: str, user_id: str, agent_id: str, **kwargs):
    return get_memory_dreaming_service().run(
        tenant_id=tenant_id, user_id=user_id, agent_id=agent_id, **kwargs
    )
