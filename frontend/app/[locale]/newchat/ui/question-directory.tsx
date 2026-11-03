// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef, useState, type FC } from "react";
import { createPortal } from "react-dom";
import { ListTreeIcon, PaperclipIcon, SearchIcon } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import type { QuestionDirectoryEntry } from "../utils/question-directory";

export interface QuestionDirectoryButtonProps {
  /** User question turns collected across the conversation. */
  questions: QuestionDirectoryEntry[];
  /** Scrolls the thread to the clicked question's message. */
  onJump: (messageId: string) => void;
  /**
   * Message id of the question the viewport is currently scrolled to; the
   * matching entry is highlighted and labelled as the current position.
   */
  activeMessageId?: string | null;
  /**
   * Floating renders a compact pill chip (overlaid on the thread viewport);
   * header renders a ghost icon button for the persistent header bars.
   */
  variant?: "floating" | "header";
  className?: string;
}

/** Hover delay before the preview card opens (ms). */
const PREVIEW_OPEN_DELAY_MS = 150;
/** Fixed width of the hover preview card. */
const PREVIEW_WIDTH = 320;
/** Rough height budget used to keep the preview card inside the viewport. */
const PREVIEW_MAX_HEIGHT = 360;

/** A preview card anchored to one hovered directory row. */
interface PreviewState {
  entry: QuestionDirectoryEntry;
  x: number;
  y: number;
}

/**
 * Entry point for the in-conversation question directory: lists every question
 * asked so far and jumps the message viewport to the selected turn. Rendered
 * as a floating chip when the surface has no persistent header, and as a
 * header icon button otherwise; the popover list is shared by both and offers
 * a keyword filter over the full question text. Hovering (or focusing) a row
 * opens a preview card with the full question and an excerpt of its assistant
 * reply, and the row the viewport is currently scrolled to is highlighted as
 * the current position.
 */
export const QuestionDirectoryButton: FC<QuestionDirectoryButtonProps> = ({
  questions,
  onJump,
  activeMessageId = null,
  variant = "floating",
  className,
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const previewTimer = useRef<number | null>(null);

  const clearPreviewTimer = () => {
    if (previewTimer.current !== null) {
      window.clearTimeout(previewTimer.current);
      previewTimer.current = null;
    }
  };

  // The hover timer must never outlive the component.
  useEffect(() => clearPreviewTimer, []);

  // Match against the full text (not the truncated summary) so keywords from
  // any line of the question still find the entry; case-insensitive.
  const filteredQuestions = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return questions;
    return questions.filter((question) =>
      question.fullText.toLowerCase().includes(keyword),
    );
  }, [questions, search]);

  if (questions.length === 0) return null;

  const label = t("chat.questions.viewAll", { count: questions.length });

  const showPreview = (
    question: QuestionDirectoryEntry,
    element: HTMLElement,
  ) => {
    clearPreviewTimer();
    previewTimer.current = window.setTimeout(() => {
      const rect = element.getBoundingClientRect();
      // Prefer the left side of the hovered row; fall back to the right side
      // and clamp so the card stays inside the viewport.
      const leftX = rect.left - PREVIEW_WIDTH - 12;
      const rightX = Math.min(
        rect.right + 12,
        window.innerWidth - PREVIEW_WIDTH - 8,
      );
      const x = leftX >= 8 ? leftX : Math.max(8, rightX);
      const y = Math.max(
        8,
        Math.min(rect.top, window.innerHeight - PREVIEW_MAX_HEIGHT),
      );
      setPreview({ entry: question, x, y });
    }, PREVIEW_OPEN_DELAY_MS);
  };

  const hidePreview = () => {
    clearPreviewTimer();
    setPreview(null);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        // Reset the filter and drop the preview between sessions so
        // reopening starts from the full directory.
        if (!nextOpen) {
          setSearch("");
          clearPreviewTimer();
          setPreview(null);
        }
      }}
    >
      <PopoverTrigger asChild>
        {variant === "header" ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={label}
            className={className}
          >
            <ListTreeIcon className="size-4" />
          </Button>
        ) : (
          <button
            type="button"
            aria-label={label}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white/95 px-3 py-1 text-xs text-muted-foreground shadow-md backdrop-blur-sm transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-900/95 dark:text-slate-300 dark:hover:border-blue-800 dark:hover:bg-slate-950 dark:hover:text-blue-300",
              className,
            )}
          >
            <ListTreeIcon className="size-3.5" />
            {label}
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-2">
        <div className="flex items-center justify-between gap-2 px-2 pb-2 pt-1">
          <span className="text-sm font-medium text-foreground">
            {t("chat.questions.title")}
          </span>
          <span className="text-xs text-muted-foreground">
            {t("chat.questions.total", { count: questions.length })}
          </span>
        </div>
        <div className="flex items-center gap-2 rounded-md border border-slate-200 px-2 py-1.5 dark:border-slate-700">
          <SearchIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("chat.questions.search")}
            aria-label={t("chat.questions.search")}
            className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
          />
        </div>
        <ul
          className="flex max-h-80 flex-col gap-0.5 overflow-y-auto pt-1"
          aria-label={t("chat.questions.title")}
        >
          {filteredQuestions.map((question) => {
            const isActive = question.messageId === activeMessageId;
            return (
              <li key={question.key}>
                <button
                  type="button"
                  aria-current={isActive ? "location" : undefined}
                  aria-label={t("chat.questions.jump", {
                    index: question.index,
                  })}
                  onClick={() => {
                    setOpen(false);
                    onJump(question.messageId);
                  }}
                  onMouseEnter={(event) =>
                    showPreview(question, event.currentTarget)
                  }
                  onMouseLeave={hidePreview}
                  onFocus={(event) =>
                    showPreview(question, event.currentTarget)
                  }
                  onBlur={hidePreview}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-blue-50 dark:hover:bg-slate-800",
                    isActive && "bg-blue-50 font-medium dark:bg-slate-800/70",
                  )}
                >
                  <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                    Q{question.index}
                  </span>
                  {question.kind === "attachment" && (
                    <PaperclipIcon className="size-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <span className="min-w-0 flex-1 truncate text-xs text-foreground">
                    {question.summary}
                  </span>
                  {isActive && (
                    <span
                      data-testid="question-directory-active"
                      className="shrink-0 rounded-full bg-blue-600/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-400/10 dark:text-blue-300"
                    >
                      {t("chat.questions.current")}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
          {filteredQuestions.length === 0 && (
            <li
              className="px-2 py-6 text-center text-xs text-muted-foreground"
              data-testid="question-directory-no-matches"
            >
              {t("chat.questions.noMatches")}
            </li>
          )}
        </ul>
      </PopoverContent>
      {preview
        ? createPortal(
            <div
              data-testid="question-directory-preview"
              role="tooltip"
              className="pointer-events-none fixed z-50 w-80 rounded-xl border bg-popover/95 p-3 shadow-xl backdrop-blur-sm"
              style={{ left: preview.x, top: preview.y }}
            >
              <p className="line-clamp-4 text-sm font-medium break-words whitespace-pre-wrap text-foreground">
                {preview.entry.fullText}
              </p>
              <div className="bg-border my-2 h-px" />
              <p className="line-clamp-5 text-xs break-words whitespace-pre-wrap text-muted-foreground">
                {preview.entry.replyText || t("chat.questions.noReply")}
              </p>
            </div>,
            document.body,
          )
        : null}
    </Popover>
  );
};
