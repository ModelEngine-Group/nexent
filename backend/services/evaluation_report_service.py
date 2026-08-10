"""Evaluation PDF report generation — matplotlib charts + reportlab layout."""

import io
import json
import logging
import os
import tempfile
from datetime import datetime

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from consts.evaluation_report_labels import get_report_labels
from database.agent_evaluation_db import get_agent_evaluation
from services.agent_evaluation_service import (
    _load_all_evaluation_cases,
    get_evaluation_stats_impl,
)
from utils.font_utils import setup_matplotlib_cjk, setup_reportlab_cjk


logger = logging.getLogger(__name__)


# ── Chart drawing ───────────────────────────────────────────────────


def _draw_score_chart(scores: dict, output: io.BytesIO, font_name: str):
    """Draw a horizontal bar chart of per-evaluator mean scores.

    Layout rules
    ------------
    * Fig height grows with the number of evaluators so bars don't overlap
      when a run configures > 4 evaluators (0.5 inch per bar + 1.2 inch pad).
    * X-axis is **hidden**; the numeric label at the end of each bar is the
      sole value read-out for the PDF (labels keep the page dense).
    * ``x_max`` has a hard floor at 1.15 so a run with only perfect 1.0
      scores still has breathing room between the score label and the right
      edge (otherwise 1.00 would be clipped against the canvas).
    * ``colors`` is a fixed 7-tone palette; runs with more than 7 evaluators
      cycle from the start — this is intentionally simple because the chart
      is only read visually in a PDF, not semantically parsed.
    * Output is written to ``output`` as a transparent-background PNG at
      150 DPI (print-friendly but not heavy).
    """
    import matplotlib

    # Backend switch MUST happen before pyplot import to avoid opening a
    # GUI window on developer workstations (Linux + macOS).
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(scores.keys())
    values = [scores[n] for n in names]
    colors = [
        "#1677ff",
        "#52c41a",
        "#faad14",
        "#ff7a45",
        "#722ed1",
        "#13c2c2",
        "#eb2f96",
    ]

    fig, ax = plt.subplots(figsize=(7, 0.5 * len(names) + 1.2))
    y_pos = range(len(names))
    bars = ax.barh(
        y_pos,
        values,
        height=0.55,
        color=colors[: len(names)],
        edgecolor="white",
        linewidth=0.8,
    )

    max_val = max(values) if values else 1.0
    x_max = max(1.15, max_val * 1.2 + 0.05)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + max(0.02, x_max * 0.01),
            bar.get_y() + bar.get_height() / 2,
            f"{val:.2f}",
            va="center",
            fontsize=11,
            fontweight="bold",
            fontproperties=matplotlib.font_manager.FontProperties(family=font_name),
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=10)
    for label in ax.get_yticklabels():
        label.set_fontproperties(
            matplotlib.font_manager.FontProperties(family=font_name)
        )
    ax.set_xlim(0, x_max)
    ax.xaxis.set_visible(False)
    for spine in ("top", "right", "bottom", "left"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(left=False)

    fig.savefig(
        output,
        format="png",
        dpi=150,
        bbox_inches="tight",
        transparent=True,
        pad_inches=0.1,
    )
    plt.close(fig)


def _draw_histogram(all_scores: list, output: io.BytesIO, font_name: str):
    """Draw a 5-bucket per-case average-score histogram.

    Input values are ASSUMED already normalized to [0, 1]; the
    normalization is done by the caller in ``generate_agent_evaluation_report_impl``
    using ``evaluator_ranges`` so custom [0, 100] ranges don't collapse
    everything into the top bucket.

    Bucket edges are half-open on the right except the last bucket, which
    includes the endpoint 1.0; ``1.01`` is used as the sentinel upper
    bound so ``s == 1.0`` still matches the 0.8–1.0 range via
    ``buckets[4] <= s < buckets[5]``.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    buckets = [0, 0.2, 0.4, 0.6, 0.8, 1.01]
    colors = ["#ff4d4f", "#ff7a45", "#faad14", "#a0d911", "#52c41a"]
    labels = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]

    fig, ax = plt.subplots(figsize=(7, 2.5))
    counts = [0] * 5
    for s in all_scores:
        for i in range(5):
            if buckets[i] <= s < buckets[i + 1]:
                counts[i] += 1
                break

    bars = ax.bar(labels, counts, color=colors, edgecolor="white", width=0.7)
    for bar, count in zip(bars, counts):
        if count > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.3,
                str(count),
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    ax.set_ylabel(
        "Cases",
        fontsize=10,
        fontproperties=matplotlib.font_manager.FontProperties(family=font_name),
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=9)
    for label in ax.get_xticklabels():
        label.set_fontproperties(
            matplotlib.font_manager.FontProperties(family=font_name)
        )

    fig.savefig(
        output,
        format="png",
        dpi=150,
        bbox_inches="tight",
        transparent=True,
        pad_inches=0.1,
    )
    plt.close(fig)


# ── Module-level helpers ────────────────────────────────────────────


def _fmt(iso):
    """Format an ISO timestamp string to MM/DD HH:MM display format."""
    if not iso:
        return "-"
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d.strftime("%m/%d %H:%M")
    except Exception:
        logger.debug("Failed to format timestamp %r", iso, exc_info=True)
        return str(iso)[:16]


def _mk_style(name, cn_font, **kw):
    """Create a reportlab ParagraphStyle with sensible CJK defaults."""
    defaults = {
        "fontName": cn_font,
        "fontSize": 10,
        "leading": 16,
        "textColor": HexColor("#333333"),
    }
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)


def _metric_card(val_text, label, bg, s_metric_val, s_metric_lbl):
    """Build a single metric-card table (value + label) with a background colour."""
    inner = Table(
        [
            [Paragraph(val_text, s_metric_val)],
            [Paragraph(label, s_metric_lbl)],
        ],
        colWidths=[48 * mm],
    )
    inner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return inner


# ── Section builders ────────────────────────────────────────────────


def _build_report_header(story, L, styles, agent_name, agent_evaluation_id, now_str):
    """Add report title, subtitle, and horizontal rule to the story."""
    story.append(Paragraph(L["TITLE"], styles["s_report_title"]))
    story.append(
        Paragraph(
            L["SUBTITLE"].format(
                agent=agent_name, id=str(agent_evaluation_id), time=now_str
            ),
            styles["s_subtitle"],
        )
    )
    story.append(
        HRFlowable(width="100%", thickness=2, color=styles["blue"], spaceAfter=0)
    )
    story.append(Spacer(1, 6 * mm))


def _build_report_metrics(story, L, styles, overall, pass_rate, total):
    """Add the three metric cards (score / pass-rate / total) in a row."""
    s_metric_val = styles["s_metric_val"]
    s_metric_lbl = styles["s_metric_lbl"]

    metrics = [
        _metric_card(
            f"{overall:.2f}" if overall is not None else "-",
            L["METRIC_SCORE"],
            HexColor("#f6ffed"),
            s_metric_val,
            s_metric_lbl,
        ),
        _metric_card(
            pass_rate,
            L["METRIC_PASS_RATE"],
            HexColor("#e6f7ff"),
            s_metric_val,
            s_metric_lbl,
        ),
        _metric_card(
            str(total),
            L["METRIC_TOTAL"],
            HexColor("#f9f0ff"),
            s_metric_val,
            s_metric_lbl,
        ),
    ]
    metric_row = Table(
        [[metrics[0], metrics[1], metrics[2]]], colWidths=[52 * mm, 52 * mm, 52 * mm]
    )
    metric_row.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(metric_row)
    story.append(Spacer(1, 6 * mm))


def _build_report_config(story, L, styles, run, avg_scores, is_no_set, cn_font):
    """Add the configuration / meta-info section with a two-column table."""
    gray = styles["gray"]
    dark = styles["dark"]

    story.append(Paragraph(L["SECTION_CONFIG"], styles["s_h1"]))

    meta_data = [
        [
            L["META_TARGET"],
            run.get("agent_name") or f"#{run.get('agent_id')}",
            L["META_SET"],
            (run.get("evaluation_set_name") or "-")
            + (L["META_NO_SET"] if is_no_set else ""),
        ],
        [
            L["META_MODEL"],
            run.get("judge_model_name") or "-",
            L["META_VERSION"],
            f"v{run.get('agent_version_no', '-')}",
        ],
        [
            L["META_CREATED"],
            _fmt(run.get("create_time")),
            L["META_COMPLETED"],
            _fmt(run.get("update_time"))
            if run.get("status") in ("COMPLETED", "FAILED")
            else "-",
        ],
        [
            L["META_EVALUATORS"],
            str(len(avg_scores)),
            L["META_PROGRESS"],
            f"{run.get('progress_done', 0)} / {run.get('progress_total', 0)}",
        ],
    ]
    meta_table = Table(meta_data, colWidths=[30 * mm, 56 * mm, 30 * mm, 56 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), cn_font),
                ("FONTSIZE", (0, 0), (0, -1), 8),
                ("TEXTCOLOR", (0, 0), (0, -1), gray),
                ("FONTSIZE", (1, 0), (1, -1), 9),
                ("TEXTCOLOR", (1, 0), (1, -1), dark),
                ("FONTSIZE", (2, 0), (2, -1), 8),
                ("TEXTCOLOR", (2, 0), (2, -1), gray),
                ("FONTSIZE", (3, 0), (3, -1), 9),
                ("TEXTCOLOR", (3, 0), (3, -1), dark),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, HexColor("#f0f0f0")),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 4 * mm))


def _build_report_charts_section(story, L, styles, avg_scores, chart_buf, hist_buf):
    """Add analysis text and chart/ histogram images. Returns (chart_path, hist_path)."""
    chart_path = hist_path = None
    s_h1 = styles["s_h1"]
    s_h2 = styles["s_h2"]
    s_body = styles["s_body"]

    story.append(PageBreak())
    story.append(Paragraph(L["SECTION_ANALYSIS"], s_h1))

    if avg_scores:
        best = max(avg_scores.items(), key=lambda x: x[1])
        worst = min(avg_scores.items(), key=lambda x: x[1])
        analysis_text = L["ANALYSIS_TEMPLATE"].format(
            n=str(len(avg_scores)),
            best=best[0],
            best_score=best[1],
            worst=worst[0],
            worst_score=worst[1],
        )
        story.append(Paragraph(analysis_text, s_body))
        story.append(Spacer(1, 2 * mm))

    # Score chart
    if chart_buf.getvalue():
        chart_buf.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tf.write(chart_buf.getvalue())
            chart_path = tf.name
        img_h = 18 * mm + 8 * mm * len(avg_scores)
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(L["CHART_SCORES"], s_h2))
        story.append(Image(chart_path, width=165 * mm, height=img_h))

    # Histogram
    if hist_buf.getvalue():
        hist_buf.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tf.write(hist_buf.getvalue())
            hist_path = tf.name
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(L["CHART_DISTRIBUTION"], s_h2))
        story.append(Image(hist_path, width=165 * mm, height=55 * mm))

    return chart_path, hist_path


def _coerce_case_score(scores):
    """Coerce a case score from a JSON string to its native type.

    Returns ``(scores, failed)`` where ``failed`` is 1 if the legacy JSON
    decode failed, else 0.  Failures are aggregated (not logged per row)
    so a 10 000-case run doesn't spam 10 000 warning rows.
    """
    if not isinstance(scores, str):
        return scores, 0
    try:
        return json.loads(scores), 0
    except Exception:
        # Aggregate failures, don't log per row — noisy on legacy tenants.
        return scores, 1


def _format_case_score_text(scores, status, thmap):
    """Format a case's score into an HTML-colored paragraph string.

    Colours use the **per-evaluator** ``pass_threshold`` (NOT hard-coded
    0.5) so the PDF colours agree with what the analysis engine decided.
    """
    if isinstance(scores, dict):
        score_parts = []
        for k, v in scores.items():
            if isinstance(v, (int, float)):
                th = float(thmap.get(str(k), 0.5))
                sc = "#52c41a" if float(v) >= th else "#ff4d4f"
                score_parts.append(f"<font color='{sc}'>{k}: <b>{v:.2f}</b></font>")
        return "<br/>".join(score_parts)
    if isinstance(scores, (int, float)):
        if status == "pass":
            sc = "#52c41a"
        elif status == "fail":
            sc = "#ff4d4f"
        else:
            sc = "#52c41a" if scores >= 0.5 else "#ff4d4f"
        return f"<font color='{sc}'><b>{scores:.2f}</b></font>"
    return str(scores or "-")


def _format_status_tag(status, L):
    """Format a pass/fail status into a colored HTML tag string."""
    if status == "pass":
        return f"<font color='#52c41a'><b>{L['PASS_LABEL']}</b></font>"
    if status == "fail":
        return f"<font color='#ff4d4f'><b>{L['FAIL_LABEL']}</b></font>"
    return status


def _apply_zebra_striping(case_table, num_rows, light_gray):
    """Apply zebra striping to even data rows of a case table.

    Even rows get a light-grey background so the reader can visually pair
    a query with its score across page folds.
    """
    for row_idx in range(2, num_rows):
        if row_idx % 2 == 0:
            case_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, row_idx - 1), (-1, row_idx - 1), light_gray),
                    ]
                )
            )


def _build_report_case_table(
    story, L, styles, all_cases, cn_font, evaluator_thresholds=None
) -> int:
    """Add the per-case detail table (one section, always on its own page).

    Returns
    -------
    coerce_fails : int
        Number of rows where ``score`` was still a raw JSON string AND the
        legacy decode failed.  The caller batches this into a single
        summary log so a 10 000-case run doesn't spam 10 000 warning rows.

    Columns
    -------
    * **Index** – 1-based row number for manual cross-referencing with the
      analysis report.
    * **Query** – user prompt, hard-capped at 150 chars so the PDF column
      doesn't grow to >20 lines per row.
    * **Score** – per-evaluator coloured values.  Colours use the
      **per-evaluator** ``pass_threshold`` (NOT hard-coded 0.5) so the PDF
      colours agree with what the analysis engine decided.
    * **Result** – Pass/Fail tag coloured green/red.

    Presentation rules
    ------------------
    * ``repeatRows=1`` – on multi-page PDFs the header row repeats on every
      page (reportlab built-in, no manual handling).
    * Even rows get a light-grey background so the reader can visually pair
      a query with its score across page folds (zebra striping).
    """
    blue = styles["blue"]
    light_gray = styles["light_gray"]
    s_h1 = styles["s_h1"]
    s_body = styles["s_body"]
    s_bold = styles["s_bold"]
    thmap = evaluator_thresholds or {}

    story.append(PageBreak())
    story.append(Paragraph(L["SECTION_DETAILS"], s_h1))
    story.append(Spacer(1, 3 * mm))

    case_header = [
        L["COL_HEADER_INDEX"],
        L["COL_HEADER_QUERY"],
        L["COL_HEADER_SCORE"],
        L["COL_HEADER_RESULT"],
    ]
    col_widths = [7 * mm, 76 * mm, 47 * mm, 16 * mm]
    case_data = [case_header]
    coerce_fails = 0
    for i, c in enumerate(all_cases):
        inputs = c.get("inputs") or {}
        query = (inputs.get("query") or "")[:150]
        scores = c.get("score")
        status = c.get("pass_status") or ""
        scores, failed = _coerce_case_score(scores)
        coerce_fails += failed
        score_text = _format_case_score_text(scores, status, thmap)
        status_tag = _format_status_tag(status, L)
        case_data.append(
            [
                Paragraph(str(i + 1), s_body),
                Paragraph(query, s_body),
                Paragraph(score_text, s_body),
                Paragraph(status_tag, s_bold),
            ]
        )

    case_table = Table(case_data, colWidths=col_widths, repeatRows=1)
    case_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), cn_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), white),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e0e0e0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    _apply_zebra_striping(case_table, len(case_data), light_gray)

    story.append(case_table)
    story.append(Spacer(1, 4 * mm))
    return coerce_fails


def _count_annotation_values(annotation_data, sid):
    """Count annotation values for a given schema across all cases.

    Option values with zero occurrences are **not** shown — the PDF would
    otherwise grow large on long option lists (e.g. free-text schemas).
    """
    value_counts: dict = {}
    for case_anns in annotation_data.values():
        for a in case_anns:
            if a["schema_id"] == sid:
                v = a.get("value", "")
                if v:
                    value_counts[v] = value_counts.get(v, 0) + 1
    return value_counts


def _build_annotation_rows(value_counts, total, s_body):
    """Build annotation table rows with bar chart visualization.

    Each row contains the option value, a proportional block-character bar,
    and the count / percentage.  ``max_c`` drives the relative bar length so
    the longest bar always fills the column.
    """
    max_c = max(value_counts.values()) if value_counts else 1
    anno_rows = []
    for val, cnt in sorted(value_counts.items(), key=lambda x: -x[1]):
        pct = int(cnt / total * 100) if total > 0 else 0
        bar_len = int(cnt / max_c * 20) if max_c > 0 else 0
        bar = "█" * bar_len
        anno_rows.append(
            [
                Paragraph(val, s_body),
                Paragraph(
                    f"<font color='#1677ff'>{bar}</font>",
                    ParagraphStyle("bar2", fontName="Courier", fontSize=7, leading=10),
                ),
                Paragraph(f"{cnt} ({pct}%)", s_body),
            ]
        )
    return anno_rows


def _build_report_annotations(
    story, labels, styles, cn_font, tenant_id, agent_evaluation_id, total, run
):
    """Add the annotations distribution section (one sub-table per schema).

    Import is lazy because annotation support is an optional feature of
    evaluator runs; hosts that disable the feature shouldn't pay an import
    cost in the default hot path (the PDF worker).  If the import fails the
    section is **silently skipped** — operators can inspect the ``import_failed``
    counter in the top-level summary log to detect broken installations.

    Table semantics
    ---------------
    * Each **enabled schema** (listed in ``run.annotation_schema_ids``)
      gets its own 2-column table: the option value on the left and its
      count / percentage on the right.
    * Schemas that exist but are NOT listed in the run are excluded so the
      PDF only contains the dimensions the user actually asked for.
    * Option values with zero occurrences are **not** shown — the PDF would
      otherwise grow large on long option lists (e.g. free-text schemas).
    * The section sits on its own page because tables can be tall; a
      preceding ``PageBreak`` keeps pagination predictable.
    """
    try:
        from database.evaluation_annotation_db import (
            list_annotation_schemas,
            list_annotations_by_evaluation_id,
        )
    except Exception as exc:
        logger.exception("Failed to import annotation DB: %s", exc)
        return

    try:
        annotation_data = list_annotations_by_evaluation_id(
            tenant_id=tenant_id, agent_evaluation_id=agent_evaluation_id
        )
        schemas = list_annotation_schemas(tenant_id=tenant_id)
        enabled_sids = run.get("annotation_schema_ids") or []
        active_schemas = [s for s in schemas if s["schema_id"] in enabled_sids]
        if not active_schemas:
            return

        s_h1 = styles["s_h1"]
        s_h2 = styles["s_h2"]
        s_body = styles["s_body"]
        s_small = styles["s_small"]

        story.append(PageBreak())
        story.append(Paragraph(labels["SECTION_ANNOTATIONS"], s_h1))
        story.append(Spacer(1, 4 * mm))

        for schema in active_schemas:
            sid = schema["schema_id"]
            value_counts = _count_annotation_values(annotation_data, sid)

            total_annotated = sum(value_counts.values())
            coverage = f"{total_annotated}/{total}" if total > 0 else "0"

            story.append(
                Paragraph(
                    f"<b>{schema['name']}</b> — {labels['ANNOTATION_COVERAGE'].format(coverage=coverage)}",
                    s_h2,
                )
            )
            story.append(Spacer(1, 2 * mm))

            if not value_counts:
                story.append(Paragraph(labels["ANNOTATION_NO_DATA"], s_small))
                story.append(Spacer(1, 2 * mm))
                continue

            anno_rows = _build_annotation_rows(value_counts, total, s_body)
            anno_table = Table(anno_rows, colWidths=[40 * mm, 70 * mm, 50 * mm])
            anno_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), cn_font),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(anno_table)
            story.append(Spacer(1, 4 * mm))
    except Exception as exc:
        logger.exception("Failed to add annotation section to report: %s", exc)


# ── Report data helpers ─────────────────────────────────────────────


def _load_evaluator_thresholds_for_report(run: dict, tenant_id: str):
    """Load evaluator thresholds and score ranges for PDF report.

    Missing metadata falls back to standard [0,1], threshold=0.5.
    Returns (thresholds, ranges, error_count).
    """
    evaluator_thresholds: dict[str, float] = {}
    evaluator_ranges: dict[str, tuple[float, float]] = {}
    eval_meta_load_errors = 0
    try:
        from database.evaluator_db import get_evaluator

        eids = (run.get("evaluator_config") or {}).get("evaluator_ids", []) or []
        for eid in eids:
            try:
                ev = get_evaluator(int(eid), tenant_id)
            except Exception:
                eval_meta_load_errors += 1
                ev = None
            if not ev:
                continue
            name = str(ev.get("name") or "")
            if not name:
                continue
            evaluator_thresholds[name] = float(ev.get("pass_threshold") or 0.5)
            rmin = float(ev.get("score_range_min") or 0.0)
            rmax = float(ev.get("score_range_max") or 1.0)
            evaluator_ranges[name] = (rmin, rmax)
    except Exception:
        logger.warning(
            "Failed to load evaluator metadata for PDF report", exc_info=True
        )
    return evaluator_thresholds, evaluator_ranges, eval_meta_load_errors


def _compute_normalized_avg_scores(all_cases: list, evaluator_ranges: dict) -> tuple:
    """Compute per-case normalized average scores for histogram.

    Each evaluator score is normalized into [0,1] using its own score_range
    so custom [0,100] ranges don't collapse everything into the top bucket.
    Returns (all_avg_scores, histogram_coerce_fails).
    """
    all_avg_scores: list = []
    histogram_coerce_fails = 0
    for c in all_cases:
        scores = c.get("score")
        if isinstance(scores, str):
            try:
                scores = json.loads(scores)
            except Exception:
                histogram_coerce_fails += 1
                scores = {}
        if isinstance(scores, dict):
            normalized_vals = []
            for k, v in scores.items():
                if not isinstance(v, (int, float)):
                    continue
                rng = evaluator_ranges.get(str(k))
                if rng:
                    rmin, rmax = rng
                    if rmax > rmin:
                        nv = (float(v) - rmin) / (rmax - rmin)
                    else:
                        nv = 0.0
                else:
                    nv = float(v)
                nv = max(0.0, min(1.0, nv))
                normalized_vals.append(nv)
            if normalized_vals:
                all_avg_scores.append(sum(normalized_vals) / len(normalized_vals))
    return all_avg_scores, histogram_coerce_fails


def _build_report_styles(cn_font: str) -> dict:
    """Build the style objects dictionary for the PDF report."""
    dark = HexColor("#1a1a1a")
    gray = HexColor("#666666")
    return {
        "blue": HexColor("#1677ff"),
        "gray": gray,
        "light_gray": HexColor("#f5f5f5"),
        "dark": dark,
        "s_report_title": _mk_style(
            "RT", cn_font, fontSize=20, leading=24, textColor=dark, spaceAfter=2
        ),
        "s_subtitle": _mk_style(
            "ST", cn_font, fontSize=10, leading=14, textColor=gray, spaceAfter=10
        ),
        "s_h1": _mk_style(
            "H1",
            cn_font,
            fontSize=14,
            leading=18,
            textColor=dark,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "s_h2": _mk_style(
            "H2",
            cn_font,
            fontSize=11,
            leading=14,
            textColor=dark,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "s_body": _mk_style("BD", cn_font),
        "s_small": _mk_style("SM", cn_font, fontSize=9, leading=13, textColor=gray),
        "s_bold": _mk_style("BDb", cn_font, textColor=dark),
        "s_metric_val": _mk_style(
            "MV", cn_font, fontSize=24, leading=28, textColor=dark
        ),
        "s_metric_lbl": _mk_style(
            "ML", cn_font, fontSize=9, leading=12, textColor=gray
        ),
        "s_footer": _mk_style(
            "FT", cn_font, fontSize=8, leading=10, textColor=HexColor("#999999")
        ),
    }


# ── PDF report orchestrator ─────────────────────────────────────────


def _generate_report_charts(avg_scores, all_avg_scores):
    """Generate matplotlib score chart and histogram into in-memory buffers.

    Returns ``(chart_buf, hist_buf, chart_gen_ok)``.  Failures are swallowed
    and logged as a single WARNING so the PDF still renders (the charts
    section is omitted, not the whole report).
    """
    chart_buf = io.BytesIO()
    hist_buf = io.BytesIO()
    chart_gen_ok = True
    try:
        font_name = setup_matplotlib_cjk()
        if avg_scores:
            _draw_score_chart(avg_scores, chart_buf, font_name)
        if all_avg_scores:
            _draw_histogram(all_avg_scores, hist_buf, font_name)
    except Exception as exc:
        chart_gen_ok = False
        logger.warning("Chart generation failed: %s", exc)
    return chart_buf, hist_buf, chart_gen_ok


def _compute_score_level(pass_rate_val, L):
    """Compute the localized score-level label from the pass rate.

    Thresholds: >=0.8 excellent, >=0.5 good, otherwise needs improvement.
    """
    if pass_rate_val >= 0.8:
        return L["SCORE_EXCELLENT"]
    if pass_rate_val >= 0.5:
        return L["SCORE_GOOD"]
    return L["SCORE_NEEDS_IMPROVEMENT"]


def _compute_quality_level(top_count, total, L):
    """Compute the localized quality-level label from the top-score case ratio.

    Thresholds: >=70% high, >=40% medium, otherwise low.  Extracted as a
    standalone function so the nested conditional expression reads as a flat
    branch sequence (SonarCloud).
    """
    if top_count >= total * 0.7:
        return L["QUALITY_HIGH"]
    if top_count >= total * 0.4:
        return L["QUALITY_MEDIUM"]
    return L["QUALITY_LOW"]


def _cleanup_temp_chart_files(chart_path, hist_path):
    """Remove temporary chart files; returns the count of cleanup failures.

    Temp-file cleanup failures are WARNed per-file but the PDF is still
    returned (unlink failures don't corrupt the in-memory ``buf``).
    """
    cleanup_fails = 0
    for p in (chart_path, hist_path):
        if p:
            try:
                os.unlink(p)
            except Exception as exc:
                cleanup_fails += 1
                logger.warning("Failed to remove temp chart file %s: %s", p, exc)
    return cleanup_fails


def generate_agent_evaluation_report_impl(
    agent_evaluation_id: int,
    tenant_id: str,
    language: str = "zh",
) -> tuple[bytes, int]:
    """Build a language-localized PDF evaluation report.

    Output
    ------
    Returns a ``(pdf_bytes, fail_count)`` tuple.  ``fail_count`` is the
    numeric count of FAILED cases; callers (e.g. the HTTP endpoint)
    typically use it for response headers or retry decisions without
    re-parsing the PDF.  The PDF itself is an A4 document with seven
    sections, all built from reportlab ``Flowable`` objects so pagination
    is automatic:

    1. **Header** – agent name, run id, report generation timestamp.
    2. **Executive summary** – free-text paragraph generated from the
       localized ``SUMMARY_TEMPLATE``; contains status, overall score,
       evaluator list, pass count / fail count, pass rate.
    3. **Metric cards** – overall score / pass rate / total case count in
       a three-column coloured card row.
    4. **Configuration section** – evaluator list with thresholds, dataset
       metadata (either evaluation-set name or "one-shot" no-set label),
       judge-model card for LLM evaluators.
    5. **Charts section** – per-evaluator mean score bar chart + per-case
       normalized average-score histogram.  Both are rendered by matplotlib
       as PNG and embedded via ``Image`` flowables.
    6. **Case details table** – every case with truncated query,
       per-evaluator coloured scores and pass/fail tag.
    7. **Annotations distribution** – one sub-table per enabled annotation
       schema with coverage count and option frequencies.

    Logging
    -------
    * No per-case / per-row prints — the section builders aggregate
      counts of legacy-format rows into ``histogram_coerce_fails`` /
      ``table_coerce_fails`` and we emit a single INFO log at the very
      end.
    * If the DB layer fails to fetch evaluator metadata (e.g. broken FK
      after a hard delete) we use the default [0, 1] range with threshold
      0.5 and raise a single WARNING (repeated failures per evaluator
      would swamp the log if unguarded).
    * Temp-file cleanup failures are WARNed per-file but the PDF is still
      returned (unlink failures don't corrupt the in-memory ``buf``).
    """
    L = get_report_labels(language)
    run = get_agent_evaluation(
        agent_evaluation_id=agent_evaluation_id, tenant_id=tenant_id
    )

    # ── Load all cases for table display ──────────────────────────────────
    all_cases = _load_all_evaluation_cases(agent_evaluation_id, tenant_id)

    # ── Fetch stats from service layer ────────────────────────────────────
    stats = get_evaluation_stats_impl(agent_evaluation_id, tenant_id)
    pass_count = stats["pass_count"]
    fail_count = stats["fail_count"]
    total = stats["total"]
    avg_scores = {item["name"]: item["avg"] for item in stats["per_evaluator"]}

    # ── Load evaluator metadata: name → threshold + score_range ─────────────
    evaluator_thresholds, evaluator_ranges, eval_meta_load_errors = (
        _load_evaluator_thresholds_for_report(run, tenant_id)
    )

    # ── Compute per-case average scores for histogram ─────────────────────
    all_avg_scores, histogram_coerce_fails = _compute_normalized_avg_scores(
        all_cases, evaluator_ranges
    )

    # ── Register CJK fonts ────────────────────────────────────────────────
    cn_font = setup_reportlab_cjk()

    # ── Generate matplotlib charts ────────────────────────────────────────
    chart_buf, hist_buf, chart_gen_ok = _generate_report_charts(
        avg_scores, all_avg_scores
    )

    # ── Build style objects ───────────────────────────────────────────────
    styles = _build_report_styles(cn_font)

    # ── Derived values ────────────────────────────────────────────────────
    agent_name = run.get("agent_name") or f"#{run.get('agent_id')}"
    is_no_set = (run.get("evaluator_config") or {}).get("no_set_mode", False)
    overall = run.get("score_overall")
    pass_rate = f"{pass_count / total * 100:.0f}%" if total else "-"
    top_count = sum(1 for s in all_avg_scores if s >= 0.8)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Build PDF ─────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Agent Evaluation Report - {agent_evaluation_id}",
    )

    story: list = []

    # Header
    _build_report_header(story, L, styles, agent_name, agent_evaluation_id, now_str)

    # Executive summary
    status_map = {
        "COMPLETED": L["STATUS_COMPLETED"],
        "RUNNING": L["STATUS_RUNNING"],
        "PENDING": L["STATUS_PENDING"],
        "FAILED": L["STATUS_FAILED"],
    }
    status_label = status_map.get(run.get("status", ""), run.get("status", ""))
    pass_rate_val = pass_count / total if total else 0.0
    score_level = _compute_score_level(pass_rate_val, L)
    eval_names = "、".join(list(avg_scores.keys())[:5]) if avg_scores else L["SCORE_NA"]
    overall_str = f"{overall:.2f}" if overall is not None else "N/A"
    quality = _compute_quality_level(top_count, total, L)

    summary_text = L["SUMMARY_TEMPLATE"].format(
        agent=f"<b>{agent_name}</b>",
        total=str(total),
        status=f"<b>{status_label}</b>",
        overall=f"<b>{overall_str}</b>",
        level=score_level,
        evaluator_count=str(len(avg_scores)),
        evaluator_names=eval_names,
        pass_count=str(pass_count),
        fail_count=str(fail_count),
        pass_rate=pass_rate,
    )
    if total:
        summary_text += L["SUMMARY_EXTRA"].format(
            top=str(top_count), total=str(total), quality=quality
        )
    story.append(Paragraph(L["SECTION_OVERVIEW"], styles["s_h1"]))
    story.append(Paragraph(summary_text, styles["s_body"]))
    story.append(Spacer(1, 5 * mm))

    # Sections
    _build_report_metrics(story, L, styles, overall, pass_rate, total)
    _build_report_config(story, L, styles, run, avg_scores, is_no_set, cn_font)
    chart_path, hist_path = _build_report_charts_section(
        story, L, styles, avg_scores, chart_buf, hist_buf
    )
    table_coerce_fails = _build_report_case_table(
        story, L, styles, all_cases, cn_font, evaluator_thresholds=evaluator_thresholds
    )
    _build_report_annotations(
        story, L, styles, cn_font, tenant_id, agent_evaluation_id, total, run
    )

    # Footer
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#e8e8e8")))
    story.append(Paragraph(L["FOOTER"].format(time=now_str), styles["s_footer"]))

    doc.build(story)

    # ── Cleanup temp chart files ──────────────────────────────────────────
    cleanup_fails = _cleanup_temp_chart_files(chart_path, hist_path)

    pdf_bytes = buf.getvalue()
    pdf_bytes_len_kb = len(pdf_bytes) // 1024
    logger.info(
        "generate_agent_evaluation_report_impl: run_id=%s tenant=%s language=%s "
        "total_cases=%s pass_count=%s fail_count=%s evaluators=%s pages_fetched=%s "
        "histogram_samples=%s top_0.8_count=%s eval_meta_load_errors=%s "
        "histogram_coerce_fails=%s table_coerce_fails=%s cleanup_fails=%s "
        "chart_gen_ok=%s pdf_kb=%s",
        agent_evaluation_id,
        tenant_id,
        language,
        total,
        pass_count,
        fail_count,
        len(evaluator_thresholds),
        (len(all_cases) + 199) // 200,
        len(all_avg_scores),
        top_count,
        eval_meta_load_errors,
        histogram_coerce_fails,
        table_coerce_fails,
        cleanup_fails,
        chart_gen_ok,
        pdf_bytes_len_kb,
    )
    return pdf_bytes, fail_count
