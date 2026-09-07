"""Utility helpers for skill import naming conventions."""

_MAX_SKILL_NAME_LENGTH = 100


def _truncate_skill_copy_base_name(base_name, suffix):
    max_base_length = max(_MAX_SKILL_NAME_LENGTH - len(suffix), 1)
    if len(base_name) <= max_base_length:
        return base_name
    return base_name[:max_base_length].rstrip() or base_name[:max_base_length]


def generate_available_copy_skill_name(base_name, unavailable_names=None):
    normalized_base = (base_name or "Skill").strip() or "Skill"
    unavailable = unavailable_names or set()
    if normalized_base not in unavailable:
        return normalized_base
    index = 1
    while True:
        suffix = " 副本" if index == 1 else f" 副本 {index}"
        candidate = f"{_truncate_skill_copy_base_name(normalized_base, suffix)}{suffix}"
        if candidate not in unavailable:
            return candidate
        index += 1
