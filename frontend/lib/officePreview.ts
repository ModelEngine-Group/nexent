// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Helpers for previewing a document stream in the browser.
 *
 * Nexent normally converts Office files to PDF on the server. AIDP knowledge
 * bases are different: AIDP serves the original bytes for docx/xlsx/pptx/pdf/txt
 * and a PDF conversion for every other format, so the browser has to resolve the
 * served format from the ``X-File-Name`` header (never from the uploaded name)
 * and has to sanitize the HTML that some formats embed in their XML.
 */

/** Office formats that are a zip archive of XML parts and can be parsed client-side. */
export type OfficeFormat = "docx" | "xlsx" | "pptx";

/**
 * Renderer that handles the bytes a document stream returned.
 *
 * `unsupported` is the last resort: AIDP converts everything it cannot serve
 * itself to PDF, so it only shows up when the stream arrives with a name whose
 * suffix no renderer claims.
 */
export type StreamPreviewKind =
  "pdf" | "docx" | "xlsx" | "pptx" | "text" | "image" | "unsupported";

const OOXML_FORMATS: Readonly<Record<string, OfficeFormat>> = {
  docx: "docx",
  xlsx: "xlsx",
  pptx: "pptx",
};

/**
 * Extensions the preview treats as Office documents.
 *
 * `doc`/`xls`/`ppt` are legacy OLE compound files rather than zip archives, so
 * no browser-side parser can read them. AIDP converts them to PDF, which means
 * the served name no longer ends in one of these suffixes; they only reach a
 * renderer unconverted when another backend serves the original bytes.
 */
const OFFICE_EXTENSIONS = new Set([
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
]);

/**
 * Office MIME types recognised by the file service.
 *
 * The set mirrors what the storage layer reports for the converted PDF path and
 * deliberately excludes ODF types, which that path never converts.
 */
const OFFICE_DOCUMENT_MIME_TYPES = new Set([
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
]);

/** Extensions rendered as plain text when a stream keeps them unconverted. */
const TEXT_EXTENSIONS = new Set([
  "txt",
  "text",
  "log",
  "json",
  "xml",
  "yaml",
  "yml",
  "md",
  "markdown",
  "csv",
  "tsv",
  "ini",
  "conf",
  "sql",
  "srt",
]);

/** Extensions rendered through an `<img>` element. */
const IMAGE_EXTENSIONS = new Set([
  "jpg",
  "jpeg",
  "png",
  "gif",
  "webp",
  "svg",
  "bmp",
  "tif",
  "tiff",
]);

/** Return the lowercase extension of `fileName` without the dot, or an empty string. */
export function getFileExtension(fileName: string): string {
  const lastDot = fileName.lastIndexOf(".");
  // A name that is only an extension (`.pdf`) still identifies the format, while
  // a trailing dot identifies nothing.
  if (lastDot === -1 || lastDot === fileName.length - 1) {
    return "";
  }
  return fileName.slice(lastDot + 1).toLowerCase();
}

/**
 * Decode the served file name the preview route reports in `X-File-Name`.
 *
 * Response header values are latin-1 on the wire while AIDP reports names
 * verbatim (Chinese names included), so the backend URI-encodes the name before
 * it reaches the browser. A value that is not valid percent-encoding (a literal
 * `%` in the name, typically) travelled verbatim and is returned unchanged.
 */
