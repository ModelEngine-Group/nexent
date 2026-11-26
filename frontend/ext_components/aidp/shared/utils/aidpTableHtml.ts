// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Sanitize an AIDP TABLE chunk's HTML for preview/rendering.
 *
 * Real AIDP formats table chunks as "<chapter title>\n\n<table>...</table>"
 * (verified 2026-11-20). The chunk text is derived from user-uploaded
 * documents, so the HTML is never rendered raw: a narrow table-only tokenizer
 * rebuilds it with DOM nodes, dropping every other tag and attribute.
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
const VOID_TAGS = new Set(["col"]);
const SPAN_ATTRS = new Set(["colspan", "rowspan"]);
const TOKEN_PATTERN =
  /<!--[\s\S]*?-->|<\s*\/\s*([a-zA-Z][\w:-]*)\s*>|<\s*([a-zA-Z][\w:-]*)([^>]*?)(\/?)>|[^<]+/g;

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: "\u00a0",
};

const decodeEntities = (text: string): string =>
  text.replace(
    /&(#x?[0-9a-f]+|amp|lt|gt|quot|apos|nbsp);/gi,
    (match, entity: string) => {
      const key = entity.toLowerCase();
      if (key.startsWith("#x")) {
        const code = Number.parseInt(key.slice(2), 16);
        return Number.isFinite(code) ? String.fromCodePoint(code) : match;
      }
      if (key.startsWith("#")) {
        const code = Number.parseInt(key.slice(1), 10);
        return Number.isFinite(code) ? String.fromCodePoint(code) : match;
      }
      return NAMED_ENTITIES[key] ?? match;
    }
  );

const applySpanAttrs = (element: Element, attrs: string) => {
  for (const attr of SPAN_ATTRS) {
    const match = new RegExp(`${attr}\\s*=\\s*["']?(\\d+)`, "i").exec(attrs);
    if (!match) continue;
    const value = Number.parseInt(match[1], 10);
    if (Number.isInteger(value) && value > 1) {
      element.setAttribute(attr, String(value));
    }
  }
};

const currentParent = (
  stack: Array<{ tag: string; element: Element | null }>
): Element | null => {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    if (stack[index].element) return stack[index].element;
  }
  return null;
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

  const rest = trimmed.slice(tableStart);
  const open = /<table\b[^>]*>/i.exec(rest);
  if (!open) return null;
  const bodyStart = open.index + open[0].length;
  const bodyEnd = rest.toLowerCase().lastIndexOf("</table>");
  if (bodyEnd < bodyStart) return null;

  const table = document.createElement("table");
  const stack: Array<{ tag: string; element: Element | null }> = [
    { tag: "table", element: table },
  ];

  for (const match of rest.slice(bodyStart, bodyEnd).matchAll(TOKEN_PATTERN)) {
    const [token, closingTag, openingTag, attrs, selfClosing] = match;
    if (token.startsWith("<!--")) continue;

    if (closingTag) {
      const tag = closingTag.toLowerCase();
      for (let index = stack.length - 1; index > 0; index -= 1) {
        if (stack[index].tag !== tag) continue;
        stack.length = index;
        break;
      }
      continue;
    }

    if (openingTag) {
      const tag = openingTag.toLowerCase();
      const allowed = ALLOWED_TAGS.has(tag);
      if (allowed) {
        const element = document.createElement(tag);
        if (tag === "td" || tag === "th") applySpanAttrs(element, attrs);
        currentParent(stack)?.appendChild(element);
        if (!VOID_TAGS.has(tag) && !selfClosing) {
          stack.push({ tag, element });
        }
      } else if (!VOID_TAGS.has(tag) && !selfClosing) {
        // Unknown wrappers are transparent: keep their sanitized children.
        stack.push({ tag, element: null });
      }
      continue;
    }

    const parent = currentParent(stack);
    if (parent) parent.appendChild(document.createTextNode(decodeEntities(token)));
  }

  const clean = table;
  // A table without any row is treated as malformed: nothing useful to show.
  if (!clean.querySelector("tr")) return null;
  return { caption, table: clean };
};

/** Quick validity probe used by the editor's preview toggle. */
export const isAidpTableHtmlValid = (raw: string): boolean =>
  sanitizeAidpTableHtml(raw) !== null;
