"use client";

import { type FC } from "react";
import { cn } from "@/lib/utils";
import {
  escapeRegExp,
  normalizeForHighlight,
  splitSourceTextIntoSentences,
} from "@/lib/citationHighlight";

/**
 * Blue index badge shared by citation markers, hover cards, and source cards.
 * Hidden when the index is not a finite number.
 */
export const CiteIndexBadge: FC<{ index?: number; className?: string }> = ({
  index,
  className,
}) => {
  if (!Number.isFinite(index)) return null;
  return (
    <span
      className={cn(
        "rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600",
        className,
      )}
    >
      {index}
    </span>
  );
};

/**
 * Render a source chunk, wrapping sentences that match any highlight term in
 * <mark>. One compiled matcher scans each displayed sentence once. This stays
 * local to the selected card and does not issue an extra search or model
 * request.
 */
export const HighlightedChunkText: FC<{
  text: string;
  terms: string[];
}> = ({ text, terms }) => {
  if (!terms.length) return <>{text}</>;

  const matcher = new RegExp(
    terms.map((term) => escapeRegExp(normalizeForHighlight(term))).join("|"),
    "i",
  );
  return (
    <>
      {splitSourceTextIntoSentences(text).map((part, index) => {
        const isMatch = matcher.test(normalizeForHighlight(part));
        matcher.lastIndex = 0;
        return isMatch ? (
          <mark
            key={`${part}-${index}`}
            className="rounded-sm bg-yellow-100 px-1 py-0.5 text-inherit"
          >
            {part}
          </mark>
        ) : (
          <span key={`${part}-${index}`}>{part}</span>
        );
      })}
    </>
  );
};
