"""Skill management support service."""

import ast
import io
import json
import logging
import os
import zipfile
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from nexent.skills import SkillManager
from nexent.skills.text_codec import decode_skill_text
from nexent.skills.paths import (
    InvalidSkillNameError, UnsafeSkillPathError, UnsafeSkillRootError, resolve_skill_path,
)
from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    CONTAINER_SKILLS_PATH,
    PERMISSION_EDIT,
    PERMISSION_PRIVATE,
    PERMISSION_READ,
)
from consts.exceptions import ForbiddenError, SkillException
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.str_utils import convert_list_to_string

logger = logging.getLogger(__name__)
_SKILL_UPDATE_FORBIDDEN_MESSAGE = "Not authorized to update this skill"
_SKILL_ACCESS_UPDATE_FORBIDDEN_MESSAGE = "Not authorized to update skill access"


_UNSUPPORTED_PREVIEW_DIRECTORIES = frozenset({
    "__macosx",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
})
_UNSUPPORTED_PREVIEW_EXTENSIONS = frozenset({
    ".7z", ".a", ".avi", ".bin", ".bmp", ".class", ".dll", ".dylib",
    ".eot", ".exe", ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg",
    ".mov", ".mp3", ".mp4", ".o", ".obj", ".otf", ".pdf", ".png",
    ".pyc", ".pyo", ".so", ".tar", ".ttf", ".wav", ".webm", ".webp",
    ".woff", ".woff2", ".xls", ".xlsx", ".zip",
})
_TEXT_PREVIEW_EXTENSIONS = frozenset({
    "", ".bash", ".c", ".cc", ".cfg", ".conf", ".cpp", ".css", ".csv",
    ".dockerfile", ".env", ".go", ".h", ".hpp", ".html", ".ini", ".java",
    ".js", ".json", ".jsx", ".log", ".md", ".mdx", ".php", ".properties",
    ".py", ".rb", ".rs", ".rst", ".sh", ".sql", ".svg", ".toml", ".ts",
    ".tsx", ".txt", ".xml", ".yaml", ".yml", ".zsh",
})


class UnsupportedSkillFilePreview(SkillException):
    """Raised when a skill file is intentionally excluded from text preview."""


def _decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    """Recover legacy ZIP member names written without the UTF-8 flag."""
    name = info.filename
    if info.flag_bits & 0x800 or name.isascii():
        return name
    try:
        raw_name = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("utf-8", "gb18030"):
        try:
            candidate = raw_name.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "utf-8" or any("\u3400" <= char <= "\u9fff" for char in candidate):
            return candidate
    return name


def _zip_members(zf: zipfile.ZipFile) -> List[Tuple[zipfile.ZipInfo, str]]:
    """Return ZIP entries paired with their normalized display paths."""
    members = [(info, _decode_zip_member_name(info)) for info in zf.infolist()]
    seen: Dict[str, str] = {}
    for info, decoded_name in members:
        normalized = _normalize_zip_entry_path(decoded_name)
        collision_key = normalized.casefold()
        previous = seen.get(collision_key)
        if previous is not None and previous != info.filename:
            raise SkillException(f"ZIP entries resolve to the same path: {decoded_name}")
        seen[collision_key] = info.filename
    return members


def _zip_file_list(zf: zipfile.ZipFile) -> List[str]:
    return [decoded_name for _, decoded_name in _zip_members(zf)]


def _read_zip_member(zf: zipfile.ZipFile, decoded_name: str) -> bytes:
    for info, candidate in _zip_members(zf):
        if candidate == decoded_name:
            return zf.read(info)
    raise KeyError(decoded_name)


def _is_obviously_binary(raw: bytes) -> bool:
    if not raw:
        return False
    if b"\x00" in raw:
        even_nuls = raw[0::2].count(0)
        odd_nuls = raw[1::2].count(0)
        if max(even_nuls, odd_nuls) > len(raw) / 4:
            return False
        return True
    control_count = sum(byte < 9 or 13 < byte < 32 for byte in raw)
    return control_count / len(raw) > 0.1


