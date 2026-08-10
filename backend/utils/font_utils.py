"""Shared CJK font utilities for matplotlib and reportlab.

Consolidates font discovery, registration and fallback logic that was
previously duplicated between ``agent_evaluation_service`` and
``evaluation_report_service``.  Both callers use the same cached
results so fonts are registered once per process lifetime.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── module-level cache ──────────────────────────────────────────────
_CACHED_FONT_PATH: Optional[str] = None   # path to CJK .ttf file, or "" if not found
_CACHED_FONT_NAME: Optional[str] = None   # matplotlib family name, or "" if fallback


def _find_cjk_font_path() -> Optional[str]:
    """Return the filesystem path to an available CJK font, or ``None``."""
    candidates = [
        # Windows
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        # Linux / macOS
        os.path.expanduser("~/.fonts/NotoSansSC.ttf"),
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

    Returns ``"CJK"`` on success, ``"Helvetica"`` on failure.
    """
    fp = get_cjk_font_path()
    if fp:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        try:
            pdfmetrics.registerFont(TTFont("CJK", fp))
            logger.debug("Reportlab CJK font registered: %s", fp)
            return "CJK"
        except Exception as exc:
            logger.warning("Failed to register reportlab CJK font: %s", exc)
    return "Helvetica"
