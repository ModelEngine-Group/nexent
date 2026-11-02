// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo } from "react";

/** DOM hooks used to scope a quotable selection to one assistant message. */
const ASSISTANT_MESSAGE_SELECTOR = "[data-role='assistant'][data-message-id]";
const MESSAGE_CONTENT_SELECTOR = "[data-slot='aui_assistant-message-content']";
// Reasoning, tool calls, execution-code summaries and subagent cards render
// outside the quotable reply text.
const NON_QUOTABLE_SELECTOR =
  "[data-slot='aui_chain-of-thought'], .aui-tool-group-root";

/** Default excerpt length for the annotation source label. */
const SOURCE_EXCERPT_MAX_LENGTH = 40;

/** Default truncation length for quoted text shown inside the chip list. */
const LIST_QUOTE_MAX_LENGTH = 80;

/**
 * Loose shape of an assistant-ui thread message as consumed by the
 * annotation helpers. Only the fields actually read are declared, mirroring
 * the relaxed typing used by `question-directory.ts`.
 */
export interface AnnotationMessageLike {
  id: string;
  role?: string;
  content?: readonly {
    type?: string;
    text?: string;
  }[];
}

/** A pending selection inside one assistant message, resolved from the DOM. */
export interface AnnotationSelectionTarget {
  /** assistant-ui message id of the message the selection belongs to. */
  messageId: string;
  /** Normalized selected text (CRLF collapsed to LF). */
  text: string;
  /** Cloned DOM range used to anchor the floating bubble. */
  range: Range;
}

/** Draft annotation captured from a completed selection. */
export interface MessageAnnotationDraft {
  /** The selected text quoted verbatim from the assistant reply. */
  quotedText: string;
  /** Optional user comment attached to the quote. */
  comment?: string;
  /** assistant-ui message id of the message the quote came from. */
  sourceMessageId: string;
}

/** A stored annotation attached to the next outgoing message. */
export interface MessageAnnotation extends MessageAnnotationDraft {
  /** Runtime identity used for list keys and edit/delete actions. */
  id: string;
  /** Short excerpt of the source reply, shown in the list and the outgoing text. */
  sourceExcerpt: string;
}

/** Aggregate handle passed from the Thread down to the composer and bubble. */
export interface MessageAnnotationsControl {
  /** Pending annotations in creation order. */
  annotations: readonly MessageAnnotation[];
  /** Stores a new annotation captured from a selection. */
  addAnnotation: (draft: MessageAnnotationDraft) => void;
  /** Saves an edited comment. */
  updateAnnotationComment: (id: string, comment: string) => void;
  /** Deletes a single annotation. */
  removeAnnotation: (id: string) => void;
  /** Deletes every pending annotation. */
  clearAnnotations: () => void;
  /** Consumes the annotations once the outgoing run has accepted them. */
  consumeAnnotations: () => void;
}

/** Localized labels used when folding annotations into the outgoing text. */
export interface AnnotationMessageLabels {
  /** "Quote" label opening each annotation header. */
  quoteLabel: string;
  /** Source template containing the `{{excerpt}}` placeholder. */
  sourceLabel: string;
  /** Label prefixing the user comment line. */
  commentLabel: string;
  /** Header terminator (full-width in Chinese, ": " in English). */
  colon: string;
}

/**
 * Collapses whitespace and truncates to a single-line excerpt.
 *
 * @param value Raw text to summarize.
 * @param maxLength Maximum character count including the ellipsis.
 * @returns The truncated single-line summary.
 */
export function truncateAnnotationText(
  value: string,
  maxLength: number
): string {
  const line = value.replace(/\s+/g, " ").trim();
  if (!line) return "";
  if (line.length <= maxLength) return line;
  return `${line.slice(0, maxLength - 1)}…`;
}

/**
 * Resolves the live selection into a quotable target.
 *
 * A selection is quotable when both endpoints sit inside the content area of
 * the same assistant message and outside reasoning, tool, execution-code and
 * subagent containers. Selections crossing messages, user messages and
 * collapsed selections are rejected.
 *
 * @param selection The live window selection.
 * @returns The target, or null when the selection is not quotable.
 */
