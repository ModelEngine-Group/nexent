// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, type FC } from "react";
import { ListTreeIcon, PaperclipIcon } from "lucide-react";
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
   * Floating renders a compact pill chip (overlaid on the thread viewport);
   * header renders a ghost icon button for the persistent header bars.
   */
  variant?: "floating" | "header";
  className?: string;
}

/**
 * Entry point for the in-conversation question directory: lists every question
 * asked so far and jumps the message viewport to the selected turn. Rendered
 * as a floating chip when the surface has no persistent header, and as a
 * header icon button otherwise; the popover list is shared by both.
 */
export const QuestionDirectoryButton: FC<QuestionDirectoryButtonProps> = ({
  questions,
  onJump,
  variant = "floating",
  className,
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  if (questions.length === 0) return null;

  const label = t("chat.questions.viewAll", { count: questions.length });

  return (
    <Popover open={open} onOpenChange={setOpen}>
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
              className
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
        <ul
          className="flex max-h-80 flex-col gap-0.5 overflow-y-auto"
          aria-label={t("chat.questions.title")}
        >
          {questions.map((question) => (
            <li key={question.key}>
              <button
                type="button"
                title={question.fullText}
                aria-label={t("chat.questions.jump", {
                  index: question.index,
                })}
                onClick={() => {
                  setOpen(false);
                  onJump(question.messageId);
                }}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-blue-50 dark:hover:bg-slate-800"
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
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
};
