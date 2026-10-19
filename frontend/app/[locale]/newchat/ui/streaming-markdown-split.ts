// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Streaming markdown splitter used by the reasoning display.
 *
 * While a reasoning part streams in token by token, re-rendering the full
 * accumulated text through a single markdown parser on every chunk costs
 * O(text length x chunk count): at a measured ~4ms per KB per parse, one
 * 40KB reasoning block alone burns ~30s of main-thread parsing and freezes
 * the page. Sealing completed prefix segments at safe boundaries lets each
 * memoized segment parse exactly once, so per-chunk work is bounded by the
 * active tail instead of the full text.
 *
 * Boundary preference, safest first:
 *   1. Blank line outside a fenced code block (paragraph-level boundary),
 *      once the accumulated length reaches `minSegmentLength`.
 *   2. Any line break once the tail would exceed `maxTailLength`, preferring
 *      breaks outside fenced code blocks. In-fence breaks are used as a last
 *      resort so the re-parsed tail stays bounded for long fenced blocks.
 *   3. Whitespace inside a line, for stretches longer than `maxTailLength`
 *      with no usable line break.
 *
 * Tier 2/3 splits can change transient rendering (for example a paragraph
 * or code block split across segments); this is acceptable because the
 * completed state re-renders the full text once through
 * MarkdownTextPrimitive.
 *
 * Append-stability: for text that only grows, previously sealed segments
 * (all but the last) stay byte-identical across calls, because every split
 * decision depends only on content before the split point. This is the
 * property that keeps memoized segments from re-parsing. Transitions that
 * change line structure (for example the first line break arriving in a
 * previously break-free stretch) can re-seal once; that costs a single
 * re-parse, not sustained quadratic work.
 */

export interface StreamingMarkdownSplitOptions {
  /** Minimum accumulated length before a blank-line boundary seals a segment. */
  minSegmentLength?: number;
  /**
   * Tail length that triggers sealing at lower-tier boundaries when no blank
   * line is available. Caps the worst-case per-chunk re-parse cost. May be
   * below `minSegmentLength`; emergency seals are then allowed to be smaller
   * than the normal minimum.
   */
  maxTailLength?: number;
}

interface LineBoundary {
  /** Offset in `text` where the next segment starts (after this boundary). */
  index: number;
  /** True for blank-line boundaries (the safest split points). */
  isBlank: boolean;
  /** True while inside, or immediately after opening, a fenced code block. */
  inFence: boolean;
}

const DEFAULT_MIN_SEGMENT_LENGTH = 400;
const DEFAULT_MAX_TAIL_LENGTH = 4000;

const FENCE_OPEN_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const FENCE_CLOSE_RE = /^ {0,3}(`{3,}|~{3,})[ \t\r]*$/;

/**
 * Collects one boundary per line break. A boundary marks the offset right
 * after a complete line (including its "\n"), which is always a safe point
 * to start the next segment.
 */
function collectLineBoundaries(text: string): LineBoundary[] {
  const boundaries: LineBoundary[] = [];
  let fenceChar: "`" | "~" | null = null;
  let fenceLength = 0;
  let lineStart = 0;
  for (let i = 0; i <= text.length; i += 1) {
    if (i < text.length && text.charCodeAt(i) !== 10 /* \n */) continue;
    const line = text.slice(lineStart, i);
    let inFence: boolean;
    if (fenceChar) {
      const close = line.match(FENCE_CLOSE_RE);
      if (
        close &&
        close[1][0] === fenceChar &&
        close[1].length >= fenceLength
      ) {
        fenceChar = null;
        inFence = false; // Splitting right after a closing fence is safe.
      } else {
        inFence = true;
      }
    } else {
      const open = line.match(FENCE_OPEN_RE);
      if (open && !(open[1][0] === "`" && open[2].includes("`"))) {
        // Backtick fences must not repeat backticks in the info string.
        fenceChar = open[1][0] as "`" | "~";
        fenceLength = open[1].length;
        inFence = true; // Splitting right after an opening fence is unsafe.
      } else {
        inFence = false;
      }
    }
    if (i < text.length) {
      boundaries.push({
        index: i + 1,
        isBlank: line.trim() === "",
        inFence,
      });
    }
    lineStart = i + 1;
  }
  return boundaries;
}

/** Returns the offset just after the last whitespace in `window`, or 0. */
function lastWhitespaceEnd(window: string): number {
  for (let i = window.length - 1; i >= 0; i -= 1) {
    if (window.charCodeAt(i) <= 32) return i + 1;
  }
  return 0;
}

/**
 * Splits streaming markdown into stable sealed segments plus an active tail.
 * The returned array always concatenates back to the exact input text, and
 * the last element is the only segment expected to keep changing while the
 * text grows.
 */
export function splitStreamingMarkdown(
  text: string,
  options: StreamingMarkdownSplitOptions = {}
): string[] {
  if (text.length === 0) return [];
  const minSegment = Math.max(
    1,
    options.minSegmentLength ?? DEFAULT_MIN_SEGMENT_LENGTH
  );
  const maxTail = Math.max(1, options.maxTailLength ?? DEFAULT_MAX_TAIL_LENGTH);

  const segments: string[] = [];
  const boundaries = collectLineBoundaries(text);
  let start = 0;
  let safeBoundary: LineBoundary | null = null;

  for (const boundary of boundaries) {
    if (!boundary.inFence) safeBoundary = boundary;
    const accumulated = boundary.index - start;
    const sealableBlank =
      boundary.isBlank && !boundary.inFence && accumulated >= minSegment;
    if (sealableBlank || accumulated >= maxTail) {
      const cut = sealableBlank ? boundary : (safeBoundary ?? boundary);
      if (cut.index > start) {
        segments.push(text.slice(start, cut.index));
        start = cut.index;
        safeBoundary = null;
      }
    }
  }

  let tail = text.slice(start);
  // Bound tails that keep growing without a sealable line break (for example
  // a long line followed by more text with no blank line). Cut offsets only
  // depend on the already-streamed prefix, so they stay stable while the
  // tail keeps growing.
  while (tail.length > maxTail) {
    const window = tail.slice(0, maxTail);
    let cut = window.lastIndexOf("\n") + 1;
    if (cut <= 0) cut = lastWhitespaceEnd(window);
    if (cut <= 0) break; // No split point at all: keep legacy single-segment cost.
    segments.push(tail.slice(0, cut));
    tail = tail.slice(cut);
  }

  segments.push(tail);
  return segments;
}
