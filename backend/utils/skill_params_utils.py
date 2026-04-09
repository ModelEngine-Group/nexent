"""Skill ``params`` helpers: DB storage without UI/YAML comment metadata, round-trip YAML for disk."""

from __future__ import annotations

import json
import logging
import re
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


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


def _coerce_scalar_display(display: str) -> Any:
    """Best-effort restore numbers/bools from merged string form (e.g. after stripping `` # ``)."""
    s = display.strip()
    if s == "":
        return display
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    return display


def _scalar_to_node_and_tip(v: Any) -> Tuple[Any, Optional[str]]:
    """Return (typed value, optional comment text) for YAML emission."""
    if isinstance(v, str):
        display, tip = split_string_inline_comment(v)
        return _coerce_scalar_display(display), tip
    return v, None


def _dict_to_commented_map(d: Dict[str, Any]) -> Any:
    """Build ruamel ``CommentedMap``; only scalar ``value # tip`` strings become YAML block comments above keys."""
    from ruamel.yaml.comments import CommentedMap

    cm = CommentedMap()
    for k, v in d.items():
        if k == "_comment":
            continue
        if isinstance(v, dict):
            inner_clean = {kk: vv for kk, vv in v.items() if kk != "_comment"}
            cm[k] = _dict_to_commented_map(inner_clean)
        elif isinstance(v, list):
            cm[k] = _list_to_commented_seq(v)
        else:
            val, tip = _scalar_to_node_and_tip(v)
            cm[k] = val
            if tip:
                cm.yaml_set_comment_before_after_key(k, before=tip + "\n")
    return cm


def _list_to_commented_seq(items: List[Any]) -> Any:
    from ruamel.yaml.comments import CommentedSeq

    seq = CommentedSeq()
    for item in items:
        if isinstance(item, dict):
            seq.append(_dict_to_commented_map(item))
        elif isinstance(item, list):
            seq.append(_list_to_commented_seq(item))
        else:
            val, _ = _scalar_to_node_and_tip(item)
            seq.append(val)
    return seq


def params_dict_to_roundtrip_yaml_text(params: Dict[str, Any]) -> str:
    """Serialize params to YAML with comments restored (ruamel round-trip). Falls back to PyYAML."""
    try:
        from ruamel.yaml import YAML

        cm = _dict_to_commented_map(params)
        y = YAML(typ="rt")
        y.indent(mapping=2, sequence=4, offset=2)
        buf = StringIO()
        y.dump(cm, buf)
        return buf.getvalue()
    except Exception as exc:
        logger.warning(
            "ruamel round-trip YAML failed (%s); falling back to plain yaml.dump",
            exc,
        )
        import yaml as pyyaml

        clean = strip_params_comments_for_db(params)
        return pyyaml.dump(
            clean,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=float("inf"),
        )
