"""Skill management service."""

import aiofiles
import argparse
import ast
import asyncio
import inspect
import io
import json
import logging
import os
import uuid
import zipfile
import re
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from nexent.skills import SkillManager
from nexent.skills.skill_loader import SkillLoader
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import ModelConfig
from consts.const import CONTAINER_SKILLS_PATH, OFFICIAL_SKILLS_ZIP_PATH, ROOT_DIR
from consts.exceptions import SkillException
from database import skill_db
from agents.skill_creation_agent import create_skill_from_request
from utils.prompt_template_utils import get_skill_creation_simple_prompt_template
from utils.content_classifier_utils import ContentClassifier

logger = logging.getLogger(__name__)

_skill_manager: Optional[SkillManager] = None


def _normalize_zip_entry_path(name: str) -> str:
    """Normalize a ZIP member path for comparison (slashes, strip ./)."""
    norm = name.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _find_zip_member_config_yaml(
    file_list: List[str],
    preferred_skill_root: Optional[str] = None,
) -> Optional[str]:
    """Return the ZIP entry path for .../config/config.yaml (any depth; filename case-insensitive).

    If preferred_skill_root is set (usually the folder containing SKILL.md, e.g. zip root
    ``my_skill/SKILL.md`` -> ``my_skill``), prefer ``<root>/config/config.yaml``.
    """
    suffix = "/config/config.yaml"
    root_only = "config/config.yaml"
    candidates: List[str] = []
    for name in file_list:
        if name.endswith("/"):
            continue
        norm = _normalize_zip_entry_path(name)
        if not norm:
            continue
        nlow = norm.lower()
        if nlow == root_only or nlow.endswith(suffix):
            candidates.append(name)

    if not candidates:
        return None

    if preferred_skill_root:
        pref = _normalize_zip_entry_path(preferred_skill_root)
        if pref:
            pref_low = pref.lower()
            expected_suffix = f"{pref_low}/config/config.yaml"
            for name in candidates:
                if _normalize_zip_entry_path(name).lower() == expected_suffix:
                    return name
            for name in candidates:
                n = _normalize_zip_entry_path(name).lower()
                if n.startswith(pref_low + "/"):
                    return name

    return candidates[0]


