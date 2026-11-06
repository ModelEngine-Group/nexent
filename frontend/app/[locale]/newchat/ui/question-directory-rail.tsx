// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, type FC } from "react";
import { Tooltip as TooltipPrimitive } from "radix-ui";
import { useTranslation } from "react-i18next";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  QuestionDirectoryButton,
  type QuestionDirectoryButtonProps,
} from "./question-directory";

/** Compact, persistent navigation in the conversation's reserved left gutter. */
export const QuestionDirectoryRail: FC<
  Omit<QuestionDirectoryButtonProps, "variant">
> = ({ questions, onJump, activeMessageId, className }) => {
  const { t } = useTranslation();
  const listRef = useRef<HTMLDivElement>(null);

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
        "group/rail pointer-events-none absolute bottom-24 left-0 top-14 z-20 flex w-8 flex-col items-center justify-center",
        className
      )}
    >
      {/* Display-only previews must not block adjacent ticks with hover grace areas. */}
      <TooltipProvider delayDuration={150} disableHoverableContent>
        <div
          ref={listRef}
          className="relative pointer-events-auto flex min-h-0 max-h-full w-full flex-col items-center overflow-y-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {questions.map((question) => {
            const active = question.messageId === activeMessageId;
            return (
              <Tooltip key={question.key}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    aria-label={t("chat.questions.jump", {
                      index: question.index,
                    })}
                    aria-current={active ? "location" : undefined}
                    onClick={() => onJump(question.messageId)}
                    className="group/tick relative flex h-[15px] min-h-[15px] w-8 shrink-0 items-center justify-center rounded-sm outline-none focus-visible:bg-accent focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring [@media(pointer:coarse)]:h-7 [@media(pointer:coarse)]:min-h-7"
                  >
                    <span
                      aria-hidden
                      className={cn(
                        "h-[3px] w-[9px] transition-colors group-hover/tick:bg-foreground/60 group-focus-visible/tick:bg-foreground/60",
                        active ? "bg-foreground/60" : "bg-foreground/20"
                      )}
                    />
                    {active && (
                      <span
                        aria-hidden
                        data-slot="question-rail-current-dot"
                        className="absolute left-[23px] size-[3px] rounded-full bg-foreground/60"
                      />
                    )}
                  </button>
                </TooltipTrigger>
                <TooltipPrimitive.Portal>
                  <TooltipContent
                    side="right"
                    sideOffset={8}
                    collisionPadding={12}
                    className="pointer-events-none w-72 max-w-[calc(100vw-4rem)] rounded-xl p-3 shadow-lg"
                  >
                    <div className="mb-1 text-[11px] text-muted-foreground">
                      Q{question.index}
                    </div>
                    <p className="line-clamp-4 whitespace-pre-wrap break-words text-sm font-medium">
                      {question.fullText}
                    </p>
                    <div className="my-2 h-px bg-border" />
                    <p className="line-clamp-5 whitespace-pre-wrap break-words text-xs text-muted-foreground">
                      {question.replyText || t("chat.questions.noReply")}
                    </p>
                  </TooltipContent>
                </TooltipPrimitive.Portal>
              </Tooltip>
            );
          })}
        </div>
      </TooltipProvider>
      <div className="pointer-events-auto shrink-0 opacity-0 transition-opacity focus-within:opacity-100 group-hover/rail:opacity-100 [@media(pointer:coarse)]:opacity-100">
        <QuestionDirectoryButton
          questions={questions}
          onJump={onJump}
          activeMessageId={activeMessageId}
          variant="header"
          className="size-8 text-muted-foreground"
        />
      </div>
    </nav>
  );
};
