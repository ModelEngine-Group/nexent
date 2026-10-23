"""Coverage for intentionally retained Memory compatibility shims."""

import pytest

from nexent.memory import memory_service
from utils.memory_utils import build_memory_config


def test_ac078_legacy_config_is_empty():
    assert build_memory_config("tenant") == {}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation",
    [
        memory_service.add_memory_in_levels,
        memory_service.search_memory_in_levels,
        memory_service.clear_memory,
    ],
)
async def test_ac078_removed_memory_apis_fail_explicitly(operation):
    with pytest.raises(memory_service.LegacyMemoryApiRemoved):
        await operation()


@pytest.fixture
def anyio_backend():
    return "asyncio"
