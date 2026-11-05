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

/** Defensive caps mirrored by the backend (see backend/contracts/annotations.py). */
export const MESSAGE_ANNOTATION_QUOTED_TEXT_MAX = 1500;
export const MESSAGE_ANNOTATION_COMMENT_MAX = 500;
export const MESSAGE_ANNOTATION_MAX_COUNT = 10;
export const MESSAGE_ANNOTATION_CONTEXT_MAX = 200;

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
  contextBefore?: string;
  contextAfter?: string;
  /** assistant-ui message id of the message the selection belongs to. */
  messageId: string;
  /** Normalized selected text (CRLF collapsed to LF). */
  text: string;
  /** Cloned DOM range used to anchor the floating bubble. */
  range: Range;
}

/** Draft annotation captured from a completed selection. */
export interface MessageAnnotationDraft {
  contextBefore?: string;
  contextAfter?: string;
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
  /** Display-only source label; nearby context is sent to the model instead. */
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

/**
 * Wire shape of one persisted reply annotation (snake_case, matching
 * `backend/contracts/annotations.py::MessageAnnotationItem`).
 */
export interface MessageAnnotationWireItem {
  context_before?: string | null;
  context_after?: string | null;
  quoted_text: string;
  comment?: string | null;
  source_excerpt?: string | null;
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

  const content = anchorElement.closest(MESSAGE_CONTENT_SELECTOR);
  const range = selection.getRangeAt(0).cloneRange();
  if (
    !content ||
    !content.contains(range.startContainer) ||
    !content.contains(range.endContainer)
  ) {
    return null;
  }
  // Endpoints alone cannot detect a selection spanning a tool/reasoning card.
  if (
    Array.from(content.querySelectorAll(NON_QUOTABLE_SELECTOR)).some((node) =>
      range.intersectsNode(node)
    )
  ) {
    return null;
  }

  return {
    messageId,
    text: text.replace(/\r\n/g, "\n"),
    range,
    ...captureAnnotationContext(content, range),
  };
}

/** Capture positional snapshots, preferring the endpoint paragraphs. */
function captureAnnotationContext(content: Element, range: Range) {
  const readSide = (before: boolean, paragraphOnly: boolean): string => {
    const node = before ? range.startContainer : range.endContainer;
    const paragraph = elementFromNode(node)?.closest(
      "p, li, pre, blockquote, td, th"
    );
    const root = paragraphOnly ? paragraph : content;
    if (!root || !content.contains(root)) return "";
    const nearby = document.createRange();
    nearby.selectNodeContents(root);
    if (before) nearby.setEnd(range.startContainer, range.startOffset);
    else nearby.setStart(range.endContainer, range.endOffset);
    const fragment = nearby.cloneContents();
    fragment
      .querySelectorAll(NON_QUOTABLE_SELECTOR)
      .forEach((node) => node.remove());
    fragment
      .querySelectorAll("p, li, pre, blockquote, tr, h1, h2, h3, h4, h5, h6")
      .forEach((node) => node.append(document.createTextNode("\n\n")));
    const text = (fragment.textContent ?? "").replace(/\r\n/g, "\n").trim();
    return before
      ? text.slice(-MESSAGE_ANNOTATION_CONTEXT_MAX)
      : text.slice(0, MESSAGE_ANNOTATION_CONTEXT_MAX);
  };
  const contextBefore = readSide(true, true) || readSide(true, false);
  const contextAfter = readSide(false, true) || readSide(false, false);
  return {
    ...(contextBefore ? { contextBefore } : {}),
    ...(contextAfter ? { contextAfter } : {}),
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
    ...(draft.contextBefore
      ? {
          contextBefore: draft.contextBefore.slice(
            -MESSAGE_ANNOTATION_CONTEXT_MAX
          ),
        }
      : {}),
    ...(draft.contextAfter
      ? {
          contextAfter: draft.contextAfter.slice(
            0,
            MESSAGE_ANNOTATION_CONTEXT_MAX
          ),
        }
      : {}),
    // Defensive caps keep the structured payload inside the backend limits.
    quotedText: draft.quotedText.slice(0, MESSAGE_ANNOTATION_QUOTED_TEXT_MAX),
    comment:
      draft.comment?.trim().slice(0, MESSAGE_ANNOTATION_COMMENT_MAX) ||
      undefined,
    sourceExcerpt: getAnnotationSourceExcerpt(messages, draft.sourceMessageId),
  };
}

/**
 * Maps pending annotations onto the structured wire payload sent with the
 * outgoing request (the backend persists it and merges it into the
 * model-facing text at request time).
 *
 * @param annotations Pending annotations in creation order.
 * @returns The snake_case wire items (length-capped by the caller).
 */
export function toMessageAnnotationWireItems(
  annotations: readonly MessageAnnotation[]
): MessageAnnotationWireItem[] {
  return annotations
    .slice(0, MESSAGE_ANNOTATION_MAX_COUNT)
    .map((annotation) => ({
      quoted_text: annotation.quotedText.slice(
        0,
        MESSAGE_ANNOTATION_QUOTED_TEXT_MAX
      ),
      comment:
        annotation.comment?.slice(0, MESSAGE_ANNOTATION_COMMENT_MAX) ?? null,
      source_excerpt: annotation.sourceExcerpt || null,
      ...(annotation.contextBefore
        ? {
            context_before: annotation.contextBefore.slice(
              -MESSAGE_ANNOTATION_CONTEXT_MAX
            ),
          }
        : {}),
      ...(annotation.contextAfter
        ? {
            context_after: annotation.contextAfter.slice(
              0,
              MESSAGE_ANNOTATION_CONTEXT_MAX
            ),
          }
        : {}),
    }));
}

/**
 * Normalizes annotation payloads read back from persisted messages.
 *
 * Invalid entries are dropped and the defensive caps are re-applied so the
 * user bubble renders sane cards even for legacy or oversized payloads.
 *
 * @param raw Value of the message's `annotations` field.
 * @returns Validated wire items; empty when nothing usable remains.
 */
export function fromMessageAnnotationWireItems(
  raw: unknown
): MessageAnnotationWireItem[] {
  if (!Array.isArray(raw)) return [];
  const items: MessageAnnotationWireItem[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) continue;
    const record = entry as Record<string, unknown>;
    const quotedText =
      typeof record.quoted_text === "string" ? record.quoted_text.trim() : "";
    if (!quotedText) continue;
    const comment =
      typeof record.comment === "string" ? record.comment.trim() : "";
    const sourceExcerpt =
      typeof record.source_excerpt === "string"
        ? record.source_excerpt.trim()
        : "";
    items.push({
      quoted_text: quotedText.slice(0, MESSAGE_ANNOTATION_QUOTED_TEXT_MAX),
      comment: comment
        ? comment.slice(0, MESSAGE_ANNOTATION_COMMENT_MAX)
        : null,
      source_excerpt: sourceExcerpt
        ? sourceExcerpt.slice(0, MESSAGE_ANNOTATION_QUOTED_TEXT_MAX)
        : null,
      ...(typeof record.context_before === "string" &&
      record.context_before.trim()
        ? {
            context_before: record.context_before
              .trim()
              .slice(-MESSAGE_ANNOTATION_CONTEXT_MAX),
          }
        : {}),
      ...(typeof record.context_after === "string" &&
      record.context_after.trim()
        ? {
            context_after: record.context_after
              .trim()
              .slice(0, MESSAGE_ANNOTATION_CONTEXT_MAX),
          }
        : {}),
    });
    if (items.length >= MESSAGE_ANNOTATION_MAX_COUNT) break;
  }
  return items;
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
