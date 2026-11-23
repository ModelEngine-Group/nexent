"""Legacy import bridge removed by the new Memory architecture.

The target branch still imports these names from agent code. Keeping explicit
errors here lets applications start while preventing the removed Mem0/local-ES
implementation from silently appearing to persist data. Callers already
degrade on these exceptions; new code must use ``nexent.memory.service`` with
backend hooks.
"""


class LegacyMemoryApiRemoved(RuntimeError):
    pass


async def add_memory_in_levels(**_kwargs):
    raise LegacyMemoryApiRemoved(
        "add_memory_in_levels was removed; use MemoryService.store_memory with a backend hook"
    )


async def search_memory_in_levels(**_kwargs):
    raise LegacyMemoryApiRemoved(
        "search_memory_in_levels was removed; use MemoryService.search_memory with a backend hook"
    )


async def clear_memory(**_kwargs):
    raise LegacyMemoryApiRemoved("clear_memory was removed; use the backend memory record service")
