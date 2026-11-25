// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Sanitize an AIDP TABLE chunk's HTML for preview/rendering.
 *
 * Real AIDP formats table chunks as "<chapter title>\n\n<table>...</table>"
 * (verified 2026-11-20). The chunk text is derived from user-uploaded
 * documents, so the HTML is never rendered raw: it is parsed and rebuilt from
 * a narrow table-only whitelist, dropping every other tag and attribute.
 *
 * Rebuilding works on DOM nodes instead of string concatenation: text is
 * copied into text nodes, never read back as HTML and interpolated.
 */

export interface AidpTableHtml {
  /** Text before the table markup (the chapter title AIDP prepends). */
  caption: string;
  /** Rebuilt table containing only whitelisted tags/attributes. */
  table: HTMLTableElement;
}

const ALLOWED_TAGS = new Set([
  "table",
  "thead",
  "tbody",
  "tfoot",
  "tr",
  "th",
  "td",
  "caption",
  "colgroup",
  "col",
]);
const SPAN_ATTRS = new Set(["colspan", "rowspan"]);

const rebuildChildren = (element: Element): Node[] => {
  const parts: Node[] = [];
  for (const node of Array.from(element.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push(document.createTextNode(node.nodeValue ?? ""));
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      parts.push(...rebuildElement(node as Element));
    }
  }
  return parts;
};

const rebuildElement = (element: Element): Node[] => {
  const tag = element.tagName.toLowerCase();
  const children = rebuildChildren(element);
  if (!ALLOWED_TAGS.has(tag)) {
    // Unknown wrapper: keep its sanitized children without the tag.
    return children;
  }
  const clean = document.createElement(tag);
  if (tag === "col") return [clean];
  if (tag === "td" || tag === "th") {
    for (const attr of SPAN_ATTRS) {
      const raw = element.getAttribute(attr);
      if (raw === null) continue;
      const value = Number.parseInt(raw, 10);
      if (Number.isInteger(value) && value > 1) {
        clean.setAttribute(attr, String(value));
      }
    }
  }
  for (const child of children) {
    clean.appendChild(child);
  }
  return [clean];
};

/**
 * Parse a TABLE chunk's text into a caption plus sanitized table markup.
 *
 * Returns null when the text carries no usable table (the caller then falls
 * back to the pipe-separated parser or the raw text view).
 */
export const sanitizeAidpTableHtml = (raw: string): AidpTableHtml | null => {
  const trimmed = raw.trim();
  const tableStart = trimmed.search(/<table[\s>]/i);
  if (tableStart < 0) return null;
  const caption = trimmed.slice(0, tableStart).trim();

  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(
      trimmed.slice(tableStart),
      "text/html"
    );
  } catch {
    return null;
  }
  const table = doc.querySelector("table");
  // A table without any row is treated as malformed: nothing useful to show.
  if (!table || !table.querySelector("tr")) return null;
  const clean = rebuildElement(table)[0] as HTMLTableElement;
  return { caption, table: clean };
};

/** Quick validity probe used by the editor's preview toggle. */
export const isAidpTableHtmlValid = (raw: string): boolean =>
  sanitizeAidpTableHtml(raw) !== null;
