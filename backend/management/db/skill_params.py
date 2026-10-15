"""Pure Skill parameter storage normalization."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def split_string_inline_comment(s: str) -> Tuple[str, Optional[str]]:
    """Split ``value # comment`` at the first `` # `` (same rule as the frontend SkillList)."""
    idx = s.find(" # ")
    if idx == -1:
        return s, None
    return s[:idx].rstrip(), s[idx + 3 :].strip() or None


def strip_params_comments_for_db(obj: Any) -> Any:
    """Remove legacy ``_comment`` keys and trailing `` # `` suffixes from strings for JSON/DB storage."""
    if isinstance(obj, str):
        display, _tip = split_string_inline_comment(obj)
        return display
    if isinstance(obj, list):
        return [strip_params_comments_for_db(x) for x in obj]
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if k == "_comment":
                continue
            out[k] = strip_params_comments_for_db(v)
        return out
    return obj