export function resolveAnnotationSelection(
  selection: Selection | null
): AnnotationSelectionTarget | null {
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }
  const text = selection.toString();
  if (!text || !text.trim()) return null;
  const anchorElement = elementFromNode(selection.anchorNode);
  const focusElement = elementFromNode(selection.focusNode);
  if (!anchorElement || !focusElement) return null;

  const messageElement = anchorElement.closest(ASSISTANT_MESSAGE_SELECTOR);
  if (!messageElement) return null;
  // Both endpoints must belong to the same assistant message; this also
  // rejects selections that start in chrome outside the message list.
  if (
    messageElement !== focusElement.closest(ASSISTANT_MESSAGE_SELECTOR) ||
    anchorElement.closest(MESSAGE_CONTENT_SELECTOR) !==
      focusElement.closest(MESSAGE_CONTENT_SELECTOR)
  ) {
    return null;
  }
  if (
    anchorElement.closest(NON_QUOTABLE_SELECTOR) ||
    focusElement.closest(NON_QUOTABLE_SELECTOR)
  ) {
    return null;
  }

  const messageId = messageElement.getAttribute("data-message-id") ?? "";
  if (!messageId) return null;

  return {
    messageId,
    text: text.replace(/\r\n/g, "\n"),
    range: selection.getRangeAt(0).cloneRange(),
  };
}

function elementFromNode(node: Node | null): HTMLElement | null {
  if (!node) return null;
  if (node.nodeType === Node.TEXT_NODE) return node.parentElement;
  return node.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : null;
}

/**
 * Extracts a short excerpt of the assistant message an annotation quotes.
 *
 * @param messages Thread messages in conversation order.
 * @param messageId assistant-ui message id of the source message.
 * @param maxLength Maximum excerpt length including the ellipsis.
 * @returns The truncated first line of the reply, or "" for unknown sources.
 */
export function getAnnotationSourceExcerpt(
  messages: readonly AnnotationMessageLike[],
  messageId: string,
  maxLength = SOURCE_EXCERPT_MAX_LENGTH
): string {
  const message = messages.find((item) => item.id === messageId);
  if (!message || message.role !== "assistant") return "";
  const text = (message.content ?? [])
    .map((part) => (part.type === "text" ? (part.text ?? "") : ""))
    .join("")
    .trim();
  return truncateAnnotationText(text, maxLength);
}

/**
 * Builds a stored annotation from a draft.
 *
 * The comment is trimmed; a whitespace-only comment is dropped. The source
 * excerpt is captured at creation time so the annotation keeps referencing
 * the reply content the user saw when selecting.
 *
 * @param draft Draft captured from the selection bubble.
 * @param messages Thread messages used to resolve the source excerpt.
 * @param id Runtime identity for the stored annotation.
 * @returns The fully populated annotation.
 */
export function createMessageAnnotation(
  draft: MessageAnnotationDraft,
  messages: readonly AnnotationMessageLike[],
  id: string
): MessageAnnotation {
  return {
    id,
    ...draft,
    comment: draft.comment?.trim() || undefined,
    sourceExcerpt: getAnnotationSourceExcerpt(messages, draft.sourceMessageId),
  };
}

function renderSourceLabel(template: string, excerpt: string): string {
  return template.replace(/\{\{excerpt\}\}/g, excerpt);
}

/**
 * Folds pending annotations into the outgoing message text.
 *
 * Each annotation becomes a numbered quote block; the user's own text follows
 * behind a `---` separator so the model receives both the quoted reply
 * excerpts (with the user's comments) and the follow-up question in one
 * message. With no annotations the text is returned unchanged.
 *
 * @param text The user-typed composer text (may be empty).
 * @param annotations Pending annotations in creation order.
 * @param labels Localized labels for the composed blocks.
 * @returns The composed outgoing message text.
 */
export function formatAnnotationsIntoMessage(
  text: string,
  annotations: readonly MessageAnnotation[],
  labels: AnnotationMessageLabels
): string {
  if (annotations.length === 0) return text;

  const blocks = annotations.map((annotation, index) => {
    const source = annotation.sourceExcerpt
      ? renderSourceLabel(labels.sourceLabel, annotation.sourceExcerpt)
      : "";
    const lines = [
      // trimEnd drops the trailing blank of the English ": " colon.
      `${index + 1}. ${labels.quoteLabel}${source}${labels.colon}`.trimEnd(),
    ];
    for (const line of annotation.quotedText.split("\n")) {
      lines.push(`> ${line}`);
    }
    if (annotation.comment) {
      lines.push(`${labels.commentLabel}${labels.colon}${annotation.comment}`);
    }
    return lines.join("\n");
  });

  const quoteBlock = blocks.join("\n\n");
  return text ? `${quoteBlock}\n\n---\n\n${text}` : quoteBlock;
}

/**
 * Memoized helper for the chip list: shortens quoted text for display.
 *
 * @param annotation The annotation whose quote should be summarized.
 * @returns A single-line truncated quote.
 */
export function useAnnotationQuotePreview(
  annotation: MessageAnnotation
): string {
  return useMemo(
    () => truncateAnnotationText(annotation.quotedText, LIST_QUOTE_MAX_LENGTH),
    [annotation.quotedText]
  );
}
