// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FC,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { CheckIcon, MessageSquareQuote, XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  resolveAnnotationSelection,
  type AnnotationSelectionTarget,
  type MessageAnnotationDraft,
} from "../utils/message-annotations";

/** Estimated pill height, used to place the bubble above the selection. */
const PILL_HEIGHT = 36;
/** Estimated composing box height. */
const COMPOSING_HEIGHT = 44;
/** Gap between the selection edge and the bubble. */
const BUBBLE_GAP = 8;
/** Viewport margin the bubble never crosses. */
const VIEWPORT_MARGIN = 8;
/** Composing box width. */
const COMPOSING_WIDTH = 320;

type BubblePhase =
  | { kind: "hidden" }
  | { kind: "selection"; target: AnnotationSelectionTarget }
  | { kind: "composing"; target: AnnotationSelectionTarget; comment: string };

/**
 * Floating "Add to chat" bubble for selected assistant reply text.
 *
 * Listens to the document selection while mounted. Selecting text inside one
 * assistant reply shows a pill above the selection; clicking it freezes the
 * quote and opens an optional-comment input. Confirming reports the draft to
 * the caller; cancelling (Escape or an outside click) discards it. The bubble
 * tracks the selection and any scroll so it stays anchored to the quoted
 * reply; a detached range (the reply re-rendered while streaming) keeps the
 * last known position.
 */
export const MessageAnnotationBubble: FC<{
  /** Whether quotable selections are currently accepted. */
  enabled: boolean;
  /** Called with the quote captured from the finished selection. */
  onAdd: (draft: MessageAnnotationDraft) => void;
}> = ({ enabled, onAdd }) => {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<BubblePhase>({ kind: "hidden" });
  // Selection anchor in viewport coordinates; maintained by the selection
  // and scroll listeners so rendering never touches refs.
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  // Mirrors the current phase for the document selection listener.
  const phaseRef = useRef<BubblePhase>({ kind: "hidden" });
  const boxRef = useRef<HTMLDivElement | null>(null);
  const commentInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // Track the live selection while the bubble is in the selection phase.
  useEffect(() => {
    if (!enabled) return;
    const handleSelectionChange = () => {
      if (phaseRef.current.kind === "composing") return;
      const target = resolveAnnotationSelection(window.getSelection());
      setPhase(target ? { kind: "selection", target } : { kind: "hidden" });
      if (target) {
        const rect = target.range.getBoundingClientRect();
        if (rect.width !== 0 || rect.height !== 0) setAnchorRect(rect);
      } else {
        setAnchorRect(null);
      }
    };
    document.addEventListener("selectionchange", handleSelectionChange);
    return () =>
      document.removeEventListener("selectionchange", handleSelectionChange);
  }, [enabled]);

  // Reposition on any scroll while a bubble is shown; a detached range keeps
  // the last known anchor.
  const activeTarget = phase.kind === "hidden" ? null : phase.target;
  useEffect(() => {
    if (!activeTarget) return;
    const reposition = () => {
      const rect = activeTarget.range.getBoundingClientRect();
      if (rect.width !== 0 || rect.height !== 0) setAnchorRect(rect);
    };
    window.addEventListener("scroll", reposition, true);
    return () => window.removeEventListener("scroll", reposition, true);
  }, [activeTarget]);

  // Focus the comment input as soon as the composing phase opens.
  useEffect(() => {
    if (phase.kind !== "composing") return;
    commentInputRef.current?.focus();
  }, [phase.kind]);

  // Dismiss the composing box on any click outside of it.
  useEffect(() => {
    if (phase.kind !== "composing") return;
    const handleMouseDown = (event: MouseEvent) => {
      if (boxRef.current?.contains(event.target as Node)) return;
      setPhase({ kind: "hidden" });
    };
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [phase.kind]);

  const cancelComposing = useCallback(() => {
    setPhase({ kind: "hidden" });
  }, []);

  const startComposing = useCallback(() => {
    setPhase((current) =>
      current.kind === "selection"
        ? { kind: "composing", target: current.target, comment: "" }
        : current
    );
  }, []);

  const commitComposing = useCallback(() => {
    const current = phaseRef.current;
    if (current.kind !== "composing") return;
    onAdd({
      quotedText: current.target.text,
      comment: current.comment.trim() || undefined,
      sourceMessageId: current.target.messageId,
      contextBefore: current.target.contextBefore,
      contextAfter: current.target.contextAfter,
    });
    setPhase({ kind: "hidden" });
    // Drop the text selection so the bubble does not re-open for the same
    // range right after the annotation is captured.
    window.getSelection()?.removeAllRanges();
  }, [onAdd]);

  const style = useMemo<CSSProperties | null>(() => {
    if (!anchorRect) return null;
    const height = phase.kind === "composing" ? COMPOSING_HEIGHT : PILL_HEIGHT;
    const above = anchorRect.top - height - BUBBLE_GAP;
    const top =
      above >= VIEWPORT_MARGIN ? above : anchorRect.bottom + BUBBLE_GAP;
    const maxLeft =
      window.innerWidth -
      (phase.kind === "composing" ? COMPOSING_WIDTH : 160) -
      VIEWPORT_MARGIN;
    const left = Math.min(
      Math.max(VIEWPORT_MARGIN, anchorRect.left),
      Math.max(VIEWPORT_MARGIN, maxLeft)
    );
    return { top, left };
  }, [anchorRect, phase.kind]);

  if (!enabled || phase.kind === "hidden" || !style) return null;

  return createPortal(
    <div
      ref={boxRef}
      role="toolbar"
      aria-label={t("chat.annotation.add")}
      style={{ ...style, position: "fixed" }}
      className={cn(
        "z-50 flex items-center gap-1.5 rounded-xl border border-border bg-background p-1.5 text-sm text-foreground shadow-md",
        phase.kind === "composing" && "w-80 p-2"
      )}
    >
      {phase.kind === "selection" ? (
        <button
          type="button"
          // Keep the text selection alive while clicking the pill.
          onMouseDown={(event) => event.preventDefault()}
          onClick={startComposing}
          className="flex h-7 items-center gap-1.5 rounded-lg px-2 text-xs font-medium hover:bg-accent"
        >
          <MessageSquareQuote className="size-4" aria-hidden />
          {t("chat.annotation.add")}
        </button>
      ) : (
        <>
          <input
            ref={commentInputRef}
            value={phase.comment}
            onChange={(event) =>
              setPhase((current) =>
                current.kind === "composing"
                  ? { ...current, comment: event.target.value }
                  : current
              )
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitComposing();
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancelComposing();
              }
            }}
            aria-label={t("chat.annotation.commentPlaceholder")}
            placeholder={t("chat.annotation.commentPlaceholder")}
            className="h-8 min-w-0 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-muted-foreground"
          />
          <button
            type="button"
            onClick={commitComposing}
            aria-label={t("chat.annotation.confirm")}
            title={t("chat.annotation.confirm")}
            className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg text-primary hover:bg-accent"
          >
            <CheckIcon className="size-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={cancelComposing}
            aria-label={t("chat.annotation.cancel")}
            title={t("chat.annotation.cancel")}
            className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent"
          >
            <XIcon className="size-4" aria-hidden />
          </button>
        </>
      )}
    </div>,
    document.body
  );
};