export function decodeServedFileName(
  value: string | null | undefined
): string | undefined {
  const raw = value?.trim();
  if (!raw) {
    return undefined;
  }
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

export function isOfficeExtension(extension: string): boolean {
  return OFFICE_EXTENSIONS.has(extension);
}

export function isOfficeDocumentMime(mime: string): boolean {
  return OFFICE_DOCUMENT_MIME_TYPES.has(mime);
}

/**
 * Resolve which client-side renderer handles a document stream.
 *
 * The served file name wins over every other signal: AIDP reports the name it
 * actually used in ``X-File-Name``, which ends in ``.pdf`` whenever the upload
 * was converted, while the uploaded name and ``file_type`` still describe the
 * format that no longer exists on the wire. Later fallbacks only cover streams
 * that arrive without a usable suffix (a missing header, or a name without a
 * dot).
 */
export function resolveStreamPreviewKind(
  fileName: string,
  fileType?: string,
  mimeType?: string
): StreamPreviewKind {
  const extension = getFileExtension(fileName);
  const hint = (fileType ?? "").trim().toLowerCase();
  const mime = (mimeType ?? "").split(";")[0].trim().toLowerCase();

  const office = OOXML_FORMATS[extension] ?? OOXML_FORMATS[hint];
  if (office) {
    return office;
  }

  if (extension === "pdf" || hint === "pdf" || mime === "application/pdf") {
    return "pdf";
  }
  if (
    IMAGE_EXTENSIONS.has(extension) ||
    IMAGE_EXTENSIONS.has(hint) ||
    mime.startsWith("image/")
  ) {
    return "image";
  }
  if (
    TEXT_EXTENSIONS.has(extension) ||
    TEXT_EXTENSIONS.has(hint) ||
    mime.startsWith("text/")
  ) {
    return "text";
  }
  return "unsupported";
}

/** Elements that may appear in sanitized Office markup. */
const ALLOWED_TAGS = new Set([
  "p",
  "br",
  "span",
  "b",
  "strong",
  "i",
  "em",
  "u",
  "s",
  "sub",
  "sup",
  "div",
  "ul",
  "ol",
  "li",
  "table",
  "thead",
  "tbody",
  "tr",
  "td",
  "th",
]);

/** Elements whose whole subtree is discarded, including their text. */
const DROPPED_TAGS = new Set([
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "link",
  "meta",
  "base",
  "form",
  "input",
  "svg",
  "math",
  "img",
]);

/** Style properties Office formats use for text runs. */
const ALLOWED_STYLE_PROPERTIES = new Set([
  "font-size",
  "font-family",
  "font-weight",
  "font-style",
  "text-decoration",
  "text-decoration-line",
  "text-align",
  "vertical-align",
  "line-height",
  "white-space",
  "color",
  "background-color",
]);

/** Values that would let a document load remote content or escape the sandbox. */
const UNSAFE_STYLE_VALUE_PATTERN = /url\(|expression\(|javascript:|@import|\\/;

function filterStyle(style: string | null): string {
  if (!style) {
    return "";
  }
  return style
    .split(";")
    .map((declaration) => declaration.trim())
    .filter(Boolean)
    .filter((declaration) => {
      const separator = declaration.indexOf(":");
      if (separator <= 0) {
        return false;
      }
      const property = declaration.slice(0, separator).trim().toLowerCase();
      const value = declaration
        .slice(separator + 1)
        .trim()
        .toLowerCase();
      return (
        ALLOWED_STYLE_PROPERTIES.has(property) &&
        !UNSAFE_STYLE_VALUE_PATTERN.test(value)
      );
    })
    .join("; ");
}

function sanitizeChildren(node: Node): Node[] {
  return Array.from(node.childNodes).flatMap(sanitizeNode);
}

function sanitizeNode(node: Node): Node[] {
  if (node.nodeType === Node.TEXT_NODE) {
    return [document.createTextNode(node.nodeValue ?? "")];
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return [];
  }

  const element = node as Element;
  const tag = element.tagName.toLowerCase();
  if (DROPPED_TAGS.has(tag)) {
    return [];
  }

  const children = sanitizeChildren(element);
  // Unknown wrappers (including hyperlinks) are unwrapped so their text still
  // shows, while dropping the attributes that made them interactive.
  if (!ALLOWED_TAGS.has(tag)) {
    return children;
  }

  const clean = document.createElement(tag);
  const style = filterStyle(element.getAttribute("style"));
  if (style) {
    clean.setAttribute("style", style);
  }
  for (const child of children) {
    clean.appendChild(child);
  }
  return [clean];
}

/**
 * Strip anything executable or remote-loading from Office-generated HTML.
 *
 * `pptxtojson` returns slide text as HTML with inline styles, and that markup
 * comes straight from an uploaded document, so it must never reach the DOM
 * unfiltered. Parsing through `DOMParser` does not execute scripts or fetch
 * resources, which makes it safe to inspect the untrusted string.
 */
export function sanitizeOfficeHtml(html: string): string {
  if (!html || typeof document === "undefined") {
    return "";
  }

  const parsed = new DOMParser().parseFromString(html, "text/html");
  const container = document.createElement("div");
  for (const child of sanitizeChildren(parsed.body)) {
    container.appendChild(child);
  }
  return container.innerHTML;
}

/**
 * Convert Office HTML to plain text, keeping paragraph boundaries.
 *
 * Used where positioning or layout support is unavailable and only the wording
 * matters.
 */
export function officeHtmlToText(html: string): string {
  if (!html) {
    return "";
  }
  const withBreaks = html
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|tr|h[1-6])>/gi, "\n");
  if (typeof document === "undefined") {
    return stripMarkup(withBreaks).trim();
  }
  const parsed = new DOMParser().parseFromString(withBreaks, "text/html");
  return (parsed.body.textContent ?? "").trim();
}

/**
 * Drop every tag from a markup string without a DOM.
 *
 * A strict left-to-right scan is used instead of a tag-matching regular
 * expression: a regex has to guess where a tag ends, and an input built out of
 * overlapping angle brackets (``<<script>script>``) then still answers with a
 * tag, which is what makes that shape an incomplete sanitization. The scan
 * simply never emits the two characters that delimit a tag, so the result can
 * only ever be text.
 */
function stripMarkup(markup: string): string {
  let text = "";
  let insideTag = false;
  for (const character of markup) {
    if (character === "<") {
      insideTag = true;
    } else if (character === ">") {
      insideTag = false;
    } else if (!insideTag) {
      text += character;
    }
  }
  return text;
}
