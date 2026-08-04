import pytest

from nexent.memory.models import MemoryLayer, MemoryType
from nexent.memory.service import MemoryService


@pytest.mark.asyncio
async def test_store_memory_propagates_backend_unchanged_result():
    async def backend_store(_payload):
        return {
            "memory_id": 17,
            "event": "UNCHANGED",
        }

    service = MemoryService(backend_store=backend_store)

    result = await service.store_memory(
        content="existing preference",
        tenant_id="tenant",
        user_id="user",
        agent_id="agent",
        layer=MemoryLayer.AGENT,
        memory_type=MemoryType.SHORT_TERM,
    )

    assert result.memory_id == "17"
    assert result.event == "UNCHANGED"
    assert result.content == "existing preference"
