"""SKILL.md loader and parser."""

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_ALLOWED_SKILL_META_KEYS = frozenset([
    "name",
    "description",
    "allowed-tools",
    "tags",
])


class SkillLoader:
    """Load and parse SKILL.md files."""

    FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

    @classmethod
    def load(cls, path: str) -> Dict[str, Any]:
        """Load Skill from file and return as dict."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")

        content = file_path.read_text(encoding="utf-8")
        return cls.parse(content, source_path=str(file_path))

    @classmethod
    def parse(cls, content: str, source_path: str = "") -> Dict[str, Any]:
        """Parse SKILL.md content and return as dict."""
        frontmatter, body = cls._split_frontmatter(content)

        if not frontmatter:
            raise ValueError("SKILL.md must have YAML frontmatter")

        # Try to parse with yaml.safe_load first
        meta = None
        try:
            # Fix YAML parsing to handle special characters in values
            frontmatter = cls._fix_yaml_frontmatter(frontmatter)
            meta = yaml.safe_load(frontmatter)
        except yaml.YAMLError as e:
            logger.warning(f"YAML parse error, falling back to regex extraction: {e}")

        # If yaml.safe_load failed or returned invalid result, use regex fallback
        if not isinstance(meta, dict):
            meta = cls._extract_frontmatter_by_regex(frontmatter)

        if "name" not in meta:
            raise ValueError("Skill must have 'name' field")
        if "description" not in meta:
            raise ValueError("Skill must have 'description' field")

        # Filter to only known keys to tolerate extra fields like 'author'
        filtered_meta = {k: v for k, v in meta.items() if k in _ALLOWED_SKILL_META_KEYS}

        return {
            "name": filtered_meta.get("name"),
            "description": filtered_meta.get("description", ""),
            "allowed_tools": filtered_meta.get("allowed-tools", []),
            "tags": filtered_meta.get("tags", []),
            "content": body.strip(),
            "source_path": source_path
        }

    @classmethod
    def _fix_yaml_frontmatter(cls, frontmatter: str) -> str:
        """Fix YAML frontmatter to properly handle special characters.

        Wraps unquoted values in double quotes to allow colons and other
        special characters within field values. Preserves block scalar indicators
        (|, |+, |-, >, >+, >-).
        """
        lines = frontmatter.split('\n')
        fixed_lines = []

        for line in lines:
            # Skip empty lines and comment lines
            if not line.strip() or line.strip().startswith('#'):
                fixed_lines.append(line)
                continue

            # Skip indented lines - these are content of multi-line values (block scalars)
            # They should NOT be modified as they're part of block scalar values
            if line.startswith(' ') or line.startswith('\t'):
                fixed_lines.append(line)
                continue

            # Check if this is a key-value line (contains ':' but not in quotes)
            if ':' in line:
                # Find the first colon to identify the key
                colon_pos = line.find(':')
                key = line[:colon_pos].strip()
                value_part = line[colon_pos + 1:].strip()

                # Check for block scalar indicators (| |+ |- > >+ >-)
                # These must be preserved as-is for multi-line strings
                base_symbols = ('|', '|+', '|-', '>', '>+', '>-')
                if value_part and value_part.rstrip().startswith(base_symbols):
                    fixed_lines.append(line)
                    continue

                # Skip YAML list items (lines starting with '-')
                if key == '' or line.strip().startswith('-'):
                    fixed_lines.append(line)
                    continue

                # If value exists and is not quoted, we need to handle it
                if value_part and not value_part.startswith('"') and not value_part.startswith("'"):
                    # Check if value contains unescaped colons that would break YAML
                    if any(c in value_part for c in [':', '{', '}', '[', ']', ',', '&', '*', '#', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`']):
                        # Wrap value in double quotes, escaping internal quotes
                        escaped_value = value_part.replace('"', '\\"')
                        line = f'{key}: "{escaped_value}"'

            fixed_lines.append(line)

        return '\n'.join(fixed_lines)

    @classmethod
    def _extract_frontmatter_by_regex(cls, frontmatter: str) -> Dict[str, Any]:
        """Extract frontmatter fields using regex when YAML parsing fails.

        This handles cases where YAML contains unexpected metadata or
        formatting issues that break the parser.
        """
        result: Dict[str, Any] = {}

        # Extract name field
        name_match = re.search(r"^name:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
        if name_match:
            result["name"] = name_match.group(1).strip().strip('"').strip("'")

        # Extract description field
        # Using non-greedy (.+?) will capture minimum, so "description: >" captures ">"
        # Need to check if this is a block scalar first
        desc_start_match = re.search(r"^description:\s*", frontmatter, re.MULTILINE)
        if desc_start_match:
            # Find the actual description line
            lines = frontmatter.split('\n')
            desc_line_idx = -1
            for i, line in enumerate(lines):
                if re.match(r"^description:\s*", line):
                    desc_line_idx = i
                    break

            if desc_line_idx >= 0:
                desc_line = lines[desc_line_idx]

                # Check if it's a block scalar
                has_block_scalar = re.match(r"^description:\s*[>|]", desc_line)
                if has_block_scalar:
                    # Collect all indented lines
                    content_lines = []
                    for line in lines[desc_line_idx + 1:]:
                        # Empty line or non-indented line ends block
                        if line.strip() == "":
                            continue
                        if not line.startswith(" ") and not line.startswith("\t"):
                            break
                        content_lines.append(line)
                    description_text = " ".join([l.lstrip() for l in content_lines]).strip()
                    result["description"] = description_text
                else:
                    # Single line value
                    desc_match = re.search(r"^description:\s*(.+?)\s*$", desc_line)
                    if desc_match:
                        result["description"] = desc_match.group(1).strip().strip('"').strip("'")

        # Extract tags field (YAML list format)
        tags_match = re.search(r"^tags:\s*\[(.*?)\]\s*$", frontmatter, re.MULTILINE | re.DOTALL)
        if tags_match:
            tags_str = tags_match.group(1)
            result["tags"] = [t.strip().strip('"').strip("'") for t in tags_str.split(",") if t.strip()]

        # Extract allowed-tools field (YAML list format)
        tools_match = re.search(r"^allowed-tools:\s*\[(.*?)\]\s*$", frontmatter, re.MULTILINE | re.DOTALL)
        if tools_match:
            tools_str = tools_match.group(1)
            result["allowed-tools"] = [t.strip().strip('"').strip("'") for t in tools_str.split(",") if t.strip()]

        return result

    @classmethod
    def _split_frontmatter(cls, content: str) -> Tuple[Optional[str], str]:
        """Split frontmatter and body."""
        match = cls.FRONTMATTER_PATTERN.match(content)
        if match:
            return match.group(1), match.group(2)
        return None, content

    @classmethod
    def to_skill_md(cls, skill_dict: Dict[str, Any]) -> str:
        """Convert skill dict to SKILL.md format."""
        frontmatter: dict = {
            "name": skill_dict["name"],
            "description": skill_dict.get("description", ""),
        }

        if skill_dict.get("allowed-tools"):
            frontmatter["allowed-tools"] = skill_dict["allowed-tools"]
        if skill_dict.get("tags"):
            frontmatter["tags"] = skill_dict["tags"]

        # Use default_flow_style=False for block style
        # Use width=float("inf") to prevent line wrapping
        yaml_str = yaml.dump(
            frontmatter,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            indent=2,
            width=float("inf")
        )

        return f"---\n{yaml_str}---\n\n{skill_dict.get('content', '')}"
