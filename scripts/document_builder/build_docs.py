#!/usr/bin/env python3
"""Build a single merged Markdown + Word document from the Nexent VitePress docs.

Architecture
============
The source docs live under ``doc/docs/en/`` and ``doc/docs/zh/`` (parallel
locales).  Their file order and section grouping are defined by the
VitePress sidebar in ``doc/docs/.vitepress/config.mts``.  This script:

1. Parses ``config.mts`` to recover the canonical ordering.
2. Walks each locale's sidebar, concatenating every referenced ``.md`` file
   in order, with section headings derived from the sidebar structure.
3. Writes the final files beside this script by default. When both locales are
   requested, ``-en`` and ``-zh`` are added to prevent filename collisions.
4. Converts each merged Markdown to ``.docx`` via Pandoc, which embeds
   images directly (no external assets needed).

Usage
-----
    python scripts/document_builder/build_docs.py                    # defaults
    python scripts/document_builder/build_docs.py --locale en        # English only
    python scripts/document_builder/build_docs.py --locale zh        # Chinese only
    python scripts/document_builder/build_docs.py --format md        # Markdown only
    python scripts/document_builder/build_docs.py --format docx      # Word only

The ``--format`` flag accepts ``md``, ``docx``, or ``both`` (default).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Repository layout constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
VITEPRESS_CONFIG = REPO_ROOT / "doc/docs/.vitepress/config.mts"
DOCS_EN = REPO_ROOT / "doc/docs/en"
DOCS_ZH = REPO_ROOT / "doc/docs/zh"

# Path to the Pandoc reference.docx template (created by build_reference_docx.py).
REFERENCE_DOCX = SCRIPT_DIR / "reference.docx"
ASSETS_DIR_NAME = "nexent-documentation-assets"
PROFILE_CONFIG = SCRIPT_DIR / "document_profiles.yaml"

# ---------------------------------------------------------------------------
# VitePress sidebar parsing
# ---------------------------------------------------------------------------


def _parse_config(config_path: Path) -> dict[str, list[str]]:
    """Extract ordered file lists from the VitePress config locale blocks."""

    text = config_path.read_text(encoding="utf-8")

    en_start = text.find("en:")
    zh_start = text.find("zh:")
    en_block = text[en_start:zh_start] if zh_start != -1 else text[en_start:]
    zh_block = text[zh_start:] if zh_start != -1 else ""

    return {
        "en": _extract_links(en_block, "en"),
        "zh": _extract_links(zh_block, "zh"),
    }


def _extract_links(block: str, lang: str) -> list[str]:
    """Return relative paths for every sidebar link in a locale block."""

    pattern = rf'link\s*:\s*["\'](/{lang}/[^"\']+)["\']'
    raw_links = re.findall(pattern, block)

    paths: list[str] = []
    for link in raw_links:
        if not link.startswith(f"/{lang}/"):
            continue
        suffix = link[len(f"/{lang}/"):]
        if suffix.endswith("/"):
            suffix = suffix.rstrip("/")
            path = f"{suffix}/index.md"
        else:
            path = f"{suffix}.md"
        if path not in paths:
            paths.append(path)

    return paths


def load_sidebar_order() -> dict[str, list[str]]:
    """Load the canonical file order for both locales from ``config.mts``."""

    if not VITEPRESS_CONFIG.exists():
        raise FileNotFoundError(
            f"VitePress config not found: {VITEPRESS_CONFIG}\n"
            "Keep the generator under scripts/document_builder in the Nexent repository."
        )
    return _parse_config(VITEPRESS_CONFIG)


# ---------------------------------------------------------------------------
# Sidebar → section hierarchy mapping
# ---------------------------------------------------------------------------

# The top-level sidebar "text" labels (first arg of each sidebar item in
# config.mts) define the H1 sections in the output document.
# We parse them from the raw config text to avoid maintaining a hard-coded
# mapping that could drift from config.mts.
#
# The sidebar format in config.mts is:
#   {
#     text: "Section Name",
#     collapsed: false,
#     items: [ ... ]
#   }
#
# A top-level item with `items` creates an H1.
# A direct `link:` creates a top-level document (no extra H1, it gets its own H1).


def _extract_sidebar_sections(block: str, lang: str) -> dict[str, str]:
    """Return {file_path: section_h2_name} for every link in the block.

    Uses brace-depth tracking with a stack to determine the enclosing
    object for each link.  A ``text:`` label is associated with the
    next object opened at the current depth.  The stack automatically
    scopes section names to the correct enclosing object.

    Only the ``sidebar:`` block is considered (nav and socialLinks are
    skipped by checking ``saw_sidebar``).
    """

    sidebar_idx = block.find("sidebar:")
    if sidebar_idx == -1:
        return {}

    sections: dict[str, str] = {}
    stack: list[tuple[int, str]] = [(0, "")]
    depth = 0
    pending_section: str = ""
    saw_sidebar = False

    for line in block[sidebar_idx:].splitlines():
        cleaned = re.sub(r"//.*", "", line)
        if "sidebar:" in cleaned:
            saw_sidebar = True

        text_match = re.search(r'\btext\s*:\s*"([^"]+)"', cleaned)
        link_match = re.search(rf'\blink\s*:\s*["\'](/{lang}/[^"\']+)["\']', cleaned)

        if text_match and saw_sidebar:
            pending_section = text_match.group(1)

        # Handle opening brace BEFORE the link on the same line so that a link
        # at the same depth as a ``text:`` inherits the pending section.
        for _ in range(cleaned.count("{")):
            new_depth = depth + 1
        # Inherited: scan the stack excluding the current (topmost) entry,
        # which may be empty - find the nearest ancestor with a section name.
        inherited = ""
        for entry_depth, entry_section in reversed(stack[:-1]):
            if entry_section:
                inherited = entry_section
                break
            section = pending_section or inherited
            pending_section = ""
            stack.append((new_depth, section))
            depth = new_depth

        if link_match and saw_sidebar:
            link_path = link_match.group(1)
            if link_path.startswith(f"/{lang}/"):
                suffix = link_path[len(f"/{lang}/"):]
                if suffix.endswith("/"):
                    suffix = suffix.rstrip("/")
                    path = f"{suffix}/index.md"
                else:
                    path = f"{suffix}.md"
                # Walk the stack upward: the link inherits from the nearest
                # ancestor that has a section name (excluding the current depth).
                inherited = ""
                for entry_depth, entry_section in reversed(stack):
                    if entry_depth == depth - 1 and entry_section:
                        inherited = entry_section
                        break
                sections[path] = inherited

        for _ in range(cleaned.count("}")):
            if len(stack) > 1:
                stack.pop()
            depth -= 1

    return sections


def build_section_map() -> dict[str, dict[str, str]]:
    """Return {lang: {file_path: section_name}} for both locales.

    Because the sidebar links live at the same depth as their section labels in
    the VitePress config, the depth-based stack approach produces empty sections
    for many files.  We fall back to directory-based grouping: the section for a
    file is derived from its top-level subdirectory (``getting-started``,
    ``user-guide``, etc.), with explicit overrides for known subdirectories that
    don't match their directory name.
    """

    # Explicit section overrides for files whose directory doesn't match the
    # sidebar section name.
    OVERRIDES: dict[str, dict[str, str]] = {
        "en": {
            "getting-started": "Overview",
            "quick-start": "Deployment & Upgrade",
            "user-guide": "User Guide",
            "developer-guide": "Developer Guide",
            "frontend": "Developer Guide",
            "backend": "Developer Guide",
            "testing": "Developer Guide",
            "integration": "Developer Guide",
            "mcp-ecosystem": "Developer Guide",
            "sdk": "Developer Guide",
            "agent-development": "Agent Development",
            "local-tools": "Local Tools",
            "evaluation": "Agent Evaluation",
            "resource-repository": "Resource Repository",
            # Root-level files
            "contributing.md": "Community",
            "opensource-memorial-wall.md": "Community",
            "code-of-conduct.md": "Community",
            "security.md": "Community",
            "contributors.md": "Community",
            "license.md": "Community",
            "docs-development.md": "Documentation Development",
        },
        "zh": {
            "getting-started": "概览",
            "quick-start": "部署与升级",
            "user-guide": "用户指南",
            "developer-guide": "开发者指南",
            "frontend": "开发者指南",
            "backend": "开发者指南",
            "testing": "开发者指南",
            "integration": "开发者指南",
            "mcp-ecosystem": "开发者指南",
            "sdk": "开发者指南",
            "agent-development": "智能体开发",
            "local-tools": "本地工具",
            "evaluation": "智能体评估",
            "resource-repository": "资源仓库",
            # Root-level files
            "contributing.md": "社区",
            "opensource-memorial-wall.md": "开源纪念墙",
            "code-of-conduct.md": "行为准则",
            "security.md": "安全政策",
            "contributors.md": "核心贡献者",
            "license.md": "许可证",
            "docs-development.md": "文档开发",
        },
    }

    result: dict[str, dict[str, str]] = {"en": {}, "zh": {}}
    sidebar_order = load_sidebar_order()

    for lang in ("en", "zh"):
        overrides = OVERRIDES.get(lang, {})
        for path in sidebar_order[lang]:
            parts = Path(path).parts
            if len(parts) >= 2:
                top_dir = parts[0]
                section = overrides.get(
                    top_dir,
                    top_dir.replace("-", " ").replace("_", " ").title(),
                )
            else:
                section = overrides.get(Path(path).name, "")
            result[lang][path] = section

    return result


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------


def _strip_top_heading(text: str) -> str:
    """Remove the source document's H1 if it is the first non-blank line.

    The merged output injects its own H1 per document, so we avoid a double
    H1 by stripping the source's leading ``# Title``.
    """

    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            end = index + 1
            if end < len(lines) and not lines[end].strip():
                end += 1
            return "\n".join(lines[:index] + lines[end:])
        return "\n".join(lines)
    return text


def _extract_top_heading(text: str, fallback: str) -> str:
    """Return the first Markdown H1, falling back to a readable filename."""

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return re.sub(r"\s+#+\s*$", "", stripped[2:]).strip() or fallback
        break
    return fallback


def _load_profile(lang: str) -> dict[str, object]:
    """Load the product-document configuration for one locale."""

    try:
        data = json.loads(PROFILE_CONFIG.read_text(encoding="utf-8"))
        return data["product"][lang]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot load product/{lang} from {PROFILE_CONFIG}: {exc}") from exc


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _plan_product_document(
    file_list: Sequence[str],
    profile_config: dict[str, object],
) -> tuple[list[str], dict[str, str]]:
    """Filter and reorder source files according to the product profile."""

    excluded = set(profile_config.get("exclude_files", []))
    remaining = [path for path in dict.fromkeys(file_list) if path not in excluded]
    ordered: list[str] = []
    section_map: dict[str, str] = {}

    for section in profile_config.get("sections", []):
        title = str(section["title"])
        includes = section.get("includes", [])
        excludes = section.get("excludes", [])
        selected = [
            path
            for path in remaining
            if _matches_any(path, includes) and not _matches_any(path, excludes)
        ]
        for path in selected:
            ordered.append(path)
            section_map[path] = title
            remaining.remove(path)

    if remaining:
        appendix = "附录" if str(profile_config.get("title", "")).find("产品") >= 0 else "Appendix"
        for path in remaining:
            ordered.append(path)
            section_map[path] = appendix
        print(
            f"[build_docs] WARNING: {len(remaining)} file(s) did not match a product section; "
            f"placed in {appendix}.",
            file=sys.stderr,
        )
    return ordered, section_map


def _strip_leading_symbols(text: str) -> str:
    """Remove decorative emoji and symbol sequences from visible labels."""

    value = text.lstrip()
    while value:
        character = value[0]
        category = unicodedata.category(character)
        if category in {"So", "Sk"} or ord(character) in {0x200D, 0xFE0F, 0x20E3}:
            value = value[1:].lstrip()
            continue
        break
    return value


def _normalize_heading_label(text: str) -> str:
    """Keep words and numbers in product-document headings and remove punctuation."""

    normalized: list[str] = []
    for character in _strip_leading_symbols(text):
        category = unicodedata.category(character)
        normalized.append(character if category[0] in {"L", "M", "N"} else " ")
    return re.sub(r"\s+", " ", "".join(normalized)).strip()


def _clean_product_markdown(body: str, profile_config: dict[str, object]) -> str:
    """Remove promotional sections and normalize headings for publication."""

    removed_headings = [str(value).casefold() for value in profile_config.get("remove_headings", [])]
    removed_phrases = [str(value).casefold() for value in profile_config.get("remove_phrases", [])]
    cleaned: list[str] = []
    skipped_level: int | None = None
    fence_marker = ""

    for line in body.splitlines():
        stripped_line = line.lstrip()
        if fence_marker:
            cleaned.append(line)
            if stripped_line.startswith(fence_marker):
                fence_marker = ""
            continue
        if stripped_line.startswith("```") or stripped_line.startswith("~~~"):
            fence_marker = stripped_line[:3]
            cleaned.append(line)
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            label = _normalize_heading_label(heading.group(2))
            if skipped_level is not None and level > skipped_level:
                continue
            skipped_level = None
            if any(value in label.casefold() for value in removed_headings):
                skipped_level = level
                continue
            # Source H2 becomes H3 because each source page is represented by H2.
            new_level = min(level + 1, 6)
            cleaned.append(f"{'#' * new_level} {label}")
            continue

        if skipped_level is not None:
            continue
        if line.strip() in {"---", "***", "___"}:
            continue
        if any(value in line.casefold() for value in removed_phrases):
            continue

        list_item = re.match(r"^(\s*(?:[-*+] |\d+[.)] ))(.+)$", line)
        if list_item:
            item_text = list_item.group(2)
            emphasis = re.match(r"^(\*\*|__)(.+)$", item_text)
            if emphasis:
                item_text = emphasis.group(1) + _strip_leading_symbols(emphasis.group(2))
            else:
                item_text = _strip_leading_symbols(item_text)
            line = list_item.group(1) + item_text
        cleaned.append(line)

    # Collapse excessive blank space left by removed promotional blocks.
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def _number_internal_headings(body: str, prefix: str) -> str:
    """Apply hierarchical numbering to source headings below the page title."""

    counters = {level: 0 for level in range(3, 7)}
    numbered: list[str] = []
    fence_marker = ""
    for line in body.splitlines():
        stripped = line.lstrip()
        if fence_marker:
            numbered.append(line)
            if stripped.startswith(fence_marker):
                fence_marker = ""
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_marker = stripped[:3]
            numbered.append(line)
            continue

        heading = re.match(r"^(#{3,6})\s+(.+?)\s*$", line)
        if not heading:
            numbered.append(line)
            continue

        level = len(heading.group(1))
        counters[level] += 1
        for deeper in range(level + 1, 7):
            counters[deeper] = 0
        for parent in range(3, level):
            if counters[parent] == 0:
                counters[parent] = 1
        label = re.sub(r"^\d+(?:\.\d+)*[.)、]?\s*", "", heading.group(2)).strip()
        label = _normalize_heading_label(label)
        suffix = ".".join(str(counters[value]) for value in range(3, level + 1))
        numbered.append(f"{heading.group(1)} {prefix}.{suffix} {label}")
    return "\n".join(numbered)


def _collect_and_copy_assets(
    docs_dir: Path,
    file_list: list[str],
    build_dir: Path,
) -> dict[str, Path]:
    """Copy all referenced images into build_dir/assets/ and return a mapping.

    Scans every .md file in file_list for ``![...](path)`` references,
    copies the images to ``build_dir/assets/`` preserving their relative
    directory structure, and returns ``{resolved_abs_path: local_build_path}``.
    All image refs in the merged output will be rewritten to ``../assets/...``.
    """

    import shutil

    assets_dest = build_dir
    assets_dest.mkdir(parents=True, exist_ok=True)

    mapping: dict[str, Path] = {}  # abs_image_path -> copied_path

    for rel_path in file_list:
        md_file = docs_dir / rel_path
        if not md_file.exists():
            continue
        text = md_file.read_text(encoding="utf-8")
        for m in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
            raw = m.group(2)
            if re.match(r"^https?://", raw):
                continue
            # Resolve relative to the source .md file's directory.
            abs_path = (md_file.parent / raw).resolve()
            if not abs_path.exists():
                continue
            if abs_path in mapping:
                continue
            # Preserve subdirectory structure under assets_dest.
            # Images may live outside docs_dir (e.g. in doc/docs/assets/ when
            # the source dir is doc/docs/en/); fall back to the basename.
            digest = hashlib.sha1(str(abs_path).encode("utf-8")).hexdigest()[:10]
            dest = assets_dest / f"{digest}-{abs_path.name}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_path, dest)
            mapping[abs_path] = dest

    return mapping


def rewrite_image_refs(
    body: str,
    source_dir: Path,
    output_dir: Path,
    assets_mapping: dict[str, Path],
) -> str:
    """Rewrite all image references in body to point to copied assets.

    Image refs like ``./assets/foo.png`` are resolved relative to ``source_dir``
    (the directory containing the source .md file) and rewritten to
    ``./assets/{basename}`` (relative to the merged file at
    the merged Markdown file).
    """

    def replace_ref(m: re.Match[str]) -> str:
        alt, raw = m.group(1), m.group(2)
        if re.match(r"^https?://", raw):
            return m.group(0)

        abs_path = (source_dir / raw).resolve()
        if abs_path in assets_mapping:
            relative = os.path.relpath(assets_mapping[abs_path], output_dir)
            return f"![{alt}]({Path(relative).as_posix()})"
        return m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_ref, body)


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter ``--- ... ---`` at the top of a file."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:])
    return text


def assemble_markdown(
    docs_dir: Path,
    file_list: Sequence[str],
    section_map: dict[str, str],
    lang: str,
    doc_title: str,
    version: str,
    output_dir: Path,
    assets_mapping: dict[str, Path],
    profile_config: dict[str, object],
) -> str:
    """Concatenate ordered docs into a single Markdown string.

    Each document gets an H1 derived from its sidebar section + file stem.
    The source file's own top-level H1 is stripped to avoid duplication.
    """

    parts: list[str] = []
    today = _dt.date.today().isoformat()
    subtitle = str(profile_config.get("subtitle", ""))
    author = str(profile_config.get("author", "Nexent Contributors"))
    document_version = str(profile_config.get("document_version", ""))
    date_text = (
        f"产品版本 {version}  文档版本 {document_version}  {today}"
        if lang == "zh"
        else f"Product {version}  Document {document_version}  {today}"
    )
    parts.extend([
        "---\n",
        f'title: "{doc_title}"\n',
        f'subtitle: "{subtitle}"\n',
        f'author: "{author}"\n',
        f'date: "{date_text}"\n',
        f'language: "{"zh-CN" if lang == "zh" else "en-US"}"\n',
        "---\n\n",
    ])

    intro = str(profile_config.get("intro", ""))
    purpose = str(profile_config.get("purpose", ""))
    audience = str(profile_config.get("audience", ""))
    scope = str(profile_config.get("scope", ""))
    label = {
        "product": "产品版本" if lang == "zh" else "Product version",
        "document": "文档版本" if lang == "zh" else "Document version",
        "date": "发布日期" if lang == "zh" else "Release date",
        "purpose": "文档目的" if lang == "zh" else "Document Purpose",
        "audience": "目标读者" if lang == "zh" else "Intended Audience",
        "scope": "文档范围" if lang == "zh" else "Document Scope",
        "section": "文档说明" if lang == "zh" else "Document Information",
        "item": "项目" if lang == "zh" else "Item",
        "value": "内容" if lang == "zh" else "Details",
    }
    parts.extend([
        f"{intro}\n\n",
        f"# 1 {label['section']}\n\n",
        f"| {label['item']} | {label['value']} |\n",
        "| --- | --- |\n",
        f"| {label['product']} | {version} |\n",
        f"| {label['document']} | {document_version} |\n",
        f"| {label['date']} | {today} |\n",
        "\n",
        f"## 1.1 {label['purpose']}\n\n{purpose}\n\n",
        f"## 1.2 {label['audience']}\n\n{audience}\n\n",
        f"## 1.3 {label['scope']}\n\n{scope}\n\n",
    ])

    previous_section = ""
    section_number = 1
    page_number = 0

    for rel_path in file_list:
        file_path = docs_dir / rel_path

        if not file_path.exists():
            print(
                f"[build_docs] WARNING: {rel_path} listed in sidebar but not "
                f"found on disk; skipping.",
                file=sys.stderr,
            )
            continue

        body = file_path.read_text(encoding="utf-8")
        body = _strip_frontmatter(body)
        fallback = file_path.parent.name if file_path.stem == "index" else file_path.stem
        fallback = fallback.replace("-", " ").replace("_", " ").title()
        page_title = _extract_top_heading(body, fallback)
        body = _strip_top_heading(body).rstrip()
        page_title = _normalize_heading_label(page_title)
        body = _clean_product_markdown(body, profile_config)
        # Rewrite image references to point to assets copied into build_dir/assets/.
        body = rewrite_image_refs(body, file_path.parent, output_dir, assets_mapping)

        section = section_map.get(rel_path, "")
        if section and section != previous_section:
            section_number += 1
            page_number = 0
            section_label = f"{section_number} {section}"
            parts.append(f"\n# {section_label}\n")
            previous_section = section

        page_number += 1
        page_label = f"{section_number}.{page_number} {page_title}"
        body = _number_internal_headings(body, f"{section_number}.{page_number}")
        parts.append(f"\n## {page_label}\n\n")

        parts.append(body)
        parts.append("\n")

    return "".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Pandoc invocation
# ---------------------------------------------------------------------------


def find_pandoc() -> Path | None:
    executable = shutil.which("pandoc")
    return Path(executable) if executable else None


def render_docx(
    markdown_text: str,
    output_path: Path,
    build_dir: Path,
    lang: str,
    doc_title: str,
    version: str,
    profile_config: dict[str, object],
) -> None:
    """Convert merged Markdown to a styled .docx via Pandoc.

    ``build_dir`` is passed to Pandoc as the process working directory so that
    relative image paths (``./assets/foo.png``) resolve from the build dir
    where the copied assets live.
    """

    pandoc = find_pandoc()
    if not pandoc:
        raise RuntimeError(
            "pandoc not found on PATH. Install it from https://pandoc.org/ "
            "or use --format md to skip the .docx step."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(pandoc),
        "--from", "gfm+yaml_metadata_block+raw_attribute",
        "--to", "docx",
        "--wrap", "preserve",
        "--standalone",
        "--toc",
        "--toc-depth", "3",
        "--reference-doc", str(REFERENCE_DOCX.resolve()),
        "--metadata", f"toc-title={'目录' if lang == 'zh' else 'Contents'}",
    ]

    # Write to a temp file in the same directory as the output, then rename.
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(output_path.parent.resolve()),
        suffix=".docx",
    )
    os.close(tmp_fd)
    command.extend(["--output", tmp_path])

    result = subprocess.run(
        command,
        input=markdown_text,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=str(build_dir),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pandoc exited with code {result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    _postprocess_docx(Path(tmp_path), lang, doc_title, version, profile_config)

    # Atomic rename. A locked destination is an actionable error, not success.
    try:
        os.replace(tmp_path, str(output_path))
    except PermissionError as exc:
        Path(tmp_path).unlink(missing_ok=True)
        raise RuntimeError(
            f"Cannot replace {output_path}; close the file in Word and retry."
        ) from exc


def _postprocess_docx(
    path: Path,
    lang: str,
    doc_title: str,
    version: str,
    profile_config: dict[str, object],
) -> None:
    """Apply publication-quality typography and layout after conversion."""

    from docx import Document
    from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    document = Document(path)
    latin_font = "Times New Roman"
    cjk_font = "宋体"
    ink = RGBColor(23, 32, 51)
    muted = RGBColor(102, 112, 133)

    def set_run_fonts(run) -> None:
        run.font.name = latin_font
        fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
        fonts.set(qn("w:ascii"), latin_font)
        fonts.set(qn("w:hAnsi"), latin_font)
        fonts.set(qn("w:cs"), latin_font)
        fonts.set(qn("w:eastAsia"), cjk_font)

    def set_style_fonts(style) -> None:
        if not hasattr(style, "font"):
            return
        style.font.name = latin_font
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        fonts.set(qn("w:ascii"), latin_font)
        fonts.set(qn("w:hAnsi"), latin_font)
        fonts.set(qn("w:cs"), latin_font)
        fonts.set(qn("w:eastAsia"), cjk_font)

    def iter_table_paragraphs(table):
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
                for nested in cell.tables:
                    yield from iter_table_paragraphs(nested)

    def iter_all_paragraphs():
        yield from document.paragraphs
        for table in document.tables:
            yield from iter_table_paragraphs(table)
        for section in document.sections:
            for container in (
                section.header,
                section.footer,
                section.first_page_header,
                section.first_page_footer,
            ):
                yield from container.paragraphs
                for table in container.tables:
                    yield from iter_table_paragraphs(table)

    def set_cell_shading(cell, fill: str) -> None:
        properties = cell._tc.get_or_add_tcPr()
        existing = properties.find(qn("w:shd"))
        if existing is not None:
            properties.remove(existing)
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), fill)
        properties.append(shading)

    # Enforce one bilingual font policy across every style. Word will render
    # Chinese glyphs in SimSun and Latin letters/digits in Times New Roman.
    for style in document.styles:
        set_style_fonts(style)

    # Refine key styles after Pandoc has imported the reference document.
    style_specs = {
        "Normal": (10.5, False, ink),
        "Body Text": (10.5, False, ink),
        "Title": (28, True, RGBColor(0, 0, 0)),
        "Subtitle": (15, False, RGBColor(0, 0, 0)),
        "Heading 1": (20, True, RGBColor(0, 0, 0)),
        "Heading 2": (15.5, True, RGBColor(0, 0, 0)),
        "Heading 3": (12.5, True, RGBColor(0, 0, 0)),
        "Heading 4": (11, True, RGBColor(0, 0, 0)),
        "Source Code": (9, False, ink),
        "Verbatim Char": (9, False, RGBColor(24, 73, 169)),
        "Caption": (9, False, muted),
        "TOC Heading": (18, True, ink),
        "TOC 1": (11, True, ink),
        "TOC 2": (10.5, False, ink),
        "TOC 3": (9.5, False, ink),
    }
    for style_name, (size, bold, color) in style_specs.items():
        try:
            style = document.styles[style_name]
        except KeyError:
            continue
        style.font.size = Pt(size)
        style.font.bold = bold
        style.font.color.rgb = color

    for name in ("Normal", "Body Text"):
        try:
            style = document.styles[name]
        except KeyError:
            continue
        style.paragraph_format.line_spacing = 1.3
        style.paragraph_format.space_after = Pt(6)

    # Keep illustrations legible, centered, and within the A4 text area.
    max_image_width = Mm(166)
    for shape in document.inline_shapes:
        if shape.width > max_image_width:
            ratio = max_image_width / shape.width
            shape.width = max_image_width
            shape.height = int(shape.height * ratio)
    for paragraph in document.paragraphs:
        if paragraph._p.xpath(".//w:drawing | .//w:pict"):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = Pt(7)
            paragraph.paragraph_format.space_after = Pt(7)
            paragraph.paragraph_format.keep_together = True

    for table in document.tables:
        table.style = "Table Grid"
        table.autofit = True
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        if not table.rows:
            continue

        column_texts = [
            [row.cells[index].text.strip() for row in table.rows]
            for index in range(len(table.columns))
        ]
        centered_columns = {
            index
            for index, values in enumerate(column_texts)
            if max((len(value) for value in values), default=0) <= 18
        }

        header_properties = table.rows[0]._tr.get_or_add_trPr()
        if header_properties.find(qn("w:tblHeader")) is None:
            repeat = OxmlElement("w:tblHeader")
            repeat.set(qn("w:val"), "true")
            header_properties.append(repeat)

        for row_index, row in enumerate(table.rows):
            row_properties = row._tr.get_or_add_trPr()
            if row_properties.find(qn("w:cantSplit")) is None:
                no_split = OxmlElement("w:cantSplit")
                row_properties.append(no_split)
            for column_index, cell in enumerate(row.cells):
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                if row_index == 0:
                    set_cell_shading(cell, "1849A9")
                    for paragraph in cell.paragraphs:
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        for run in paragraph.runs:
                            run.font.bold = True
                            run.font.color.rgb = RGBColor(255, 255, 255)
                elif row_index % 2 == 0:
                    set_cell_shading(cell, "F8FAFC")
                for paragraph in cell.paragraphs:
                    if row_index != 0:
                        paragraph.alignment = (
                            WD_ALIGN_PARAGRAPH.CENTER
                            if column_index in centered_columns
                            else WD_ALIGN_PARAGRAPH.LEFT
                        )
                    paragraph.paragraph_format.line_spacing = 1.1
                    paragraph.paragraph_format.space_before = Pt(2)
                    paragraph.paragraph_format.space_after = Pt(2)

    author = str(profile_config.get("author", "Nexent Contributors"))
    header_text = (
        "NEXENT 产品与技术指南" if lang == "zh" else "NEXENT PRODUCT AND TECHNICAL GUIDE"
    )
    page_label = "第 " if lang == "zh" else "Page "
    page_suffix = " 页" if lang == "zh" else ""
    for section in document.sections:
        header = section.header.paragraphs[0]
        header.text = ""
        header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        header_run = header.add_run(header_text)
        set_run_fonts(header_run)
        header_run.font.size = Pt(8)
        header_run.font.bold = True
        header_run.font.color.rgb = RGBColor(0, 0, 0)

        footer = section.footer.paragraphs[0]
        footer.text = ""
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        prefix = footer.add_run(f"Nexent    {version}    {page_label}")
        set_run_fonts(prefix)
        prefix.font.size = Pt(8)
        prefix.font.color.rgb = RGBColor(102, 112, 133)
        page_run = footer.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instruction = OxmlElement("w:instrText")
        instruction.set(qn("xml:space"), "preserve")
        instruction.text = " PAGE "
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        value = OxmlElement("w:t")
        value.text = "1"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        for element in (begin, instruction, separate, value, end):
            page_run._r.append(element)
        set_run_fonts(page_run)
        suffix = footer.add_run(page_suffix)
        set_run_fonts(suffix)
        suffix.font.size = Pt(8)
        suffix.font.color.rgb = muted

    language_code = "zh-CN" if lang == "zh" else "en-US"
    for style in document.styles:
        if not hasattr(style, "font"):
            continue
        run_properties = style.element.get_or_add_rPr()
        language = run_properties.find(qn("w:lang"))
        if language is None:
            language = OxmlElement("w:lang")
            run_properties.append(language)
        language.set(qn("w:val"), language_code)
        language.set(qn("w:eastAsia"), language_code)

    for paragraph in iter_all_paragraphs():
        for run in paragraph.runs:
            set_run_fonts(run)

    document.core_properties.title = doc_title
    document.core_properties.subject = "Product and technical documentation"
    document.core_properties.author = author
    document.save(path)


# ---------------------------------------------------------------------------
# Per-locale builder
# ---------------------------------------------------------------------------


def build_locale(
    lang: str,
    docs_dir: Path,
    file_list: list[str],
    section_map: dict[str, str],
    format_: str,
    output_dir: Path,
    md_name: str,
    docx_name: str,
) -> bool:
    """Build merged Markdown (and optionally .docx) for one locale.

    Returns True when every requested output was written.
    """

    title_map: dict[str, str] = {
        "en": "Nexent Documentation",
        "zh": "Nexent 文档",
    }
    profile_config = _load_profile(lang)
    file_list, section_map = _plan_product_document(file_list, profile_config)
    doc_title = str(profile_config.get("title", title_map[lang]))
    print(f"[build_docs] product profile includes {len(file_list)} published file(s)")

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / ASSETS_DIR_NAME / lang
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Copy all referenced images into the build directory first.
    assets_mapping = _collect_and_copy_assets(docs_dir, file_list, assets_dir)
    print(f"[build_docs] copied {len(assets_mapping)} image(s) to {assets_dir}")

    version_path = REPO_ROOT / "VERSION"
    version = version_path.read_text(encoding="utf-8").splitlines()[0].strip() if version_path.exists() else ""

    merged = assemble_markdown(
        docs_dir,
        file_list,
        section_map,
        lang,
        doc_title,
        version,
        output_dir,
        assets_mapping,
        profile_config,
    )

    md_path = output_dir / md_name
    docx_path = output_dir / docx_name

    written_md = False
    written_docx = False

    if format_ in ("md", "both"):
        md_path.write_text(merged, encoding="utf-8")
        size_kb = len(merged) // 1024
        print(f"[build_docs] wrote {md_path}  (~{size_kb} KB, {len(merged):,} chars)")
        written_md = True

    if format_ in ("docx", "both"):
        try:
            render_docx(
                merged,
                docx_path,
                output_dir,
                lang,
                doc_title,
                version,
                profile_config,
            )
            size_kb = docx_path.stat().st_size // 1024
            print(f"[build_docs] wrote {docx_path}  (~{size_kb} KB)")
            written_docx = True
        except RuntimeError as exc:
            print(f"[build_docs] ERROR: {exc}", file=sys.stderr)
            return False

    return written_md or written_docx


def _locale_filename(filename: str, lang: str, multiple_locales: bool) -> str:
    """Add a locale suffix when one invocation creates both languages."""

    path = Path(filename)
    if not multiple_locales:
        return path.name
    return f"{path.stem}-{lang}{path.suffix}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate Nexent VitePress docs into a single Markdown "
            "and/or Word document.  File order and section grouping are "
            "derived from the sidebar in .vitepress/config.mts."
        )
    )
    parser.add_argument(
        "--locale",
        choices=("en", "zh", "both"),
        default="zh",
        help="Which locale(s) to build (default: zh).",
    )
    parser.add_argument(
        "--format",
        choices=("md", "docx", "both"),
        default="docx",
        help="Which output format(s) to produce (default: docx).",
    )
    parser.add_argument(
        "--md-name",
        default=None,
        help="Filename for merged Markdown (default: nexent-product-technical-guide.md).",
    )
    parser.add_argument(
        "--docx-name",
        default=None,
        help="Filename for the Word document (default: nexent-product-technical-guide.docx).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR,
        help="Output directory (default: the directory containing this script).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    md_name = args.md_name or "nexent-product-technical-guide.md"
    docx_name = args.docx_name or "nexent-product-technical-guide.docx"

    # Load canonical sidebar order from config.mts.
    sidebar_order = load_sidebar_order()

    # Build the section → H2 prefix map for each locale.
    section_map = build_section_map()

    locales_to_build = []
    if args.locale in ("en", "both"):
        locales_to_build.append("en")
    if args.locale in ("zh", "both"):
        locales_to_build.append("zh")

    success = True
    for lang in locales_to_build:
        docs_dir = DOCS_EN if lang == "en" else DOCS_ZH
        file_list = sidebar_order.get(lang, [])
        lang_section_map = section_map.get(lang, {})

        print(f"\n[build_docs] Building {lang} docs from {len(file_list)} sidebar link(s) ...")
        multiple_locales = len(locales_to_build) > 1
        result = build_locale(
            lang,
            docs_dir,
            file_list,
            lang_section_map,
            args.format,
            args.output_dir.resolve(),
            _locale_filename(md_name, lang, multiple_locales),
            _locale_filename(docx_name, lang, multiple_locales),
        )
        if not result:
            success = False

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
