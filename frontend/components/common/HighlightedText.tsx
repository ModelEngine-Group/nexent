// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { type FC } from "react";

import { escapeRegExp } from "@/lib/citationHighlight";

interface HighlightedTextProps {
  text: string;
  /**
   * Fragment to wrap in `<mark>`. A blank fragment renders the plain text, so
   * rows outside an active search keep their original markup.
   */
  keyword?: string;
}

interface TextSegment {
  value: string;
  matched: boolean;
}

/**
 * Split text at every case-insensitive occurrence of a keyword. Matching keeps
 * the original casing and slicing only uses the original string, so a keyword
 * such as "关键" is highlighted without altering the rendered text.
 *
 * Returns null when the text contains no occurrence, which lets the caller
 * render the plain string as a single node.
 */
function splitByKeyword(text: string, keyword: string): TextSegment[] | null {
  const matcher = new RegExp(escapeRegExp(keyword), "gi");
  const segments: TextSegment[] = [];
  let cursor = 0;

  for (const match of text.matchAll(matcher)) {
    const start = match.index ?? 0;
    if (start > cursor) {
      segments.push({ value: text.slice(cursor, start), matched: false });
    }
    segments.push({ value: match[0], matched: true });
    cursor = start + match[0].length;
  }

  if (segments.length === 0) return null;
  if (cursor < text.length) {
    segments.push({ value: text.slice(cursor), matched: false });
  }
  return segments;
}

/**
 * Render text with the matched fragments of a table search wrapped in
 * `<mark>`, so the user can see both which rows matched and where inside the
 * row they matched.
 */
const HighlightedText: FC<HighlightedTextProps> = ({ text, keyword }) => {
  const needle = (keyword ?? "").trim();
  const segments = needle ? splitByKeyword(text, needle) : null;
  if (!segments) return <>{text}</>;

  return (
    <>
      {segments.map((segment, index) =>
        segment.matched ? (
          <mark
            key={`${index}-${segment.value}`}
            className="rounded-sm bg-yellow-100 px-0.5 text-inherit"
          >
            {segment.value}
          </mark>
        ) : (
          <span key={`${index}-${segment.value}`}>{segment.value}</span>
        )
      )}
    </>
  );
};

export default HighlightedText;
