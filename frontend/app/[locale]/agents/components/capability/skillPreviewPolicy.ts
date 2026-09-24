"use client";

/**
 * Tuning knobs for the Skill file code preview.
 *
 * `MAX_HIGHLIGHT_BYTES` bounds the Shiki payload we hand to the renderer.
 * Anything above the threshold is rendered as plain text to avoid blocking
 * the main thread on multi-megabyte skill files.
 *
 * `MAX_HIGHLIGHT_LINE_BREAKS` is a secondary guard: a single pathological
 * line (e.g. a base64 blob) can be expensive even when total bytes look
 * reasonable.
 */
export const MAX_HIGHLIGHT_BYTES = 256 * 1024;
export const MAX_HIGHLIGHT_LINE_BREAKS = 4000;

/**
 * Plain-text fallback delay after the last content change. We skip the
 * highlighter during streaming and switch to plain text immediately, then
 * promote to highlighted output once the stream settles.
 */
export const STREAMING_PLAIN_TEXT_DELAY_MS = 0;

export interface PreviewSizingInput {
  content: string;
  lines?: number;
}

export interface PreviewSizingResult {
  shouldHighlight: boolean;
  reason: "ok" | "too-large" | "too-many-lines" | "empty";
}

/**
 * Decide whether the renderer should run Shiki on the given content.
 *
 * Returning a `reason` lets callers surface a subtle "preview is showing
 * plain text because the file is large" hint without changing the layout.
 */
export function shouldRenderHighlight({
  content,
  lines,
}: PreviewSizingInput): PreviewSizingResult {
  if (!content || content.length === 0) {
    return { shouldHighlight: false, reason: "empty" };
  }
  const byteLength =
    typeof TextEncoder !== "undefined"
      ? new TextEncoder().encode(content).length
      : content.length;
  if (byteLength > MAX_HIGHLIGHT_BYTES) {
    return { shouldHighlight: false, reason: "too-large" };
  }
  if (typeof lines === "number" && lines > MAX_HIGHLIGHT_LINE_BREAKS) {
    return { shouldHighlight: false, reason: "too-many-lines" };
  }
  return { shouldHighlight: true, reason: "ok" };
}
