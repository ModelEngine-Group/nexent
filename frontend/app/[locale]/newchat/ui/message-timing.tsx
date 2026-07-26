"use client";

import { useMessageTiming } from "@assistant-ui/react";
import { ClockIcon } from "lucide-react";
import { type FC } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const formatMs = (ms: number) =>
  ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;

export interface MessageTimingProps {
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
}

export const MessageTiming: FC<MessageTimingProps> = ({
  className,
  side = "right",
}) => {
  const timing = useMessageTiming();
  if (!timing?.totalStreamTime) return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          data-slot="aui-message-timing"
          aria-label={`Generated in ${formatMs(timing.totalStreamTime)}`}
          className={cn(
            "text-muted-foreground inline-flex cursor-default items-center gap-1 text-xs",
            className
          )}
        >
          <ClockIcon className="size-3" />
          {formatMs(timing.totalStreamTime)}
        </span>
      </TooltipTrigger>
      <TooltipContent side={side}>
        {timing.firstTokenTime !== undefined && (
          <p>TTFT: {formatMs(timing.firstTokenTime)}</p>
        )}
        <p>Total: {formatMs(timing.totalStreamTime)}</p>
        {timing.tokensPerSecond !== undefined && (
          <p>{timing.tokensPerSecond.toFixed(1)} tok/s</p>
        )}
        {timing.tokenCount !== undefined && <p>Tokens: {timing.tokenCount}</p>}
        {timing.toolCallCount > 0 && <p>Tool calls: {timing.toolCallCount}</p>}
        {timing.totalChunks > 0 && <p>Chunks: {timing.totalChunks}</p>}
      </TooltipContent>
    </Tooltip>
  );
};

MessageTiming.displayName = "MessageTiming";