def _params_dict_to_storable(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure params are JSON-serializable for the database JSON column."""
    try:
        return json.loads(json.dumps(data, default=str))
    except (TypeError, ValueError) as exc:
        raise SkillException(
            f"params from config/config.yaml cannot be stored: {exc}"
        ) from exc


def _comment_text_from_token(tok: Any) -> Optional[str]:
    """Normalize a ruamel CommentToken (or similar) to tooltip text after ``#``."""
    if tok is None:
        return None
    val = getattr(tok, "value", None)
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("#"):
            return s[1:].strip()
    return None


def _tuple_slot2(tok_container: Any) -> Any:
    """Return ruamel per-key tuple slot index 2 (EOL / before-next-key comment token)."""
    if not tok_container or len(tok_container) <= 2:
        return None
    return tok_container[2]


def _is_before_next_sibling_comment_token(tok: Any) -> bool:
    """True if token is a comment line placed *above the next key* (starts with newline in ruamel)."""
    if tok is None:
        return False
    val = getattr(tok, "value", None)
    return isinstance(val, str) and val.startswith("\n")


def _flatten_ca_comment_to_text(comment_field: Any) -> Optional[str]:
    """Join ``#`` lines from ``ca.comment`` (block header above first key in map or first list item)."""
    if not comment_field:
        return None
    parts: List[str] = []
    if isinstance(comment_field, list):
        for part in comment_field:
            if part is None:
                continue
            if isinstance(part, list):
                for tok in part:
                    t = _comment_text_from_token(tok)
                    if t:
                        parts.append(t)
            else:
                t = _comment_text_from_token(part)
                if t:
                    parts.append(t)
    if not parts:
        return None
    return " ".join(parts)


def _comment_from_map_block_header(cm: Any) -> Optional[str]:
    """Lines above the first key in this ``CommentedMap`` (``ca.comment``)."""
    ca = getattr(cm, "ca", None)
    if not ca or not ca.comment:
        return None
    return _flatten_ca_comment_to_text(ca.comment)


def _tooltip_for_commented_map_key(cm: Any, ordered_keys: List[Any], index: int, key: Any) -> Optional[str]:
    """Collect tooltip text: block header, line-above key, and same-line EOL ``#`` for one mapping key."""
    tips: List[str] = []
    if index == 0:
        h = _comment_from_map_block_header(cm)
        if h:
            tips.append(h)
    if index > 0:
        prev_k = ordered_keys[index - 1]
        ca = getattr(cm, "ca", None)
        if ca and ca.items:
            prev_tup = ca.items.get(prev_k)
            tok = _tuple_slot2(prev_tup) if prev_tup else None
            if _is_before_next_sibling_comment_token(tok):
                t = _comment_text_from_token(tok)
                if t:
                    tips.append(t)
    ca = getattr(cm, "ca", None)
    if ca and ca.items:
        tup = ca.items.get(key)
        tok = _tuple_slot2(tup) if tup else None
        if tok is not None and not _is_before_next_sibling_comment_token(tok):
            t = _comment_text_from_token(tok)
            if t:
                tips.append(t)
    if not tips:
        return None
    return " ".join(tips)


def _tooltip_for_commented_seq_index(seq: Any, index: int) -> Optional[str]:
    """Same rules as maps: ``ca.comment`` for item 0; slot 0 on previous item for 'line above next'."""
    tips: List[str] = []
    if index == 0:
        ca = getattr(seq, "ca", None)
        if ca and ca.comment:
            h = _flatten_ca_comment_to_text(ca.comment)
            if h:
                tips.append(h)
    if index > 0:
        ca = getattr(seq, "ca", None)
        if ca and ca.items:
            prev_tup = ca.items.get(index - 1)
            if prev_tup and len(prev_tup) > 0 and prev_tup[0] is not None:
                tok = prev_tup[0]
                if _is_before_next_sibling_comment_token(tok):
                    t = _comment_text_from_token(tok)
                    if t:
                        tips.append(t)
    ca = getattr(seq, "ca", None)
    if ca and ca.items:
        tup = ca.items.get(index)
        if tup:
            tok = _tuple_slot2(tup)
            if tok is not None and not _is_before_next_sibling_comment_token(tok):
                t = _comment_text_from_token(tok)
                if t:
                    tips.append(t)
    if not tips:
        return None
    return " ".join(tips)


def _apply_inline_comment_to_scalar(val: Any, comment: Optional[str]) -> Any:
    """Append `` # comment`` to scalars so the UI can show tooltips (same as frontend convention)."""
    if not comment:
        return val
    if isinstance(val, str):
        return f"{val} # {comment}"
    if isinstance(val, (dict, list)):
        return val
    try:
        encoded = json.dumps(val, ensure_ascii=False)
    except (TypeError, ValueError):
        encoded = str(val)
    return f"{encoded} # {comment}"


def _commented_tree_to_plain(node: Any) -> Any:
    """Turn ruamel CommentedMap/Seq into plain dict/list.

    YAML ``#`` comments are merged only into **scalar** values as ``value # tip`` (same as the UI).
    Block / line-above-key comments attached to **mapping or list values** are not persisted (no ``_comment`` keys).
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(node, CommentedMap):
        ordered_keys = list(node.keys())
        out: Dict[str, Any] = {}
        for i, k in enumerate(ordered_keys):
            v = node[k]
            plain_v = _commented_tree_to_plain(v)
            tip = _tooltip_for_commented_map_key(node, ordered_keys, i, k)
            if tip is not None and not isinstance(plain_v, (dict, list)):
                plain_v = _apply_inline_comment_to_scalar(plain_v, tip)
            out[k] = plain_v
        return out
    if isinstance(node, CommentedSeq):
        out_list: List[Any] = []
        for i, v in enumerate(node):
            plain_v = _commented_tree_to_plain(v)
            tip = _tooltip_for_commented_seq_index(node, i)
            if tip is not None and not isinstance(plain_v, (dict, list)):
                plain_v = _apply_inline_comment_to_scalar(plain_v, tip)
            out_list.append(plain_v)
        return out_list
    return node


def _ruamel_tree_to_plain(node: Any) -> Any:
    """Convert ruamel CommentedMap/Seq to plain dict/list with NO comment merging.

    Used for parsing config.yaml into config_values where the value must be clean
    (e.g. ``/mnt/nexent`` not ``/mnt/nexent # Initial workspace path``).
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(node, CommentedMap):
        return {k: _ruamel_tree_to_plain(v) for k, v in node.items()}
    if isinstance(node, CommentedSeq):
        return [_ruamel_tree_to_plain(v) for v in node]
    return node


def _parse_yaml_ruamel_plain(text: str) -> Dict[str, Any]:
    """Parse YAML with ruamel round-trip and return plain dict (no comment merging).

    Used for ``config.yaml`` → ``config_values`` where scalar values must be clean.
    """
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap

    y = YAML(typ="rt")
    try:
        root = y.load(text)
    except Exception as exc:
        raise SkillException(f"Invalid YAML in config/config.yaml: {exc}") from exc
    if root is None:
        return {}
    if isinstance(root, CommentedMap):
        plain = _ruamel_tree_to_plain(root)
    elif isinstance(root, dict):
        plain = root
    else:
        raise SkillException(
            "config/config.yaml must contain a JSON or YAML object (mapping), not a list or scalar"
        )
    if not isinstance(plain, dict):
        raise SkillException(
            "config/config.yaml must contain a JSON or YAML object (mapping), not a list or scalar"
        )
    return _params_dict_to_storable(plain)


def _parse_yaml_with_ruamel_merge_eol_comments(text: str) -> Dict[str, Any]:
    """Parse YAML with ruamel; merge ``#`` into scalar values only (``value # tip`` for the UI).

    Does not inject ``_comment`` into nested objects; non-scalar-adjacent YAML comments are dropped.
    """
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap

    # Round-trip loader preserves ``CommentedMap`` and comment tokens; ``safe`` returns plain dict.
    y = YAML(typ="rt")
    try:
        root = y.load(text)
    except Exception as exc:
        raise SkillException(
            f"Invalid YAML in config/config.yaml: {exc}"
        ) from exc
    if root is None:
        return {}
    if isinstance(root, CommentedMap):
        plain = _commented_tree_to_plain(root)
    elif isinstance(root, dict):
        plain = root
    else:
        raise SkillException(
            "config/config.yaml must contain a JSON or YAML object (mapping), not a list or scalar"
        )
    if not isinstance(plain, dict):
        raise SkillException(
            "config/config.yaml must contain a JSON or YAML object (mapping), not a list or scalar"
        )
    return _params_dict_to_storable(plain)


def _get_skill_inputs_from_code(scripts_dir: str) -> List[Dict[str, Any]]:
    """Extract argparse parameters from skill scripts using AST analysis.

    Walks every ``scripts/*.py`` file (skipping ``_*.py``) and uses AST to find
    all ``parser.add_argument(...)`` calls anywhere in the file, including inside
    function bodies and ``if __name__ == "__main__":`` blocks.

    Mirrors ``get_local_tools()`` in tool_configuration_service.py.

    Args:
        scripts_dir: Absolute path to the skill's ``scripts/`` directory.

    Returns:
        List of input parameter dicts with name, type, required, description, default.
    """
    inputs: List[Dict[str, Any]] = []
    seen_names: set = set()

    if not os.path.isdir(scripts_dir):
        return inputs

    for filename in os.listdir(scripts_dir):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        script_path = os.path.join(scripts_dir, filename)
        try:
            source = open(script_path, "r", encoding="utf-8").read()
        except (OSError, IOError):
            continue

        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_add_argument_call(node):
                continue

            parsed = _extract_arg_from_add_argument(node)
            if not parsed:
                continue

            param_name = parsed["name"]
            if param_name in ("help", "h") or param_name in seen_names:
                continue
            seen_names.add(param_name)

            inputs.append({
                "name": param_name,
                "type": parsed["type"],
                "required": parsed["required"],
                "description_en": parsed.get("description_en", ""),
            })

    return inputs


def _is_add_argument_call(node: ast.Call) -> bool:
    """Return True if node is a call to ``<obj>.add_argument(...)``."""
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "add_argument":
        return False
    if isinstance(node.func.value, ast.Name) and node.func.value.id == "parser":
        return True
    if isinstance(node.func.value, ast.Attribute):
        return True
    return False


def _extract_arg_from_add_argument(node: ast.Call) -> Optional[Dict[str, Any]]:
    """Extract parameter metadata from an ``add_argument`` Call AST node."""
    args = node.args
    kwargs = {kw.arg: kw.value for kw in node.keywords}

    # Positional arg 0 = name or first positional arg (--name / name)
    name_node = args[0] if args else kwargs.get("name")
    if name_node is None:
        return None
    param_name = _ast_literal_eval(name_node)
    if not param_name or not isinstance(param_name, str):
        return None

    # --name style
    if param_name.startswith("--"):
        param_name = param_name[2:]
    elif param_name.startswith("-"):
        param_name = param_name[1:]

    # Determine type
    param_type = "string"
    type_node = kwargs.get("type")
    if type_node is not None:
        type_name = _get_type_name(type_node)
        if type_name in ("int", "integer"):
            param_type = "number"
        elif type_name in ("float",):
            param_type = "number"
        elif type_name in ("bool",):
            param_type = "boolean"

    # Description
    help_node = kwargs.get("help")
    description = ""
    if help_node is not None:
        val = _ast_literal_eval(help_node)
        if isinstance(val, str):
            description = val

    # Required / default
    required = False
    default: Any = None

    if kwargs.get("required") is not None:
        req_val = _ast_literal_eval(kwargs["required"])
        if req_val is True:
            required = True

    default_node = kwargs.get("default")
    if default_node is not None:
        default = _ast_literal_eval(default_node)
        if default is None or (isinstance(default, str) and default == ""):
            required = False
        elif not required:
            required = False

    return {
        "name": param_name,
        "type": param_type,
        "required": required,
        "description_en": description,
    }


def _get_type_name(node: ast.AST) -> str:
    """Get the type name string from a type-related AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _ast_literal_eval(node: ast.AST) -> Any:
    """Safely evaluate a literal AST node (Name, Constant, Str, Num, etc.) to a Python value."""
    if isinstance(node, (ast.Constant, ast.Num)):
        return getattr(node, "value", None)
    if isinstance(node, ast.Str):  # Python < 3.8 compat
        return node.s
    if isinstance(node, ast.Name):
        name = node.id
        if name == "None":
            return None
        if name == "True":
            return True
        if name == "False":
            return False
        return name
    if isinstance(node, (ast.List, ast.Tuple)):
        elts = [_ast_literal_eval(e) for e in node.elts]
        return list(elts) if isinstance(node, ast.List) else tuple(elts)
    if isinstance(node, ast.Dict):
        return {_ast_literal_eval(k): _ast_literal_eval(v) for k, v in node.keys}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        val = _ast_literal_eval(node.operand)
        if isinstance(val, (int, float)):
            return -val if isinstance(node.op, ast.USub) else val
    if isinstance(node, ast.BinOp):
        left = _ast_literal_eval(node.left)
        right = _ast_literal_eval(node.right)
        if isinstance(left, str) and isinstance(right, str) and isinstance(node.op, ast.Add):
            return left + right
    return None


def _parse_yaml_fallback_pyyaml(text: str) -> Dict[str, Any]:
    """Parse YAML with PyYAML (comments are dropped)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SkillException(
            f"Invalid JSON or YAML in config/config.yaml: {exc}"
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SkillException(
            "config/config.yaml must contain a JSON or YAML object (mapping), not a list or scalar"
        )
    return _params_dict_to_storable(data)


def _parse_skill_params_from_config_bytes(raw: bytes) -> Dict[str, Any]:
    """Parse JSON or YAML from config/config.yaml bytes (DB upload path; scalar ``#`` tips merged when possible)."""
    text = raw.decode("utf-8-sig").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            return _parse_yaml_ruamel_plain(text)
        except ImportError:
            logger.warning("ruamel.yaml not installed; YAML comments will be dropped on parse")
            return _parse_yaml_fallback_pyyaml(text)
        except SkillException:
            raise
        except Exception as exc:
            logger.warning(
                "ruamel YAML parse failed (%s); falling back to PyYAML",
                exc,
            )
            return _parse_yaml_fallback_pyyaml(text)
    else:
        if not isinstance(data, dict):
            raise SkillException(
                "config/config.yaml must contain a JSON or YAML object (mapping), not a list or scalar"
            )
        return _params_dict_to_storable(data)


def _parse_skill_schema_from_yaml_bytes(raw: bytes) -> List[Dict[str, Any]]:
    """Parse config/schema.yaml bytes into List[SkillParam].

    Expected YAML structure:
        param_name:
          type: string | number | boolean | array | object
          required: true | false
          description_en: "English description"
          description_zh: "Chinese description"
          depends_on: other_param_name

    Returns a list of param dicts with name, type, required, description_en,
    description_zh, depends_on — matching frontend SkillParam interface.
    """
    text = raw.decode("utf-8-sig").strip()
    if not text:
        logger.warning("[schema] Empty raw bytes for schema.yaml")
        return []
    data: Any = None
    parse_method = "unknown"
    try:
        data = json.loads(text)
        parse_method = "json"
    except json.JSONDecodeError:
        try:
            data = _parse_yaml_with_ruamel_merge_eol_comments(text)
            parse_method = "ruamel"
        except ImportError:
            data = _parse_yaml_fallback_pyyaml(text)
            parse_method = "pyyaml"
        except SkillException:
            raise
        except Exception:
            try:
                data = _parse_yaml_fallback_pyyaml(text)
                parse_method = "pyyaml"
            except Exception as exc:
                logger.warning("[schema] All YAML parsers failed: %s", exc)
                return []

    if not isinstance(data, dict):
        logger.warning("[schema] Parsed data is not a dict (type=%s, parse_method=%s)", type(data).__name__, parse_method)
        return []

    result: List[Dict[str, Any]] = []
    for param_name, meta in data.items():
        if not isinstance(meta, dict):
            logger.debug("[schema] Skipping param '%s': meta is not a dict (%s)", param_name, type(meta).__name__)
            continue
        result.append({
            "name": param_name,
            "type": meta.get("type", "string"),
            "required": bool(meta.get("required", False)),
            "description_en": meta.get("description_en", meta.get("description", "")),
            "description_zh": meta.get("description_zh", ""),
            "depends_on": meta.get("depends_on"),
        })
    return result


def _read_params_from_zip_config_yaml(
    zip_bytes: bytes,
    preferred_skill_root: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """If the archive contains config/config.yaml, read and parse it into params; else None."""
    import zipfile

    zip_stream = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_stream, "r") as zf:
        member = _find_zip_member_config_yaml(
            zf.namelist(),
            preferred_skill_root=preferred_skill_root,
        )
        if not member:
            return None
        raw = zf.read(member)
    params = _parse_skill_params_from_config_bytes(raw)
    logger.info("Loaded skill params from ZIP member %s", member)
    return params


def _find_zip_member_schema_yaml(
    file_list: List[str],
    preferred_skill_root: Optional[str] = None,
) -> Optional[str]:
    """Return the ZIP entry path for .../config/schema.yaml (any depth; case-insensitive)."""
    for entry in file_list:
        norm = _normalize_zip_entry_path(entry)
        # Match .../config/schema.yaml at any depth
        parts = norm.split("/")
        if len(parts) >= 2 and parts[-2] == "config" and parts[-1] == "schema.yaml":
            logger.debug("[schema] Found schema.yaml via config/ prefix match: %s", entry)
            return entry
        # Fallback: if preferred_root is given, also check <root>/config/schema.yaml
        if preferred_skill_root and norm == f"{preferred_skill_root}/config/schema.yaml":
            logger.debug("[schema] Found schema.yaml via preferred_root match: %s", entry)
            return entry
    logger.debug("[schema] No schema.yaml found in ZIP entries (preferred_root=%s, entry_count=%d)", preferred_skill_root, len(file_list))
    return None


def _read_schema_yaml_from_zip(
    zip_bytes: bytes,
    preferred_skill_root: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """If the archive contains config/schema.yaml, parse it into List[SkillParam]; else None."""
    import zipfile

    zip_stream = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zip_stream, "r") as zf:
        member = _find_zip_member_schema_yaml(
            zf.namelist(),
            preferred_skill_root=preferred_skill_root,
        )
        if not member:
            return None
        raw = zf.read(member)
    parsed = _parse_skill_schema_from_yaml_bytes(raw)
    if not parsed:
        logger.debug("[schema] Parsed result is empty from ZIP member %s", member)
    return parsed


def _get_skill_inputs_from_zip(
    zip_bytes: bytes,
    preferred_skill_root: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract argparse parameters from scripts/*.py inside a ZIP archive.

    Mirrors ``_get_skill_inputs_from_code`` but reads from ZIP bytes instead of filesystem.

    Args:
        zip_bytes: ZIP archive content.
        preferred_skill_root: Preferred folder name inside ZIP containing scripts/.

    Returns:
        List of input parameter dicts with name, type, required, description, default.
    """
    zip_stream = io.BytesIO(zip_bytes)
    inputs: List[Dict[str, Any]] = []
    seen_names: set = set()

    try:
        with zipfile.ZipFile(zip_stream, "r") as zf:
            file_list = zf.namelist()
            scripts_root = preferred_skill_root or ""

            for member in file_list:
                normalized = member.replace("\\", "/").strip()
                if not normalized.endswith(".py") or "/_" in normalized or normalized.endswith("/_"):
                    continue
                if not normalized.startswith(scripts_root + "/scripts/"):
                    if scripts_root:
                        continue
                    parts = normalized.split("/")
                    if len(parts) < 2 or parts[-2] != "scripts":
                        continue

                try:
                    source = zf.read(member).decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                try:
                    tree = ast.parse(source, filename=member)
                except SyntaxError:
                    continue

                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not _is_add_argument_call(node):
                        continue
                    parsed = _extract_arg_from_add_argument(node)
                    if not parsed:
                        continue
                    param_name = parsed["name"]
                    if param_name in ("help", "h") or param_name in seen_names:
                        continue
                    seen_names.add(param_name)
                    inputs.append({
                        "name": param_name,
                        "type": parsed["type"],
                        "required": parsed["required"],
                        "description_en": parsed.get("description_en", ""),
                    })
    except zipfile.BadZipFile:
        return inputs

    return inputs


def _local_skill_config_yaml_path(skill_name: str, local_skills_dir: str) -> str:
    """Absolute path to <local_skills_dir>/<skill_name>/config/config.yaml."""
    return os.path.join(local_skills_dir, skill_name, "config", "config.yaml")


def _local_skill_schema_yaml_path(skill_name: str, local_skills_dir: str) -> str:
    """Absolute path to <local_skills_dir>/<skill_name>/config/schema.yaml."""
    return os.path.join(local_skills_dir, skill_name, "config", "schema.yaml")


def _write_skill_params_to_local_config_yaml(
    skill_name: str,
    params: Dict[str, Any],
    local_skills_dir: str,
) -> None:
    """Write params to config/config.yaml; scalar ``value # tip`` strings round-trip as YAML comments above keys."""
    from utils.skill_params_utils import params_dict_to_roundtrip_yaml_text

    if not local_skills_dir:
        return
    config_dir = os.path.join(local_skills_dir, skill_name, "config")
    os.makedirs(config_dir, exist_ok=True)
    path = _local_skill_config_yaml_path(skill_name, local_skills_dir)
    text = params_dict_to_roundtrip_yaml_text(params)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info("Wrote skill params to %s", path)


def _remove_local_skill_config_yaml(skill_name: str, local_skills_dir: str) -> None:
    """Remove config/config.yaml when params are cleared in the database."""
    if not local_skills_dir:
        return
    path = _local_skill_config_yaml_path(skill_name, local_skills_dir)
    if os.path.isfile(path):
        os.remove(path)
        logger.info("Removed %s (params cleared in DB)", path)


def get_skill_manager(tenant_id: Optional[str] = None) -> SkillManager:
    """Create a SkillManager instance with optional tenant-based directory isolation.

    Args:
        tenant_id: Tenant ID for directory isolation. When provided, skills
            are stored under CONTAINER_SKILLS_PATH / tenant_id /
    """
    return SkillManager(base_skills_dir=CONTAINER_SKILLS_PATH, tenant_id=tenant_id)


class SkillService:
    """Skill management service for backend operations."""

    def __init__(self, skill_manager: Optional[SkillManager] = None, tenant_id: Optional[str] = None):
        """Initialize SkillService.

        Args:
            skill_manager: Optional SkillManager instance, uses tenant-aware global if not provided
            tenant_id: Tenant ID for skill isolation. Required when no skill_manager is provided.
        """
        self.tenant_id = tenant_id
        self.skill_manager = skill_manager or get_skill_manager(tenant_id)

    def _resolve_local_skills_dir_for_overlay(self) -> Optional[str]:
        """Directory where skill folders live: ``SKILLS_PATH``, else ``ROOT_DIR/skills`` if present."""
        d = self.skill_manager.local_skills_dir or CONTAINER_SKILLS_PATH
        if d:
            return str(d).rstrip(os.sep) or None
        if ROOT_DIR:
            candidate = os.path.join(ROOT_DIR, "skills")
            if os.path.isdir(candidate):
                return candidate
        return None

    def _enrich_configs_from_yaml(self, skill: Dict[str, Any]) -> Dict[str, Any]:
        """Read local config files and overlay onto skill.

        config/config.yaml → config_values (runtime defaults dict)
        config/schema.yaml → config_schemas (parameter metadata list)

        If a file does not exist, the corresponding DB key is removed so the
        response never contains stale data (e.g. {"configs": null} instead of
        the old DB value).
        """
        out = dict(skill)
        local_dir = self._resolve_local_skills_dir_for_overlay()
        if not local_dir:
            return out
        name = out.get("name")
        if not name:
            return out
        config_path = _local_skill_config_yaml_path(name, local_dir)
        if os.path.isfile(config_path):
            try:
                with open(config_path, "rb") as f:
                    raw = f.read()
                out["config_values"] = _parse_skill_params_from_config_bytes(raw)
            except Exception as exc:
                logger.warning("Could not parse local config.yaml for skill %s: %s", name, exc)
        else:
            out.pop("config_values", None)
        # schema.yaml takes precedence over DB config_schemas
        schema_path = _local_skill_schema_yaml_path(name, local_dir)
        if os.path.isfile(schema_path):
            try:
                with open(schema_path, "rb") as f:
                    raw = f.read()
                parsed = _parse_skill_schema_from_yaml_bytes(raw)
                out["config_schemas"] = parsed
            except Exception as exc:
                logger.warning("Could not parse local schema.yaml for skill %s: %s", name, exc)
        else:
            out.pop("config_schemas", None)
        return out

    def list_skills(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all skills for a tenant.

        Args:
            tenant_id: Tenant ID for filtering skills. Uses instance tenant_id if not provided.

        Returns:
            List of skill info dicts
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        try:
            skills = skill_db.list_skills(effective_tenant_id)
            enriched = [self._enrich_configs_from_yaml(s) for s in skills]
            return enriched
        except Exception as e:
            logger.error(f"Error listing skills: {e}")
            raise SkillException(f"Failed to list skills: {str(e)}") from e

    def get_skill(self, skill_name: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a specific skill within a tenant.

        Args:
            skill_name: Name of the skill
            tenant_id: Tenant ID for filtering. Uses instance tenant_id if not provided.

        Returns:
            Skill dict or None if not found
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        try:
            skill = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
            if skill:
                return self._enrich_configs_from_yaml(skill)
            return None
        except Exception as e:
            logger.error(f"Error getting skill {skill_name}: {e}")
            raise SkillException(f"Failed to get skill: {str(e)}") from e

    def get_skill_by_id(self, skill_id: int, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a specific skill by ID within a tenant.

        Args:
            skill_id: ID of the skill
            tenant_id: Tenant ID for filtering. Uses instance tenant_id if not provided.

        Returns:
            Skill dict or None if not found
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        try:
            skill = skill_db.get_skill_by_id(skill_id, effective_tenant_id)
            if skill:
                return self._enrich_configs_from_yaml(skill)
            return None
        except Exception as e:
            logger.error(f"Error getting skill by ID {skill_id}: {e}")
            raise SkillException(f"Failed to get skill: {str(e)}") from e

    def create_skill(
        self,
        skill_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new skill for a tenant.

        Args:
            skill_data: Skill data including name, description, content, etc.
            tenant_id: Tenant ID for skill isolation. Uses instance tenant_id if not provided.
            user_id: User ID of the creator

        Returns:
            Created skill dict

        Raises:
            SkillException: If skill already exists locally or in database (409)
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")

        skill_name = skill_data.get("name")
        if not skill_name:
            raise SkillException("Skill name is required")

        # Check if skill already exists in database
        existing = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
        if existing:
            raise SkillException(f"Skill '{skill_name}' already exists")

        # Check if skill directory already exists locally
        resolved = self._resolve_local_skills_dir_for_overlay()
        if resolved and os.path.exists(os.path.join(resolved, skill_name)):
            raise SkillException(f"Skill '{skill_name}' already exists locally")

        # Set created_by and updated_by if user_id is provided
        if user_id:
            skill_data["created_by"] = user_id
            skill_data["updated_by"] = user_id

        try:
            # Create database record first
            result = skill_db.create_skill(skill_data, effective_tenant_id)

            # Create local skill file (SKILL.md)
            self.skill_manager.save_skill(skill_data)

            # Mirror DB config_schemas to config/config.yaml when present (same layout as ZIP uploads).
            if self.skill_manager.base_skills_dir and skill_data.get("config_schemas") is not None:
                try:
                    _write_skill_params_to_local_config_yaml(
                        skill_name,
                        _params_dict_to_storable(skill_data["config_schemas"]),
                        self.skill_manager.local_skills_dir,
                    )
                except Exception as exc:
                    logger.warning(
                        "Local config/config.yaml write failed after create for %s: %s",
                        skill_name,
                        exc,
                    )

            logger.info(f"Created skill '{skill_name}' with local files")
            return self._enrich_configs_from_yaml(result)
        except SkillException:
            raise
        except Exception as e:
            logger.error(f"Error creating skill: {e}")
            raise SkillException(f"Failed to create skill: {str(e)}") from e

    def create_skill_from_file(
        self,
        file_content: Union[bytes, str, io.BytesIO],
        skill_name: Optional[str] = None,
        file_type: str = "auto",
        source: str = "自定义",
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a skill from file content.

        Supports two formats:
        1. Single SKILL.md file - extracts metadata and saves directly
        2. ZIP archive - extracts SKILL.md and all other files/scripts

        Args:
            file_content: File content as bytes, string, or BytesIO
            skill_name: Optional skill name (extracted from ZIP if not provided)
            file_type: File type hint - "md", "zip", or "auto" (detect)
            source: Source identifier for the skill (e.g., "自定义", "官方", "导入")
            tenant_id: Tenant ID for skill isolation. Uses instance tenant_id if not provided.
            user_id: User ID of the creator

        Returns:
            Created skill dict
        """
        effective_tenant_id = tenant_id or self.tenant_id
        content_bytes: bytes
        if isinstance(file_content, str):
            content_bytes = file_content.encode("utf-8")
        elif isinstance(file_content, io.BytesIO):
            content_bytes = file_content.getvalue()
        else:
            content_bytes = file_content

        if file_type == "auto":
            if content_bytes.startswith(b"PK"):
                file_type = "zip"
            else:
                file_type = "md"

        if file_type == "zip":
            return self._create_skill_from_zip(content_bytes, skill_name, source, user_id, effective_tenant_id)
        else:
            return self._create_skill_from_md(content_bytes, skill_name, source, user_id, effective_tenant_id)

    def _create_skill_from_md(
        self,
        content_bytes: bytes,
        skill_name: Optional[str] = None,
        source: str = "自定义",
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create skill from SKILL.md content."""
        content_str = content_bytes.decode("utf-8")

        try:
            skill_data = SkillLoader.parse(content_str)
        except ValueError as e:
            raise SkillException(f"Invalid SKILL.md format: {e}")

        name = skill_name or skill_data.get("name")
        if not name:
            raise SkillException("Skill name is required")

        # Check if skill already exists in database
        existing = skill_db.get_skill_by_name(name, tenant_id)
        if existing:
            raise SkillException(f"Skill '{name}' already exists")

        # Convert allowed_tools (from SKILL.md) to tool_ids for database
        allowed_tools = skill_data.get("allowed_tools", [])
        tool_ids = []
        if allowed_tools:
            tool_ids = skill_db.get_tool_ids_by_names(allowed_tools, tenant_id)

        skill_dict = {
            "name": name,
            "description": skill_data.get("description", ""),
            "content": skill_data.get("content", ""),
            "tags": skill_data.get("tags", []),
            "source": source,
            "tool_ids": tool_ids,
            "allowed-tools": allowed_tools,  # Preserve for local file sync
        }
        # Note: scripts/ reflection is only possible for ZIP uploads (scripts exist in ZIP bytes).
        # For MD-only uploads there are no scripts to reflect at create time.

        # Set created_by and updated_by if user_id is provided
        if user_id:
            skill_dict["created_by"] = user_id
            skill_dict["updated_by"] = user_id

        result = skill_db.create_skill(skill_dict, tenant_id)

        # Write SKILL.md to local storage
        self.skill_manager.save_skill(skill_dict)

        return self._enrich_configs_from_yaml(result)

    def _create_skill_from_zip(
        self,
        zip_bytes: bytes,
        skill_name: Optional[str] = None,
        source: str = "自定义",
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create skill from ZIP archive (for file storage, content extracted from SKILL.md).

        Priority for skill_name:
        1. Parameter skill_name
        2. Root directory SKILL.md (top-level skill_name field)
        3. Subdirectory name containing SKILL.md
        """
        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                file_list = zf.namelist()
        except zipfile.BadZipFile:
            raise SkillException("Invalid ZIP archive")

        zip_stream.seek(0)

        skill_md_path: Optional[str] = None
        detected_skill_name: Optional[str] = None

        # First: Check for SKILL.md at root level
        for file_path in file_list:
            if file_path.endswith("/"):
                continue
            normalized_path = file_path.replace("\\", "/")
            parts = normalized_path.split("/")
            # Root level SKILL.md (only 1 part)
            if len(parts) == 1 and parts[0].lower() == "skill.md":
                skill_md_path = file_path
                break

        # Second: If not found at root, check subdirectory
        if not skill_md_path:
            for file_path in file_list:
                if file_path.endswith("/"):
                    continue
                normalized_path = file_path.replace("\\", "/")
                parts = normalized_path.split("/")
                if len(parts) >= 2 and parts[-1].lower() == "skill.md":
                    skill_md_path = file_path
                    detected_skill_name = parts[0]
                    break

        if not skill_md_path:
            raise SkillException("SKILL.md not found in ZIP archive")

        name = skill_name or detected_skill_name
        if not name:
            raise SkillException("Skill name is required")

        # Check if skill already exists in database
        existing = skill_db.get_skill_by_name(name, tenant_id)
        if existing:
            raise SkillException(f"Skill '{name}' already exists")

        with zipfile.ZipFile(zip_stream, "r") as zf:
            skill_content = zf.read(skill_md_path).decode("utf-8")

        try:
            skill_data = SkillLoader.parse(skill_content)
        except ValueError as e:
            raise SkillException(f"Invalid SKILL.md in ZIP: {e}")

        # If still no name, try to get from SKILL.md parsed data
        if not name:
            name = skill_data.get("name")

        if not name:
            raise SkillException("Skill name is required")

        # Convert allowed_tools (from SKILL.md) to tool_ids for database
        allowed_tools = skill_data.get("allowed_tools", [])
        tool_ids = []
        if allowed_tools:
            tool_ids = skill_db.get_tool_ids_by_names(allowed_tools, tenant_id)

        skill_dict = {
            "name": name,
            "description": skill_data.get("description", ""),
            "content": skill_data.get("content", ""),
            "tags": skill_data.get("tags", []),
            "source": source,
            "tool_ids": tool_ids,
            "allowed-tools": allowed_tools,  # Preserve for local file sync
        }

        preferred_root = detected_skill_name or name

        # Priority: schema.yaml (list metadata) > scripts AST (list) > config.yaml (dict defaults)
        schema_from_zip = _read_schema_yaml_from_zip(zip_bytes, preferred_root)
        inputs_from_scripts = _get_skill_inputs_from_zip(
            zip_bytes,
            preferred_skill_root=preferred_root,
        )
        params_from_zip = _read_params_from_zip_config_yaml(
            zip_bytes,
            preferred_skill_root=preferred_root,
        )

        if schema_from_zip:
            skill_dict["config_schemas"] = schema_from_zip
        elif inputs_from_scripts:
            skill_dict["config_schemas"] = inputs_from_scripts

        # config.yaml always goes into config_values (runtime defaults dict)
        if params_from_zip is not None:
            skill_dict["config_values"] = params_from_zip

        # Set created_by and updated_by if user_id is provided
        if user_id:
            skill_dict["created_by"] = user_id
            skill_dict["updated_by"] = user_id

        result = skill_db.create_skill(skill_dict, tenant_id)

        # Save SKILL.md to local storage
        self.skill_manager.save_skill(skill_dict)

        self._upload_zip_files(zip_bytes, name, detected_skill_name)

        return self._enrich_configs_from_yaml(result)

    def _delete_local_skill_files(self, skill_name: str) -> None:
        """Delete all files within a skill's local directory, preserving the directory itself.

        Args:
            skill_name: Name of the skill whose local files should be deleted.
        """
        import shutil

        local_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
        logger.info("Starting deletion of local files for skill '%s' from '%s'", skill_name, local_dir)

        if not os.path.isdir(local_dir):
            logger.info("Local skill directory does not exist, nothing to delete: %s", local_dir)
            return
        try:
            items = os.listdir(local_dir)
            logger.info("Found %d items to delete in '%s'", len(items), local_dir)

            for item in items:
                item_path = os.path.join(local_dir, item)
                if item_path.endswith("/"):
                    continue
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    logger.debug("Deleted directory: %s", item_path)
                else:
                    os.remove(item_path)
                    logger.debug("Deleted file: %s", item_path)
            logger.info("Successfully deleted all local files for skill '%s'", skill_name)
        except Exception as e:
            logger.error("Failed to delete local files for skill '%s': %s", skill_name, e)

    def _upload_zip_files(
        self,
        zip_bytes: bytes,
        skill_name: str,
        original_folder_name: Optional[str] = None
    ) -> None:
        """Extract ZIP files to local storage only.

        Args:
            zip_bytes: ZIP archive content
            skill_name: Target skill name (for local directory)
            original_folder_name: Original folder name in ZIP (if different from skill_name)
        """
        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                file_list = zf.namelist()
        except zipfile.BadZipFile:
            raise SkillException("Invalid ZIP archive")

        # Determine if this ZIP has a subdirectory structure or root-level structure.
        # Root-level: SKILL.md is at root (e.g., "SKILL.md", "script/analyze.py") -> no stripping
        # Subdirectory: SKILL.md is inside a folder (e.g., "my-skill/SKILL.md") -> strip folder prefix
        needs_rename = (
            original_folder_name is not None
            and original_folder_name != skill_name
        )

        has_root_skill_md = any(
            not fp.endswith("/")
            and fp.replace("\\", "/").split("/")[0].lower() == "skill.md"
            for fp in file_list
        )

        logger.info(
            "Starting ZIP extraction for skill '%s': needs_rename=%s, original_folder='%s', has_root_skill_md=%s",
            skill_name, needs_rename, original_folder_name, has_root_skill_md
        )

        zip_stream.seek(0)
        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                logger.info("ZIP contains %d entries for skill '%s'", len(file_list), skill_name)

                extracted_count = 0
                for file_path in file_list:
                    if file_path.endswith("/"):
                        continue

                    normalized_path = file_path.replace("\\", "/")
                    parts = normalized_path.split("/")

                    # Calculate target relative path
                    # Only strip the first component when the ZIP has a subdirectory structure
                    # (SKILL.md is inside a folder, not at root level)
                    if needs_rename and len(parts) >= 2 and parts[0] == original_folder_name:
                        relative_path = parts[0].replace(original_folder_name, skill_name) + "/" + "/".join(parts[1:])
                    elif len(parts) >= 2 and not has_root_skill_md:
                        # Strip first component (ZIP has subdirectory structure without root SKILL.md)
                        relative_path = "/".join(parts[1:])
                    else:
                        relative_path = normalized_path

                    if not relative_path:
                        continue

                    file_data = zf.read(file_path)

                    local_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
                    normalized_relative = relative_path.replace("/", os.sep).replace("\\", os.sep)
                    local_path = os.path.normpath(os.path.join(local_dir, normalized_relative))
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(file_data)
                    extracted_count += 1
                    logger.debug("Extracted file '%s' -> '%s'", file_path, local_path)

            logger.info(
                "Completed ZIP extraction for skill '%s': %d files extracted to '%s'",
                skill_name, extracted_count, self.skill_manager.local_skills_dir
            )
        except Exception as e:
            logger.error("Failed to extract ZIP files for skill '%s': %s", skill_name, e)
            raise

    def update_skill_from_file(
        self,
        skill_name: str,
        file_content: Union[bytes, str, io.BytesIO],
        file_type: str = "auto",
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update an existing skill from file content.

        Args:
            skill_name: Name of the skill to update
            file_content: File content as bytes, string, or BytesIO
            file_type: File type hint - "md", "zip", or "auto" (detect)
            tenant_id: Tenant ID (reserved for future multi-tenant support)
            user_id: User ID of the updater

        Returns:
            Updated skill dict
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        existing = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
        if not existing:
            raise SkillException(f"Skill not found: {skill_name}")

        content_bytes: bytes
        if isinstance(file_content, str):
            content_bytes = file_content.encode("utf-8")
        elif isinstance(file_content, io.BytesIO):
            content_bytes = file_content.getvalue()
        else:
            content_bytes = file_content

        if file_type == "auto":
            if content_bytes.startswith(b"PK"):
                file_type = "zip"
            else:
                file_type = "md"

        if file_type == "zip":
            return self._update_skill_from_zip(content_bytes, skill_name, user_id, effective_tenant_id)
        else:
            return self._update_skill_from_md(content_bytes, skill_name, user_id, effective_tenant_id)

    def _update_skill_from_md(
        self,
        content_bytes: bytes,
        skill_name: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update skill from SKILL.md content."""
        content_str = content_bytes.decode("utf-8")

        try:
            skill_data = SkillLoader.parse(content_str)
        except ValueError as e:
            raise SkillException(f"Invalid SKILL.md format: {e}")

        # Get allowed-tools from parsed content and try to map to tool_ids
        allowed_tools = skill_data.get("allowed_tools", [])
        tool_ids = []
        if allowed_tools:
            tool_ids = skill_db.get_tool_ids_by_names(allowed_tools, tenant_id)

        skill_dict = {
            "description": skill_data.get("description", ""),
            "content": skill_data.get("content", ""),
            "tags": skill_data.get("tags", []),
            "tool_ids": tool_ids,
        }

        result = skill_db.update_skill(
            skill_name, skill_dict, tenant_id, updated_by=user_id or None
        )

        # Clean up existing local files before writing new ones
        self._delete_local_skill_files(skill_name)

        # Update local storage with new SKILL.md (preserve allowed-tools)
        skill_dict["name"] = skill_name
        skill_dict["allowed-tools"] = allowed_tools
        self.skill_manager.save_skill(skill_dict)

        return self._enrich_configs_from_yaml(result)

    def _update_skill_from_zip(
        self,
        zip_bytes: bytes,
        skill_name: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update skill from ZIP archive."""
        existing = skill_db.get_skill_by_name(skill_name, tenant_id)
        if not existing:
            raise SkillException(f"Skill not found: {skill_name}")

        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        skill_md_path = None
        original_folder_name = None

        with zipfile.ZipFile(zip_stream, "r") as zf:
            file_list = zf.namelist()

            for file_path in file_list:
                normalized_path = file_path.replace("\\", "/")
                if normalized_path.lower().endswith("skill.md"):
                    parts = normalized_path.split("/")
                    if len(parts) >= 2:
                        skill_md_path = file_path
                        original_folder_name = parts[0]
                        break

            skill_content = None
            if skill_md_path:
                skill_content = zf.read(skill_md_path).decode("utf-8")

        # Reset stream position before _upload_zip_files reads it
        zip_stream.seek(0)

        preferred_root = original_folder_name or skill_name
        params_from_zip = _read_params_from_zip_config_yaml(
            zip_bytes,
            preferred_skill_root=preferred_root,
        )

        skill_dict = {}
        allowed_tools = []
        if skill_content:
            try:
                skill_data = SkillLoader.parse(skill_content)
                allowed_tools = skill_data.get("allowed_tools", [])
                # Try to map allowed_tools to tool_ids for database
                tool_ids = []
                if allowed_tools:
                    tool_ids = skill_db.get_tool_ids_by_names(allowed_tools, tenant_id)
                skill_dict = {
                    "description": skill_data.get("description", ""),
                    "content": skill_data.get("content", ""),
                    "tags": skill_data.get("tags", []),
                    "tool_ids": tool_ids,
                }
            except ValueError as e:
                logger.warning(f"Could not parse SKILL.md from ZIP: {e}")

        if params_from_zip is not None:
            skill_dict["config_values"] = params_from_zip

        result = skill_db.update_skill(
            skill_name, skill_dict, tenant_id, updated_by=user_id or None
        )

        # Clean up existing local files before writing new ones
        self._delete_local_skill_files(skill_name)

        # Update SKILL.md in local storage (preserve allowed-tools)
        skill_dict["name"] = skill_name
        skill_dict["allowed-tools"] = allowed_tools
        self.skill_manager.save_skill(skill_dict)

        # Update other files in local storage
        self._upload_zip_files(zip_bytes, skill_name, original_folder_name)

        return self._enrich_configs_from_yaml(result)

    def update_skill(
        self,
        skill_name: str,
        skill_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update an existing skill for a tenant.

        Args:
            skill_name: Name of the skill to update
            skill_data: Business fields from the application layer (no audit fields).
            tenant_id: Tenant ID for skill isolation. Uses instance tenant_id if not provided.
            user_id: Updater id from server-side auth (JWT / session); sets DB updated_by.

        Returns:
            Updated skill dict
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        try:
            existing = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
            if not existing:
                raise SkillException(f"Skill not found: {skill_name}")

            result = skill_db.update_skill(
                skill_name, skill_data, effective_tenant_id, updated_by=user_id or None
            )

            # Keep config/config.yaml in sync when config_values are updated (matches ZIP import path).
            local_dir = self.skill_manager.local_skills_dir or CONTAINER_SKILLS_PATH
            if local_dir and "config_values" in skill_data:
                try:
                    raw_config_values = skill_data["config_values"]
                    if raw_config_values is None:
                        _remove_local_skill_config_yaml(skill_name, local_dir)
                    else:
                        _write_skill_params_to_local_config_yaml(
                            skill_name,
                            _params_dict_to_storable(raw_config_values),
                            local_dir,
                        )
                except Exception as exc:
                    logger.warning(
                        "Local config/config.yaml sync failed after config_values update for %s: %s",
                        skill_name,
                        exc,
                    )

            # Optional: sync SKILL.md on disk when SKILLS_PATH is configured (DB is source of truth).
            if not local_dir:
                logger.warning(
                    "SKILLS_PATH is not set; skipped local SKILL.md sync after DB update for %s",
                    skill_name,
                )
                return self._enrich_configs_from_yaml(result)

            try:
                allowed_tools = skill_db.get_tool_names_by_skill_name(skill_name, effective_tenant_id)
                local_skill_dict = {
                    "name": skill_name,
                    "description": skill_data.get("description", existing.get("description", "")),
                    "content": skill_data.get("content", existing.get("content", "")),
                    "tags": skill_data.get("tags", existing.get("tags", [])),
                    "allowed-tools": allowed_tools,
                    "files": skill_data.get("files", []),
                }
                self.skill_manager.save_skill(local_skill_dict)
            except Exception as exc:
                logger.warning(
                    "Local SKILL.md sync failed after DB update for %s: %s",
                    skill_name,
                    exc,
                )

            return self._enrich_configs_from_yaml(result)
        except SkillException:
            raise
        except Exception as e:
            logger.error(f"Error updating skill {skill_name}: {e}")
            raise SkillException(f"Failed to update skill: {str(e)}") from e

    def delete_skill(
        self,
        skill_name: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """Delete a skill for a tenant.

        Args:
            skill_name: Name of the skill to delete
            tenant_id: Tenant ID for skill isolation. Uses instance tenant_id if not provided.
            user_id: User ID of the user performing the delete

        Returns:
            True if deleted successfully
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            raise SkillException("tenant_id is required")
        try:
            # Delete local skill files from filesystem
            skill_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
            if os.path.exists(skill_dir):
                import shutil
                shutil.rmtree(skill_dir)
                logger.info(f"Deleted skill directory: {skill_dir}")

            # Delete from database (soft delete with updated_by)
            return skill_db.delete_skill(skill_name, effective_tenant_id, updated_by=user_id)
        except Exception as e:
            logger.error(f"Error deleting skill {skill_name}: {e}")
            raise SkillException(f"Failed to delete skill: {str(e)}") from e


    def get_enabled_skills_for_agent(
        self,
        agent_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> List[Dict[str, Any]]:
        """Get enabled skills for a specific agent from SkillInstance table.

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            version_no: Version number for fetching skill instances

        Returns:
            List of enabled skill dicts
        """
        try:
            enabled_skills = skill_db.search_skills_for_agent(
                agent_id=agent_id,
                tenant_id=tenant_id,
                version_no=version_no
            )

            result = []
            for skill_instance in enabled_skills:
                skill_id = skill_instance.get("skill_id")
                skill = skill_db.get_skill_by_id(skill_id, tenant_id)
                if skill:
                    # Get skill info from ag_skill_info_t (repository returns keys: name, description, content)
                    merged = {
                        "skill_id": skill_id,
                        "name": skill.get("name"),
                        "description": skill.get("description", ""),
                        "content": skill.get("content", ""),
                        "enabled": skill_instance.get("enabled", True),
                        "tool_ids": skill.get("tool_ids", []),
                    }
                    result.append(merged)

            return result
        except Exception as e:
            logger.error(f"Error getting enabled skills for agent: {e}")
            raise SkillException(f"Failed to get enabled skills: {str(e)}") from e

    def load_skill_directory(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Load entire skill directory including scripts.

        Args:
            skill_name: Name of the skill

        Returns:
            Dict with skill metadata and local directory path, or None if not found
        """
        try:
            return self.skill_manager.load_skill_directory(skill_name)
        except Exception as e:
            logger.error(f"Error loading skill directory {skill_name}: {e}")
            raise SkillException(f"Failed to load skill directory: {str(e)}") from e

    def get_skill_scripts(self, skill_name: str) -> List[str]:
        """Get list of executable scripts in skill.

        Args:
            skill_name: Name of the skill

        Returns:
            List of script file paths
        """
        try:
            return self.skill_manager.get_skill_scripts(skill_name)
        except Exception as e:
            logger.error(f"Error getting skill scripts {skill_name}: {e}")
            raise SkillException(f"Failed to get skill scripts: {str(e)}") from e

    def build_skills_summary(
        self,
        available_skills: Optional[List[str]] = None,
        agent_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        version_no: int = 0
    ) -> str:
        """Build skills summary with whitelist filter for prompt injection.

        Args:
            available_skills: Optional whitelist of skill names to include.
                             If provided, only skills in this list will be included.
            agent_id: Agent ID for fetching skill instances
            tenant_id: Tenant ID for fetching skill instances
            version_no: Version number for fetching skill instances

        Returns:
            XML-formatted skills summary
        """
        try:
            skills_to_include = []

            if agent_id and tenant_id:
                # Get skills from SkillInstance table
                agent_skills = skill_db.search_skills_for_agent(
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    version_no=version_no
                )

                for skill_instance in agent_skills:
                    skill_id = skill_instance.get("skill_id")
                    skill = skill_db.get_skill_by_id(skill_id, tenant_id)
                    if skill:
                        if available_skills is not None and skill.get("name") not in available_skills:
                            continue
                        # Get skill info from ag_skill_info_t (repository returns keys: name, description)
                        skills_to_include.append({
                            "name": skill.get("name"),
                            "description": skill.get("description", ""),
                        })
            else:
                # Fallback: use all skills from the current tenant
                effective_tenant_id = tenant_id or self.tenant_id
                if effective_tenant_id:
                    all_skills = skill_db.list_skills(effective_tenant_id)
                else:
                    all_skills = []
                skills_to_include = all_skills
                if available_skills is not None:
                    available_set = set(available_skills)
                    skills_to_include = [s for s in all_skills if s.get("name") in available_set]

            if not skills_to_include:
                return ""

            def escape_xml(s: str) -> str:
                if s is None:
                    return ""
                return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            lines = ["<skills>"]
            for skill in skills_to_include:
                name = escape_xml(skill.get("name", ""))
                description = escape_xml(skill.get("description", ""))

                lines.append(f'  <skill>')
                lines.append(f'    <name>{name}</name>')
                lines.append(f'    <description>{description}</description>')
                lines.append(f'  </skill>')

            lines.append("</skills>")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Error building skills summary: {e}")
            raise SkillException(f"Failed to build skills summary: {str(e)}") from e

    def get_skill_content(self, skill_name: str, tenant_id: Optional[str] = None) -> str:
        """Get skill content for runtime loading.

        Args:
            skill_name: Name of the skill to load
            tenant_id: Tenant ID for filtering. Uses instance tenant_id if not provided.

        Returns:
            Skill content in markdown format
        """
        effective_tenant_id = tenant_id or self.tenant_id
        if not effective_tenant_id:
            return ""
        try:
            skill = skill_db.get_skill_by_name(skill_name, effective_tenant_id)
            return skill.get("content", "") if skill else ""
        except Exception as e:
            logger.error(f"Error getting skill content {skill_name}: {e}")
            raise SkillException(f"Failed to get skill content: {str(e)}") from e

    def get_skill_file_tree(
        self,
        skill_name: str,
        tenant_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get file tree structure of a skill.

        Args:
            skill_name: Name of the skill
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            Dict with file tree structure, or None if not found
        """
        try:
            return self.skill_manager.get_skill_file_tree(skill_name)
        except Exception as e:
            logger.error(f"Error getting skill file tree: {e}")
            raise SkillException(f"Failed to get skill file tree: {str(e)}") from e

    def get_skill_file_content(
        self,
        skill_name: str,
        file_path: str,
        tenant_id: Optional[str] = None
    ) -> Optional[str]:
        """Get content of a specific file within a skill.

        Args:
            skill_name: Name of the skill
            file_path: Relative path to the file within the skill directory
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            File content as string, or None if file not found
        """
        try:
            local_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
            normalized_file_path = file_path.replace("/", os.sep).replace("\\", os.sep)
            full_path = os.path.normpath(os.path.join(local_dir, normalized_file_path))

            if not os.path.exists(full_path):
                logger.warning(f"File not found: {full_path}")
                return None

            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading skill file {skill_name}/{file_path}: {e}")
            raise SkillException(f"Failed to read skill file: {str(e)}") from e

    # ============== Skill Instance Methods ==============

    def create_or_update_skill_instance(
        self,
        skill_info,
        tenant_id: str,
        user_id: str,
        version_no: int = 0
    ):
        """Create or update a skill instance for an agent.

        Args:
            skill_info: Skill instance information (SkillInstanceInfoRequest or dict)
            tenant_id: Tenant ID
            user_id: User ID (will be set as created_by/updated_by)
            version_no: Version number (default 0 for draft)

        Returns:
            Created or updated skill instance dict
        """
        from database import skill_db as skill_db_module
        return skill_db_module.create_or_update_skill_by_skill_info(
            skill_info=skill_info,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no
        )

    def list_skill_instances(
        self,
        agent_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> List[Dict[str, Any]]:
        """List all skill instances for an agent.

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            version_no: Version number (default 0 for draft)

        Returns:
            List of skill instance dicts
        """
        from database import skill_db as skill_db_module
        return skill_db_module.query_skill_instances_by_agent_id(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )

    def get_skill_instance(
        self,
        agent_id: int,
        skill_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> Optional[Dict[str, Any]]:
        """Get a specific skill instance for an agent.

        Args:
            agent_id: Agent ID
            skill_id: Skill ID
            tenant_id: Tenant ID
            version_no: Version number (default 0 for draft)

        Returns:
            Skill instance dict or None if not found
        """
        from database import skill_db as skill_db_module
        return skill_db_module.query_skill_instance_by_id(
            agent_id=agent_id,
            skill_id=skill_id,
            tenant_id=tenant_id,
            version_no=version_no
        )

    def create_skill_from_zip_bytes(
        self,
        zip_bytes: bytes,
        skill_name: Optional[str] = None,
        source: str = "导入",
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        skip_duplicate_check: bool = False
    ) -> Dict[str, Any]:
        """Create a skill from ZIP bytes, optionally skipping the duplicate name check.

        This is the shared implementation used by both the upload endpoint and the
        agent import flow. When skip_duplicate_check is True, the existence check
        is bypassed (used during agent import where we pre-validate duplicates).

        Args:
            zip_bytes: Raw ZIP file bytes
            skill_name: Optional skill name override
            source: Source label for the skill
            user_id: Creator user ID
            tenant_id: Tenant ID
            skip_duplicate_check: If True, skip the "skill already exists" check

        Returns:
            Created skill dict
        """
        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                file_list = zf.namelist()
        except zipfile.BadZipFile:
            raise SkillException("Invalid ZIP archive")

        zip_stream.seek(0)

        skill_md_path: Optional[str] = None
        detected_skill_name: Optional[str] = None

        for file_path in file_list:
            if file_path.endswith("/"):
                continue
            normalized_path = file_path.replace("\\", "/")
            parts = normalized_path.split("/")
            if len(parts) == 1 and parts[0].lower() == "skill.md":
                skill_md_path = file_path
                break

        if not skill_md_path:
            for file_path in file_list:
                if file_path.endswith("/"):
                    continue
                normalized_path = file_path.replace("\\", "/")
                parts = normalized_path.split("/")
                if len(parts) >= 2 and parts[-1].lower() == "skill.md":
                    skill_md_path = file_path
                    detected_skill_name = parts[0]
                    break

        if not skill_md_path:
            raise SkillException("SKILL.md not found in ZIP archive")

        name = skill_name or detected_skill_name
        if not name:
            raise SkillException("Skill name is required")

        if not skip_duplicate_check:
            existing = skill_db.get_skill_by_name(name, tenant_id)
            if existing:
                raise SkillException(f"Skill '{name}' already exists")

        with zipfile.ZipFile(zip_stream, "r") as zf:
            skill_content = zf.read(skill_md_path).decode("utf-8")

        try:
            skill_data = SkillLoader.parse(skill_content)
        except ValueError as e:
            raise SkillException(f"Invalid SKILL.md in ZIP: {e}")

        if not name:
            name = skill_data.get("name")

        if not name:
            raise SkillException("Skill name is required")

        allowed_tools = skill_data.get("allowed_tools", [])
        tool_ids = []
        if allowed_tools:
            tool_ids = skill_db.get_tool_ids_by_names(allowed_tools, tenant_id)

        skill_dict = {
            "name": name,
            "description": skill_data.get("description", ""),
            "content": skill_data.get("content", ""),
            "tags": skill_data.get("tags", []),
            "source": source,
            "tool_ids": tool_ids,
            "allowed-tools": allowed_tools,
        }

        preferred_root = detected_skill_name or name

        schema_from_zip = _read_schema_yaml_from_zip(zip_bytes, preferred_root)
        inputs_from_scripts = _get_skill_inputs_from_zip(
            zip_bytes,
            preferred_skill_root=preferred_root,
        )
        params_from_zip = _read_params_from_zip_config_yaml(
            zip_bytes,
            preferred_skill_root=preferred_root,
        )

        if schema_from_zip:
            skill_dict["config_schemas"] = schema_from_zip
        elif inputs_from_scripts:
            skill_dict["config_schemas"] = inputs_from_scripts

        if params_from_zip is not None:
            skill_dict["config_values"] = params_from_zip

        if user_id:
            skill_dict["created_by"] = user_id
            skill_dict["updated_by"] = user_id

        result = skill_db.create_skill(skill_dict, tenant_id)

        self.skill_manager.save_skill(skill_dict)

        self._upload_zip_files(zip_bytes, name, detected_skill_name)

        return self._enrich_configs_from_yaml(result)

    def export_skills_by_names(
        self,
        skill_names: List[str],
        tenant_id: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Export skills as ZIP files by name.

        Packages the entire skill directory (SKILL.md, scripts/, assets/, config/)
        into a ZIP for each skill name.

        Args:
            skill_names: List of skill names to export
            tenant_id: Tenant ID for skill lookup

        Returns:
            List of dicts with skill_name and skill_zip_base64
        """
        import base64

        effective_tenant_id = tenant_id or self.tenant_id
        results: List[Dict[str, str]] = []

        for skill_name in skill_names:
            skill_dir = os.path.join(
                self.skill_manager.local_skills_dir or CONTAINER_SKILLS_PATH,
                skill_name
            )
            if not os.path.isdir(skill_dir):
                logger.warning(f"Skill directory not found for export: {skill_name}")
                continue

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(skill_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, skill_dir)
                        arcname = os.path.join(skill_name, rel_path)
                        zf.write(file_path, arcname)

            zip_buffer.seek(0)
            zip_base64 = base64.b64encode(zip_buffer.read()).decode("utf-8")
            results.append({
                "skill_name": skill_name,
                "skill_zip_base64": zip_base64
            })

        return results


def classify_streaming_content(
    content: str,
    classifier: Any
) -> List[Dict[str, Any]]:
    """Classify streaming content using the ContentClassifier.

    Args:
        content: Raw streaming content to classify
        classifier: ContentClassifier instance

    Returns:
        List of classified event dictionaries
    """
    return classifier.classify(content)


class SkillCreationStreamService:
    """Service for handling skill creation streaming operations."""

    def __init__(self, skill_service: Optional["SkillService"] = None):
        """Initialize the stream service.

        Args:
            skill_service: Optional SkillService instance for accessing skill manager
        """
        self.skill_service = skill_service or SkillService()

    def get_skill_manager_local_dir(self) -> str:
        """Get local_skills_dir from SkillManager.

        Returns:
            Local skills directory path
        """
        return self.skill_service.skill_manager.local_skills_dir or ""

    def create_classifier(self) -> "ContentClassifier":
        """Create a new ContentClassifier instance.

        Returns:
            New ContentClassifier instance
        """
        from utils.content_classifier_utils import ContentClassifier
        return ContentClassifier()

    def classify_content(
        self,
        content: str,
        classifier: "ContentClassifier"
    ) -> List[Dict[str, Any]]:
        """Classify streaming content using the provided classifier.

        Args:
            content: Raw streaming content to classify
            classifier: ContentClassifier instance

        Returns:
            List of classified event dictionaries
        """
        return classifier.classify(content)


def create_skill_creation_stream_generator(
    observer: Any,
    classifier: "ContentClassifier",
) -> Any:
    """Create a generator that processes observer messages and yields SSE events.

    Args:
        observer: MessageObserver instance with cached messages
        classifier: ContentClassifier instance for content classification

    Yields:
        SSE-formatted event strings
    """
    import json
    from consts.const import STREAMABLE_CONTENT_TYPES

    cached = observer.get_cached_message()
    for msg in cached:
        if isinstance(msg, str):
            try:
                data = json.loads(msg)
                msg_type = data.get("type", "")
                content = data.get("content", "")

                if msg_type == "step_count":
                    yield f"data: {json.dumps({'type': 'step_count', 'content': content}, ensure_ascii=False)}\n\n"
                elif msg_type in STREAMABLE_CONTENT_TYPES:
                    for event in classifier.classify(content):
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except (json.JSONDecodeError, Exception):
                pass


def format_final_answer_sse(classifier: "ContentClassifier", final_result: str) -> List[str]:
    """Format final answer content into SSE event strings.

    Args:
        classifier: ContentClassifier instance for content classification
        final_result: Final answer content to format

    Returns:
        List of SSE-formatted event strings
    """
    import json

    events = []
    for event in classifier.classify(final_result):
        events.append(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
    return events


# ========== Skill Creation Task Manager ==========


class SkillCreationTaskManager:
    """Singleton manager to track active skill creation threads and their stop events."""

    _instance: Optional["SkillCreationTaskManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SkillCreationTaskManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Tuple[threading.Thread, threading.Event]] = {}
                    cls._instance._tasks_lock = threading.Lock()
        return cls._instance

    def register_task(self, task_id: str, thread: threading.Thread, stop_event: threading.Event) -> None:
        """Register a new skill creation task.

        Args:
            task_id: Unique identifier for the task
            thread: The thread running the skill creation
            stop_event: Event to signal stop request
        """
        with self._tasks_lock:
            self._tasks[task_id] = (thread, stop_event)
            logger.info(f"Registered skill creation task: {task_id}")

    def unregister_task(self, task_id: str) -> None:
        """Unregister a completed skill creation task.

        Args:
            task_id: Unique identifier for the task
        """
        with self._tasks_lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                logger.info(f"Unregistered skill creation task: {task_id}")

    def stop_task(self, task_id: str) -> bool:
        """Signal a skill creation task to stop.

        Args:
            task_id: Unique identifier for the task

        Returns:
            True if the task was found and stop was signaled, False otherwise
        """
        with self._tasks_lock:
            if task_id in self._tasks:
                _, stop_event = self._tasks[task_id]
                stop_event.set()
                logger.info(f"Stop signal sent for skill creation task: {task_id}")
                return True
        return False

    def is_task_running(self, task_id: str) -> bool:
        """Check if a task is still running.

        Args:
            task_id: Unique identifier for the task

        Returns:
            True if the task exists and is still alive
        """
        with self._tasks_lock:
            if task_id in self._tasks:
                thread, _ = self._tasks[task_id]
                return thread.is_alive()
        return False


# Singleton instance
skill_creation_task_manager = SkillCreationTaskManager()


# ========== Skill Creation Stream Service ==========


def stream_skill_creation(
    user_request: str,
    language: str,
    model_config: "ModelConfig",
    existing_skill: Optional[Dict[str, Any]] = None,
    complexity: str = "simple",
) -> tuple[str, Any]:
    """Stream skill creation process as an async generator.

    This function handles all the business logic for skill creation:
    - Loads prompt template
    - Creates observer, stop_event, and classifier
    - Registers the task with the task manager
    - Starts the agent thread
    - Yields SSE events until completion

    Args:
        user_request: User's skill description request
        language: Language code (e.g., "zh", "en")
        model_config: Model configuration
        existing_skill: Optional existing skill for modification
        complexity: Skill complexity level ("simple" or "complicated")

    Returns:
        Tuple of (task_id, generator_function)
        The task_id should be passed to the caller for stop functionality
    """
    task_id = str(uuid.uuid4())

    async def generate():
        is_task_registered = False
        observer = None
        classifier = None

        try:
            # Load prompt template
            template = get_skill_creation_simple_prompt_template(
                language=language,
                existing_skill=existing_skill,
                complexity=complexity
            )

            # Create observer and classifier
            observer = MessageObserver(lang=language)
            stop_event = threading.Event()
            classifier = ContentClassifier()

            # Get local skills directory
            local_skills_dir = SkillService().skill_manager.local_skills_dir or ""

            def run_task():
                create_skill_from_request(
                    system_prompt=template.get("system_prompt", ""),
                    user_prompt=user_request,
                    model_config_list=[model_config],
                    observer=observer,
                    stop_event=stop_event,
                    local_skills_dir=local_skills_dir
                )

            thread = threading.Thread(target=run_task)

            # Register task before starting
            skill_creation_task_manager.register_task(task_id, thread, stop_event)
            is_task_registered = True

            thread.start()

            while thread.is_alive():
                for event in create_skill_creation_stream_generator(observer, classifier):
                    yield event
                await asyncio.sleep(0.1)

            thread.join()

            for event in create_skill_creation_stream_generator(observer, classifier):
                yield event

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"Error in stream_skill_creation: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            if is_task_registered:
                skill_creation_task_manager.unregister_task(task_id)

    return task_id, generate


# ============== Skill List Initialization ==============


async def init_skill_list_for_tenant(tenant_id: str, user_id: str):
    """Initialize skill list for a new tenant by scanning local skill directories.

    Mirrors init_tool_list_for_tenant() in tool_configuration_service.py.

    Args:
        tenant_id: Tenant ID for the new tenant
        user_id: User ID for tracking who initiated the scan

    Returns:
        Dictionary containing initialization result
    """
    from database import skill_db as skill_db_module

    if skill_db_module.check_skill_list_initialized(tenant_id):
        logger.info(f"Skill list already initialized for tenant {tenant_id}, skipping")
        return {"status": "already_initialized", "message": "Skill list already exists"}

    logger.info(f"Initializing skill list for new tenant: {tenant_id}")
    await update_skill_list(tenant_id=tenant_id, user_id=user_id)
    return {"status": "success", "message": "Skill list initialized successfully"}


async def update_skill_list(tenant_id: str, user_id: str):
    """Scan local skill directories and update ag_skill_info_t.

    Mirrors update_tool_list() in tool_configuration_service.py.

    Args:
        tenant_id: Tenant ID for the tenant
        user_id: User ID for tracking who initiated the scan
    """
    from database import skill_db as skill_db_module
    from nexent.skills import SkillManager

    skill_manager = SkillManager(base_skills_dir=CONTAINER_SKILLS_PATH, tenant_id=tenant_id)
    # Use the resolved tenant-scoped local path for schema/config file reading
    local_base = skill_manager.local_skills_dir or CONTAINER_SKILLS_PATH
    scanned_skills = skill_manager.list_skills()

    skills_to_upsert = []
    for skill_info in scanned_skills:
        skill_name = skill_info.get("name")
        if not skill_name:
            continue

        skill_data = {
            "name": skill_name,
            "description": skill_info.get("description", ""),
            "tags": skill_info.get("tags", []),
            "source": "official",
        }

        try:
            full_skill = skill_manager.load_skill(skill_name)
            if full_skill:
                skill_data["content"] = full_skill.get("content", "")

            # Try schema.yaml first; fall back to AST-parsed scripts
            schema_path = _local_skill_schema_yaml_path(skill_name, local_base)
            if os.path.isfile(schema_path):
                async with aiofiles.open(schema_path, "rb") as f:
                    raw = await f.read()
                parsed = _parse_skill_schema_from_yaml_bytes(raw)
                skill_data["config_schemas"] = parsed
                logger.debug("Loaded config_schemas from schema.yaml for skill %s", skill_name)
            else:
                scripts_dir = os.path.join(local_base, skill_name, "scripts")
                inputs = _get_skill_inputs_from_code(scripts_dir)
                if inputs:
                    skill_data["config_schemas"] = inputs
        except Exception as e:
            logger.warning(f"Could not load full skill content for {skill_name}: {e}")
            skill_data["content"] = ""

        skills_to_upsert.append(skill_data)

    if skills_to_upsert:
        skill_db_module.upsert_scanned_skills(skills_to_upsert, user_id, tenant_id)
        logger.info(f"Upserted {len(skills_to_upsert)} skills for tenant {tenant_id}")
    else:
        logger.info(f"No skills found to upsert for tenant {tenant_id}")


def install_skills_for_tenant(
    skill_ids: List[int],
    tenant_id: str,
    user_id: Optional[str] = None
) -> List[int]:
    """Install specified official skills into a new tenant by copying their records.

    For each skill_id provided, finds the global template skill (official skill with
    NULL tenant_id) and creates a copy in ag_skill_info_t for the target tenant.
    Skills that cannot be found as global templates are skipped with a warning.

    Args:
        skill_ids: List of skill IDs to install for the tenant.
        tenant_id: Target tenant ID to install skills into.
        user_id: User ID for created_by/updated_by audit fields.

    Returns:
        List of skill IDs that were successfully installed.
    """
    from database import skill_db as skill_db_module

    if not skill_ids:
        return []

    installed_ids: List[int] = []
    for skill_id in skill_ids:
        try:
            template = skill_db_module.get_skill_by_id_global(skill_id)
            if not template:
                logger.warning(
                    f"Skill template with ID {skill_id} not found for installation "
                    f"into tenant {tenant_id}"
                )
                continue

            skill_name = template.get("name", "")
            if not skill_name:
                logger.warning(
                    f"Skill template {skill_id} has no name, skipping installation "
                    f"for tenant {tenant_id}"
                )
                continue

            existing = skill_db_module.get_skill_by_name(skill_name, tenant_id)
            if existing:
                logger.info(
                    f"Skill '{skill_name}' already exists for tenant {tenant_id}, skipping"
                )
                installed_ids.append(existing.get("skill_id"))
                continue

            skill_data = {
                "name": skill_name,
                "description": template.get("description", ""),
                "tags": template.get("tags", []),
                "content": template.get("content", ""),
                "config_schemas": template.get("config_schemas"),
                "config_values": template.get("config_values"),
                "source": template.get("source", "official"),
                "created_by": user_id,
                "updated_by": user_id,
            }
            result = skill_db_module.create_skill(skill_data, tenant_id)
            new_skill_id = result.get("skill_id")
            if new_skill_id:
                installed_ids.append(new_skill_id)
                logger.info(
                    f"Installed skill '{skill_name}' (ID {new_skill_id}) for tenant {tenant_id}"
                )
            else:
                logger.warning(
                    f"create_skill returned no skill_id for '{skill_name}', "
                    f"tenant {tenant_id}"
                )
        except Exception as e:
            logger.error(
                f"Failed to install skill ID {skill_id} into tenant {tenant_id}: {e}"
            )

    return installed_ids


def install_skills_from_zip_for_tenant(
    skill_names: List[str],
    tenant_id: str,
    user_id: Optional[str] = None,
    locale: Optional[str] = None
) -> List[str]:
    """Install official skills into a new tenant by reading ZIP files from OFFICIAL_SKILLS_ZIP_PATH.

    For each skill_name provided, derives the ZIP filename as <skill_name>.zip,
    reads the file from OFFICIAL_SKILLS_ZIP_PATH, and creates the skill via
    create_skill_from_file (which handles ZIP extraction, SKILL.md parsing,
    and database record creation).

    Skills that cannot be found as ZIP files are skipped with a warning.
    Skills that already exist for the tenant are skipped (not reinstalled).

    Args:
        skill_names: List of skill names to install (e.g. ["search-knowledge-base"]).
        tenant_id: Target tenant ID to install skills into.
        user_id: User ID for created_by/updated_by audit fields.
        locale: Frontend locale (e.g. "zh" or "en"). Determines the source label:
            "zh" → "官方", other locales → "official".

    Returns:
        List of skill names that were successfully installed.
    """
    if not skill_names:
        return []

    zip_dir = OFFICIAL_SKILLS_ZIP_PATH
    if not os.path.isdir(zip_dir):
        logger.warning(f"Official skills zip directory not found: {zip_dir}")
        return []

    # Derive source label from locale: zh → "官方", otherwise "official"
    source = "官方" if locale == "zh" else "official"

    installed: List[str] = []
    service = SkillService(tenant_id=tenant_id)

    for skill_name in skill_names:
        zip_filename = f"{skill_name}.zip"
        zip_path = os.path.join(zip_dir, zip_filename)

        if not os.path.isfile(zip_path):
            logger.warning(
                f"ZIP file not found for skill '{skill_name}': {zip_path}"
            )
            continue

        try:
            existing = skill_db.get_skill_by_name(skill_name, tenant_id)
            if existing:
                logger.info(
                    f"Skill '{skill_name}' already exists for tenant {tenant_id}, skipping"
                )
                installed.append(skill_name)
                continue

            with open(zip_path, "rb") as f:
                zip_content = f.read()

            result = service.create_skill_from_file(
                file_content=zip_content,
                skill_name=skill_name,
                file_type="zip",
                source=source,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            installed_name = result.get("name", skill_name)
            installed.append(installed_name)
            logger.info(
                f"Installed skill '{installed_name}' for tenant {tenant_id} "
                f"from ZIP {zip_filename}"
            )
        except Exception as e:
            logger.error(
                f"Failed to install skill '{skill_name}' from ZIP for tenant {tenant_id}: {e}"
            )

    return installed


def get_official_skills_with_status(
    tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return all official skills with their installation status for a tenant.

    Scans the official-skills-zip directory for available official skills
    (filename without .zip = skill name). For each skill, checks whether
    it is already installed for the target tenant and whether local resource
    files exist.

    Args:
        tenant_id: Tenant ID to check installation status for.

    Returns:
        List of dicts with skill_id, name, description, source, and status
        ("installable" | "installed" | "resource_missing").
    """
    from database import skill_db as skill_db_module

    result: List[Dict[str, Any]] = []

    zip_dir = OFFICIAL_SKILLS_ZIP_PATH
    if not os.path.isdir(zip_dir):
        logger.warning(f"Official skills zip directory not found: {zip_dir}")
        return result

    try:
        zip_files = [f for f in os.listdir(zip_dir) if f.lower().endswith(".zip")]
    except OSError as e:
        logger.warning(f"Failed to list official skills zip directory: {e}")
        return result

    for zip_file in sorted(zip_files):
        skill_name = zip_file[:-4]
        if not skill_name:
            continue

        skill_id: Optional[int] = None
        is_installed = False
        has_resources = True

        if tenant_id:
            existing = skill_db_module.get_skill_by_name(skill_name, tenant_id)
            if existing:
                skill_id = existing.get("skill_id")
                is_installed = True
                skill_manager = SkillManager(
                    base_skills_dir=CONTAINER_SKILLS_PATH,
                    tenant_id=tenant_id
                )
                skill_dir = os.path.join(
                    skill_manager.local_skills_dir or CONTAINER_SKILLS_PATH or "",
                    skill_name
                )
                has_resources = os.path.isdir(skill_dir)

        if skill_id is None:
            global_skill = skill_db_module.get_skill_by_name(skill_name, None)
            if global_skill:
                skill_id = global_skill.get("skill_id")

        if is_installed and not has_resources:
            status = "resource_missing"
        elif is_installed:
            status = "installed"
        else:
            status = "installable"

        description = ""
        if skill_id:
            db_skill = skill_db_module.get_skill_by_id(skill_id, tenant_id) if tenant_id else None
            if db_skill:
                description = db_skill.get("description", "")
        if not description:
            db_global = skill_db_module.get_skill_by_name(skill_name, None)
            if db_global:
                description = db_global.get("description", "")

        result.append({
            "skill_id": skill_id if skill_id is not None else 0,
            "name": skill_name,
            "description": description,
            "source": "official",
            "status": status,
        })

    return result
