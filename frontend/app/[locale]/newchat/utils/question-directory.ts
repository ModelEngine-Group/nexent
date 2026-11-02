// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo } from "react";

/** Truncation length for the question summary shown in the directory list. */
const QUESTION_SUMMARY_MAX_LENGTH = 60;

/**
 * Loose shape of an assistant-ui thread message as consumed by the question
 * directory. Only the fields actually read are declared, mirroring the relaxed
 * typing used by `conversation-artifacts.ts` for restored content parts.
 */
export interface QuestionMessageLike {
  id: string;
  role?: string;
  content?: readonly {
    type?: string;
    text?: string;
  }[];
  attachments?: readonly { name?: string }[];
}

/** One user question turn, flattened for the conversation directory. */
export interface QuestionDirectoryEntry {
  /** Stable identity (the user message id; also the jump target). */
  key: string;
  /** assistant-ui message id used to locate the DOM node for scrolling. */
  messageId: string;
  /** 1-based position of the question within the conversation. */
  index: number;
  /** Short single-line label for the list. */
  summary: string;
  /** Full question text (or attachment name) for the hover tooltip. */
  fullText: string;
  /** Whether the turn was derived from text or from an attachment-only message. */
  kind: "text" | "attachment";
}

const truncateSummary = (value: string): string => {
  const line = value.split("\n")[0]?.trim() ?? "";
  if (!line) return "";
  if (line.length <= QUESTION_SUMMARY_MAX_LENGTH) return line;
  return `${line.slice(0, QUESTION_SUMMARY_MAX_LENGTH - 1)}…`;
};

/**
 * Collects one directory entry per user message, in conversation order.
 *
 * Text questions use the first non-empty text part (first line, truncated) as
 * the summary; messages that only carried attachments fall back to the first
 * attachment's name. Messages with neither are skipped.
 */
export function collectQuestionDirectory(
  messages: readonly QuestionMessageLike[]
): QuestionDirectoryEntry[] {
  const entries: QuestionDirectoryEntry[] = [];
  for (const message of messages) {
    if (message.role !== "user") continue;

    const fullText =
      message.content
        ?.find(
          (part) =>
            part?.type === "text" && typeof part.text === "string" && part.text
        )
        ?.text?.trim() ?? "";

    let kind: QuestionDirectoryEntry["kind"];
    let source: string;
    if (fullText) {
      kind = "text";
      source = fullText;
    } else {
      const attachmentName = message.attachments?.find((a) => a?.name)?.name;
      if (!attachmentName) continue;
      kind = "attachment";
      source = attachmentName;
    }

    const summary = truncateSummary(source);
    if (!summary) continue;

    entries.push({
      key: message.id,
      messageId: message.id,
      index: entries.length + 1,
      summary,
      fullText: source,
      kind,
    });
  }
  return entries;
}

/**
 * Memoized wrapper for component consumption. `messages` identity changes on
 * every streamed token, which keeps the directory live during generation.
 */
export function useQuestionDirectory(
  messages: readonly QuestionMessageLike[]
): QuestionDirectoryEntry[] {
  return useMemo(() => collectQuestionDirectory(messages), [messages]);
}

/**
 * Scrolls the thread viewport to the message with the given id.
 *
 * assistant-ui renders `data-message-id` on every message root and exposes no
 * public scroll-to-message API, so the target is located through the DOM and
 * scrolled natively. The target flashes briefly so the landing point is
 * obvious after the smooth scroll settles.
 */
export function scrollThreadToMessage(messageId: string): boolean {
  if (!messageId) return false;
  // Message ids are runtime-generated, but escape quote/backslash anyway so
  // the attribute selector stays valid for any id shape.
  const escaped = messageId.replace(/["\\]/g, "\\$&");
  const element = document.querySelector<HTMLElement>(
    `[data-message-id="${escaped}"]`
  );
  if (!element) return false;

  // Breathing room between the landed message and the viewport top edge.
  element.style.scrollMarginTop = "16px";
  element.scrollIntoView({ behavior: "smooth", block: "start" });

  // Brief highlight so the jump target is visible after scrolling.
  element.style.transition = "box-shadow 0.4s ease-out";
  element.style.boxShadow = "0 0 0 3px rgba(59, 130, 246, 0.45)";
  window.setTimeout(() => {
    element.style.boxShadow = "";
    element.style.transition = "";
  }, 1600);
  return true;
}
