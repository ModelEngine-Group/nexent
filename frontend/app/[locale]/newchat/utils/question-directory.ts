// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useState } from "react";

/** Truncation length for the question summary shown in the directory list. */
const QUESTION_SUMMARY_MAX_LENGTH = 60;

/** Truncation length for the assistant reply excerpt shown in the preview. */
const REPLY_EXCERPT_MAX_CHARS = 400;

/** Viewport fraction used as the "current question" midline. */
const ACTIVE_QUESTION_MIDLINE = 0.5;

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
  /** Full question text (or attachment name) for the preview card. */
  fullText: string;
  /** Excerpt of the assistant reply that answered the question ("" if none yet). */
  replyText: string;
  /** Whether the turn was derived from text or from an attachment-only message. */
  kind: "text" | "attachment";
}

const truncateSummary = (value: string): string => {
  const line = value.split("\n")[0]?.trim() ?? "";
  if (!line) return "";
  if (line.length <= QUESTION_SUMMARY_MAX_LENGTH) return line;
  return `${line.slice(0, QUESTION_SUMMARY_MAX_LENGTH - 1)}…`;
};

const truncateReply = (value: string): string => {
  const trimmed = value.trim();
  if (trimmed.length <= REPLY_EXCERPT_MAX_CHARS) return trimmed;
  return `${trimmed.slice(0, REPLY_EXCERPT_MAX_CHARS - 1)}…`;
};

/** Joins the text parts of a message (assistant replies only). */
const messageText = (message: QuestionMessageLike): string =>
  (message.content ?? [])
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => (part.type === "text" ? (part.text ?? "") : ""))
    .join("\n")
    .trim();

/**
 * Collects one directory entry per user message, in conversation order.
 *
 * Text questions use the first non-empty text part (first line, truncated) as
 * the summary; messages that only carried attachments fall back to the first
 * attachment's name. Messages with neither are skipped. Each entry also
 * carries an excerpt of the first assistant reply that follows it so the
 * directory can preview the answer together with the question.
 */
export function collectQuestionDirectory(
  messages: readonly QuestionMessageLike[],
): QuestionDirectoryEntry[] {
  const entries: QuestionDirectoryEntry[] = [];
  // Index of the newest question that has not received an assistant reply yet;
  // assistant messages without text (tool calls, reasoning summaries) do not
  // consume it so the first textual reply wins.
  let pendingIndex = -1;
  for (const message of messages) {
    if (message.role === "user") {
      const fullText =
        message.content
          ?.find(
            (part) =>
              part?.type === "text" &&
              typeof part.text === "string" &&
              part.text,
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
        replyText: "",
        kind,
      });
      pendingIndex = entries.length - 1;
      continue;
    }

    if (message.role === "assistant" && pendingIndex >= 0) {
      const pending = entries[pendingIndex];
      const reply = messageText(message);
      if (pending && reply) {
        pending.replyText = truncateReply(reply);
        pendingIndex = -1;
      }
    }
  }
  return entries;
}

/**
 * Memoized wrapper for component consumption. `messages` identity changes on
 * every streamed token, which keeps the directory live during generation.
 */
export function useQuestionDirectory(
  messages: readonly QuestionMessageLike[],
): QuestionDirectoryEntry[] {
  return useMemo(() => collectQuestionDirectory(messages), [messages]);
}

/**
 * Locates the rendered message element for an assistant-ui message id.
 *
 * assistant-ui renders `data-message-id` on every message root and exposes no
 * public message-lookup API, so the target is located through the DOM. Message
 * ids are runtime-generated, but quote/backslash are escaped anyway so the
 * attribute selector stays valid for any id shape.
 */
export function findMessageElement(messageId: string): HTMLElement | null {
  const escaped = messageId.replace(/["\\]/g, "\\$&");
  return document.querySelector<HTMLElement>(`[data-message-id="${escaped}"]`);
}

/**
 * Scrolls the thread viewport to the message with the given id.
 *
 * The target is located through the DOM and scrolled natively without adding
 * a visual highlight to the message.
 */
export function scrollThreadToMessage(messageId: string): boolean {
  const element = findMessageElement(messageId);
  if (!element) return false;

  // Breathing room between the landed message and the viewport top edge.
  element.style.scrollMarginTop = "16px";
  element.scrollIntoView({ behavior: "smooth", block: "start" });

  return true;
}

/**
 * Tracks the question the thread viewport is currently scrolled to.
 *
 * The active question is the last one whose message top sits above the
 * viewport midline (classic active-section logic), recomputed rAF-throttled on
 * every scroll and once whenever the tracked question set changes. Scroll
 * events do not bubble, so the listener attaches to `window` in the capture
 * phase to also catch inner scroll containers.
 */
export function useActiveQuestionId(
  questions: readonly QuestionDirectoryEntry[],
): string | null {
  const [activeId, setActiveId] = useState<string | null>(null);
  // Stable dependency: entry identities change on every streamed token, but
  // the tracked id list only changes when questions are added or removed.
  const questionIdsKey = questions
    .map((question) => question.messageId)
    .join("\n");

  useEffect(() => {
    const ids = questionIdsKey ? questionIdsKey.split("\n") : [];
    let frame = 0;
    const compute = () => {
      frame = 0;
      const midline = window.innerHeight * ACTIVE_QUESTION_MIDLINE;
      let current: string | null = null;
      for (const id of ids) {
        const element = findMessageElement(id);
        // Unmounted messages (still loading, filtered runs) are skipped; the
        // first rendered message below the midline ends the scan.
        if (!element) continue;
        if (element.getBoundingClientRect().top <= midline) {
          current = id;
        } else {
          break;
        }
      }
      setActiveId(current);
    };

    const scheduleCompute = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(compute);
    };

    // The initial computation rides the same rAF path as scroll-driven ones;
    // an empty question set resolves to null on the next frame.
    scheduleCompute();
    window.addEventListener("scroll", scheduleCompute, true);
    return () => {
      window.removeEventListener("scroll", scheduleCompute, true);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [questionIdsKey]);

  return activeId;
}
