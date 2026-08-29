"""Shared CJK font utilities for matplotlib and reportlab.

Consolidates font discovery, registration and fallback logic that was
previously duplicated between ``agent_evaluation_service`` and
``evaluation_report_service``.  Both callers use the same cached
results so fonts are registered once per process lifetime.
"""

import logging
import os
import shutil
import subprocess
from typing import Optional


logger = logging.getLogger(__name__)

# ── module-level cache ──────────────────────────────────────────────
_CACHED_FONT_PATH: Optional[str] = None   # path to CJK .ttf file, or "" if not found
_CACHED_FONT_NAME: Optional[str] = None   # matplotlib family name, or "" if fallback


def _find_cjk_font_with_fontconfig() -> Optional[str]:
    """Resolve a Chinese font through Linux fontconfig.

    ``fc-match`` returns the best font for a font pattern and language.  The
    family and language fields are checked as well as the file path so a
    generic western fallback is not mistaken for a usable CJK font.
    """
    fc_match = shutil.which("fc-match")
    if not fc_match:
        logger.debug("fontconfig fc-match is unavailable")
        return None

    try:
        result = subprocess.run(
            [
                fc_match,
                "-f",
                "%{family}\\t%{lang}\\t%{file}\\n",
                "sans-serif:lang=zh-cn",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("fontconfig CJK lookup failed: %s", exc)
        return None

    for line in result.stdout.splitlines():
        family, separator, remainder = line.partition("\t")
        if not separator:
            continue
        lang, separator, font_path = remainder.partition("\t")
        if not separator or not font_path:
            continue
        family_lang = f"{family} {lang}".lower()
        if "zh" not in family_lang and "cjk" not in family_lang:
            logger.debug("fontconfig returned non-CJK fallback: %s", line)
            continue
        if os.path.exists(font_path) and os.path.getsize(font_path) > 1000:
            logger.debug("fontconfig resolved CJK font: %s → %s", family, font_path)
            return font_path
    return None


def _find_cjk_font_path() -> Optional[str]:
    """Return an available Linux CJK font path, or ``None``.

    fontconfig is the primary discovery mechanism.  The explicit paths are
    retained only as a compatibility fallback for minimal environments where
    the command is unavailable or its cache is not usable yet.
    """
    font_path = _find_cjk_font_with_fontconfig()
    if font_path:
        return font_path

    candidates = [
        # Linux fallback paths
        os.path.expanduser("~/.fonts/NotoSansSC.ttf"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in candidates:
        if os.path.exists(fp) and os.path.getsize(fp) > 1000:
            return fp
    return None


def get_cjk_font_path() -> Optional[str]:
    """Cached wrapper for ``_find_cjk_font_path``."""
    global _CACHED_FONT_PATH
    if _CACHED_FONT_PATH is None:
        _CACHED_FONT_PATH = _find_cjk_font_path() or ""
    return _CACHED_FONT_PATH or None


def setup_matplotlib_cjk() -> str:
    """Register a CJK font with matplotlib and return the family name.

    Subsequent ``plt`` calls use the registered font automatically.
    The result is cached — repeated calls are free.
    """
    global _CACHED_FONT_NAME
    if _CACHED_FONT_NAME is not None:
        return _CACHED_FONT_NAME

    fp = get_cjk_font_path()
    if fp:
        from matplotlib import font_manager as fm
        try:
            fm.fontManager.addfont(fp)
            _CACHED_FONT_NAME = fm.FontProperties(fname=fp).get_name()
            logger.debug("Matplotlib CJK font registered: %s → %s", fp, _CACHED_FONT_NAME)
            return _CACHED_FONT_NAME
        except Exception as exc:
            logger.warning("Failed to register CJK font %s: %s", fp, exc)

    # Fallback: scan system font list for a known CJK family name
    candidates = [
        "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei",
        "SimHei", "Microsoft YaHei", "PingFang SC", "Heiti SC",
    ]
    from matplotlib import font_manager as fm
    for name in candidates:
        for f in fm.fontManager.ttflist:
            if name.lower() in f.name.lower():
                _CACHED_FONT_NAME = f.name
                logger.debug("Matplotlib fallback CJK font: %s", _CACHED_FONT_NAME)
                return _CACHED_FONT_NAME

    _CACHED_FONT_NAME = "sans-serif"
    logger.warning("No CJK font found — charts may render as tofu")
    return _CACHED_FONT_NAME


def setup_reportlab_cjk() -> str:
    """Register a CJK font with reportlab and return the PDF font name.

    Returns ``"CJK"`` when a TrueType font can be embedded.  Debian's
    ``fonts-noto-cjk`` package provides CFF-based TTC files, which ReportLab's
    ``TTFont`` cannot embed, so fall back to ReportLab's built-in Chinese CID
    font before using Helvetica as a last resort.
    """
    from reportlab.pdfbase import pdfmetrics

    fp = get_cjk_font_path()
    if fp:
        from reportlab.pdfbase.ttfonts import TTFont
        try:
            pdfmetrics.registerFont(TTFont("CJK", fp))
            logger.debug("Reportlab CJK font registered: %s", fp)
            return "CJK"
        except Exception as exc:
            logger.warning("Failed to register reportlab CJK font: %s", exc)

    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        logger.warning("Using ReportLab built-in STSong-Light CID font for CJK PDF text")
        return "STSong-Light"
    except Exception as exc:
        logger.warning("Failed to register ReportLab CJK CID fallback: %s", exc)
    return "Helvetica"