def _skill_file_preview_status(
    local_skills_dir: str,
    skill_name: str,
    relative_path: str,
) -> str:
    """Classify whether a local skill file may be exposed as editable text."""
    parts = [part.casefold() for part in relative_path.replace("\\", "/").split("/")]
    if any(part in _UNSUPPORTED_PREVIEW_DIRECTORIES for part in parts[:-1]):
        return "unsupported"
    extension = os.path.splitext(relative_path)[1].casefold()
    if extension in _UNSUPPORTED_PREVIEW_EXTENSIONS:
        return "unsupported"
    if extension in _TEXT_PREVIEW_EXTENSIONS:
        return "readable"

    local_root = os.path.realpath(local_skills_dir)
    skill_root = os.path.realpath(
        _resolve_local_skill_path(local_skills_dir, skill_name)
    )
    file_path = os.path.realpath(
        _resolve_local_skill_path(local_skills_dir, skill_name, relative_path)
    )
    if (
        not file_path.startswith(local_root + os.sep)
        or not file_path.startswith(skill_root + os.sep)
    ):
        raise ForbiddenError("Unsafe local skill path")
    try:
        with open(file_path, "rb") as file_obj:
            return "unsupported" if _is_obviously_binary(file_obj.read(4096)) else "readable"
    except OSError:
        return "readable"


def _replace_skill_frontmatter_name(content: str, new_name: str) -> str:
    """Replace only the name value in SKILL.md frontmatter and preserve the body."""
    match = re.match(
        r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?P<closing>\r?\n---[ \t]*\r?\n)(?P<body>[\s\S]*)\Z",
        content,
        re.DOTALL,
    )
    if not match:
        raise SkillException("SKILL.md must have YAML frontmatter")

    frontmatter = match.group("frontmatter")
    name_match = re.search(r"(?m)^name[ \t]*:[^\r\n]*(?P<line_end>\r?\n|$)", frontmatter)
    if not name_match:
        raise SkillException("SKILL.md frontmatter must contain a name field")

    replacement = f"name: {json.dumps(new_name, ensure_ascii=False)}{name_match.group('line_end')}"
    updated_frontmatter = (
        frontmatter[:name_match.start()]
        + replacement
        + frontmatter[name_match.end():]
    )
    return (
        content[:match.start("frontmatter")]
        + updated_frontmatter
        + content[match.end("frontmatter"):]
    )


def _to_group_id_set(group_ids: Any) -> set[int]:
    if isinstance(group_ids, str):
        return {
            int(group_id.strip())
            for group_id in group_ids.split(",")
            if group_id.strip().isdigit()
        }
    if isinstance(group_ids, list):
        return {
            int(group_id)
            for group_id in group_ids
            if str(group_id).strip().isdigit()
        }
    return set()


def can_view_skill(
    *,
    skill: Dict[str, Any],
    user_id: str,
    user_role: str,
    user_group_ids: set[int],
) -> bool:
    """Return whether a skill is available to the current user."""
    if skill.get("source") == "official":
        return True
    if user_role in CAN_EDIT_ALL_USER_ROLES:
        return True
    if str(skill.get("created_by")) == str(user_id):
        return True
    if skill.get("ingroup_permission") == PERMISSION_PRIVATE:
        return False
    return bool(
        user_group_ids.intersection(_to_group_id_set(skill.get("group_ids")))
    )


def resolve_skill_permission(
    *,
    skill: Dict[str, Any],
    user_id: str,
    user_role: str,
    user_group_ids: set[int],
) -> str:
    """Resolve whether the current user can edit or only use a visible skill."""
    if user_role in CAN_EDIT_ALL_USER_ROLES:
        return PERMISSION_EDIT
    if str(skill.get("created_by")) == str(user_id):
        return PERMISSION_EDIT
    if skill.get("ingroup_permission") != PERMISSION_EDIT:
        return PERMISSION_READ
    return (
        PERMISSION_EDIT
        if user_group_ids.intersection(_to_group_id_set(skill.get("group_ids")))
        else PERMISSION_READ
    )


def _apply_default_skill_permission_fields(
    skill_data: Dict[str, Any],
    user_id: Optional[str],
) -> None:
    """Default user-created skills to the creator's groups with edit permission."""
    if not user_id:
        return
    if skill_data.get("group_ids") is None:
        skill_data["group_ids"] = convert_list_to_string(query_group_ids_by_user(user_id))
    if not skill_data.get("ingroup_permission"):
        skill_data["ingroup_permission"] = PERMISSION_EDIT


