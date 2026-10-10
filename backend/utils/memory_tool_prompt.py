from collections.abc import Iterable

def should_enable_memory_tool_policy(tool_names: Iterable[str]) -> bool:
    """Enable memory guidance only for a final visible store tool."""
    return "store_memory" in set(tool_names)
