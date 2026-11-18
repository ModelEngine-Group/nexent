// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function OverflowTooltipText({
  children,
  className,
}: {
  children: ReactNode;
  className: string;
}) {
  const textRef = useRef<HTMLSpanElement>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const [isTooltipOpen, setIsTooltipOpen] = useState(false);

  useEffect(() => {
    const textElement = textRef.current;
    if (!textElement) return;
    const updateOverflow = () => {
      const overflow = textElement.scrollWidth > textElement.clientWidth;
      setIsOverflowing(overflow);
      if (!overflow) setIsTooltipOpen(false);
    };
    updateOverflow();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(textElement);
    return () => observer.disconnect();
  }, [children]);

  return (
    <Tooltip
      open={isOverflowing && isTooltipOpen}
      onOpenChange={(open) => {
        if (isOverflowing) setIsTooltipOpen(open);
      }}
    >
      <TooltipTrigger asChild>
        <span ref={textRef} data-history-title className={className}>
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-80 break-words">
        {children}
      </TooltipContent>
    </Tooltip>
  );
}

/** Share truncation and metadata visibility without moving the title on hover. */
export function ConversationHistoryLabel({
  title,
  time,
  status,
  showActions = true,
}: {
  title: string;
  time?: string;
  status?: ReactNode;
  showActions?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2 text-left">
      <OverflowTooltipText className="min-w-0 flex-1 truncate text-left">
        {title}
      </OverflowTooltipText>
      {status}
      {(time || showActions) && (
        <span
          data-history-time={time ? true : undefined}
          className={cn(
            "flex h-7 shrink-0 items-center justify-center whitespace-nowrap text-xs text-muted-foreground",
            showActions &&
              "min-w-7 group-hover/item:invisible group-focus-within/item:invisible"
          )}
        >
          {time}
        </span>
      )}
    </div>
  );
}