def _get_user_role(user_id: Optional[str]) -> str:
    if not user_id:
        return "USER"
    user_tenant = get_user_tenant_by_user_id(user_id)
    if not user_tenant:
        return "USER"
    return str(user_tenant.get("user_role") or "USER")


def _can_edit_skill(skill: Dict[str, Any], user_id: Optional[str]) -> bool:
    if not user_id:
        return False
    user_role = _get_user_role(user_id)
    user_group_ids = set(query_group_ids_by_user(user_id) or [])
    return resolve_skill_permission(
        skill=skill,
        user_id=user_id,
        user_role=user_role,
        user_group_ids=user_group_ids,
    ) == PERMISSION_EDIT


def _can_manage_skill_access(skill: Dict[str, Any], user_id: Optional[str]) -> bool:
    if not user_id:
        return False
    return (
        _get_user_role(user_id) in CAN_EDIT_ALL_USER_ROLES
        or str(skill.get("created_by")) == str(user_id)
    )


def _has_skill_access_changes(
    existing: Dict[str, Any], skill_data: Dict[str, Any]
) -> bool:
    if (
        "group_ids" in skill_data
        and _to_group_id_set(skill_data.get("group_ids"))
        != _to_group_id_set(existing.get("group_ids"))
    ):
        return True
    return (
        "ingroup_permission" in skill_data
        and skill_data.get("ingroup_permission") != existing.get("ingroup_permission")
    )


def _validate_skill_access_update(
    existing: Dict[str, Any], skill_data: Dict[str, Any], user_id: Optional[str]
) -> None:
    if (
        user_id
        and _has_skill_access_changes(existing, skill_data)
        and not _can_manage_skill_access(existing, user_id)
    ):
        raise ForbiddenError(_SKILL_ACCESS_UPDATE_FORBIDDEN_MESSAGE)


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
    text = str(decode_skill_text(raw)).strip()
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
    text = str(decode_skill_text(raw)).strip()
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
            _zip_file_list(zf),
            preferred_skill_root=preferred_skill_root,
        )
        if not member:
            return None
        raw = _read_zip_member(zf, member)
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
            _zip_file_list(zf),
            preferred_skill_root=preferred_skill_root,
        )
        if not member:
            return None
        raw = _read_zip_member(zf, member)
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
            file_list = _zip_file_list(zf)
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
                    source = decode_skill_text(_read_zip_member(zf, member))
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
    return _resolve_local_skill_path(
        local_skills_dir,
        skill_name,
        "config",
        "config.yaml",
    )


def _local_skill_schema_yaml_path(skill_name: str, local_skills_dir: str) -> str:
    """Absolute path to <local_skills_dir>/<skill_name>/config/schema.yaml."""
    return _resolve_local_skill_path(
        local_skills_dir,
        skill_name,
        "config",
        "schema.yaml",
    )


def _resolve_local_skill_path(local_skills_dir: str, skill_name: str, *parts: str) -> str:
    """Apply backend storage configuration and translate SDK path errors."""
    try:
        return resolve_skill_path(
            local_skills_dir, str(skill_name or "").strip(),
            *(str(part or "") for part in parts), allowed_root=CONTAINER_SKILLS_PATH,
        )
    except (InvalidSkillNameError, UnsafeSkillRootError) as exc:
        raise SkillException(str(exc)) from exc
    except UnsafeSkillPathError as exc:
        raise ForbiddenError(str(exc)) from exc


def _write_skill_params_to_local_config_yaml(
    skill_name: str,
    params: Dict[str, Any],
    local_skills_dir: str,
) -> None:
    """Write params to config/config.yaml; scalar ``value # tip`` strings round-trip as YAML comments above keys."""
    from utils.skill_params_utils import params_dict_to_roundtrip_yaml_text

    if not local_skills_dir:
        return
    path = _local_skill_config_yaml_path(skill_name, local_skills_dir)
    config_dir = os.path.dirname(path)
    os.makedirs(config_dir, exist_ok=True)
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


def get_skill_manager() -> SkillManager:
    """Return the process-wide SkillManager."""
    return SkillManager(base_skills_dir=CONTAINER_SKILLS_PATH)
