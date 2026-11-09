// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState, type FC } from "react";
import { Popover as PopoverPrimitive } from "radix-ui";
import { Bookmark } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Popover, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { QuestionDirectoryEntry } from "../utils/question-directory";

export interface QuestionDirectoryRailProps {
  questions: QuestionDirectoryEntry[];
  onJump: (messageId: string) => void;
  activeMessageId?: string | null;
  className?: string;
  bookmarkedIds?: ReadonlySet<string>;
  onBookmark?: (messageId: string, bookmarked: boolean) => void;
  canBookmark?: (messageId: string) => boolean;
  bookmarkFailed?: boolean;
  onBookmarkRetry?: () => void;
}

/** Compact, persistent navigation in the conversation's reserved left gutter. */
export const QuestionDirectoryRail: FC<QuestionDirectoryRailProps> = ({
  questions,
  onJump,
  activeMessageId,
  className,
  bookmarkedIds,
  onBookmark,
  canBookmark,
  bookmarkFailed,
  onBookmarkRetry,
}) => {
  const { t } = useTranslation();
  const listRef = useRef<HTMLDivElement>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keepPreview = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  };
  const leavePreview = () => {
    keepPreview();
    closeTimer.current = setTimeout(() => setPreviewId(null), 180);
  };
  useEffect(
    () => () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
    },
    []
  );

  useEffect(() => {
    const list = listRef.current;
    const current = list?.querySelector<HTMLButtonElement>(
      '[aria-current="location"]'
    );
    if (!list || !current) return;
    // Scroll only the rail, never the surrounding chat or page.
    const top = current.offsetTop;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (top + current.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top + current.offsetHeight - list.clientHeight;
    }
  }, [activeMessageId, questions.length]);

  if (!questions.length) return null;

  return (
    <nav
      aria-label={t("chat.questions.title")}
      className={cn(
        "pointer-events-none absolute bottom-24 left-0 top-14 z-20 flex w-8 flex-col items-center justify-center",
        className
      )}
    >
      <div
        ref={listRef}
        className="relative pointer-events-auto flex min-h-0 max-h-full w-full flex-col items-center overflow-y-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {questions.map((question) => {
          const active = question.messageId === activeMessageId;
          const bookmarked = bookmarkedIds?.has(question.messageId) ?? false;
          return (
            <Popover
              key={question.key}
              open={previewId === question.messageId}
              onOpenChange={(open) => {
                if (!open)
                  setPreviewId((id) => (id === question.messageId ? null : id));
              }}
            >
              <PopoverPrimitive.Anchor asChild>
                <button
                  type="button"
                  aria-label={t("chat.questions.jump", {
                    index: question.index,
                  })}
                  aria-current={active ? "location" : undefined}
                  aria-haspopup="dialog"
                  aria-controls={`question-preview-${question.key}`}
                  aria-expanded={previewId === question.messageId}
                  onPointerMove={() => {
                    keepPreview();
                    setPreviewId(question.messageId);
                  }}
                  onPointerLeave={leavePreview}
                  onFocus={() => {
                    keepPreview();
                    setPreviewId(question.messageId);
                  }}
                  onBlur={leavePreview}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowRight") {
                      event.preventDefault();
                      document
                        .getElementById(`question-preview-${question.key}`)
                        ?.querySelector<HTMLButtonElement>("button")
                        ?.focus();
                    }
                    if (event.key === "Escape") {
                      keepPreview();
                      setPreviewId(null);
                    }
                  }}
                  onClick={() => onJump(question.messageId)}
                  className="group/tick relative flex h-[15px] min-h-[15px] w-8 shrink-0 items-center justify-center rounded-sm outline-none focus-visible:bg-accent focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring [@media(pointer:coarse)]:h-7 [@media(pointer:coarse)]:min-h-7"
                >
                  <span
                    aria-hidden
                    className={cn(
                      "h-[3px] w-[9px] transition-colors group-hover/tick:bg-foreground/60 group-focus-visible/tick:bg-foreground/60",
                      bookmarked
                        ? "bg-primary"
                        : active
                          ? "bg-foreground/60"
                          : "bg-foreground/20"
                    )}
                  />
                  {bookmarked && (
                    <Bookmark
                      aria-hidden
                      data-slot="question-rail-bookmark"
                      className="absolute left-0 size-2 fill-primary text-primary"
                    />
                  )}
                  {active && (
                    <span
                      aria-hidden
                      data-slot="question-rail-current-dot"
                      className="absolute left-[23px] size-[3px] rounded-full bg-foreground/60"
                    />
                  )}
                </button>
              </PopoverPrimitive.Anchor>
              <PopoverContent
                id={`question-preview-${question.key}`}
                side="right"
                sideOffset={8}
                collisionPadding={12}
                aria-label={t("chat.questions.jump", { index: question.index })}
                onOpenAutoFocus={(event) => event.preventDefault()}
                onCloseAutoFocus={(event) => event.preventDefault()}
                onPointerEnter={keepPreview}
                onPointerLeave={leavePreview}
                onFocusCapture={keepPreview}
                onBlurCapture={leavePreview}
                className="pointer-events-auto w-72 max-w-[calc(100vw-4rem)] rounded-xl p-3 shadow-lg"
              >
                <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                  Q{question.index}
                  {onBookmark && (
                    <button
                      type="button"
                      aria-label={t(
                        bookmarked
                          ? "chat.questions.unbookmark"
                          : "chat.questions.bookmark"
                      )}
                      aria-pressed={bookmarked}
                      disabled={
                        canBookmark ? !canBookmark(question.messageId) : false
                      }
                      onClick={() =>
                        onBookmark(question.messageId, !bookmarked)
                      }
                      className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-40"
                    >
                      <Bookmark
                        aria-hidden
                        className={cn(
                          "size-4",
                          bookmarked && "fill-primary text-primary"
                        )}
                      />
                    </button>
                  )}
                </div>
                {bookmarkFailed && (
                  <div role="alert" className="mb-2 text-xs text-destructive">
                    {t("chat.questions.bookmarkFailed")}
                    <button
                      type="button"
                      onClick={onBookmarkRetry}
                      className="ml-2 underline"
                    >
                      {t("chat.questions.bookmarkRetry")}
                    </button>
                  </div>
                )}
                <p className="line-clamp-4 whitespace-pre-wrap break-words text-sm font-medium">
                  {question.fullText}
                </p>
                <div className="my-2 h-px bg-border" />
                <p className="line-clamp-5 whitespace-pre-wrap break-words text-xs text-muted-foreground">
                  {question.replyText || t("chat.questions.noReply")}
                </p>
              </PopoverContent>
            </Popover>
          );
        })}
      </div>
    </nav>
  );
};
