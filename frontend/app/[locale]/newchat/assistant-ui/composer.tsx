"use client";

import { useState, type FC, type ReactNode } from "react";
import {
  ArrowUp,
  Mic,
  Square,
  Lightbulb,
  Play,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  AuiIf,
  ComposerPrimitive,
} from "@assistant-ui/react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  ModelSelector,
  type ModelOption,
} from "../ui/model-selector";
import { ComposerAttachments, ComposerAddAttachment } from "../ui/attachment";

type ChatMode = "planning" | "execution";

export interface ComposerProps {
  models: readonly ModelOption[];
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
}

// Simple tooltip wrapper
const TooltipWrapper: FC<{
  tooltip: string;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactNode;
}> = ({ tooltip, side = "bottom", children }) => {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side}>{tooltip}</TooltipContent>
    </Tooltip>
  );
};

export const Composer: FC<ComposerProps> = ({
  models,
  selectedModelId,
  onModelChange,
}) => {
  const [chatMode, setChatMode] = useState<ChatMode>("execution");

  return (
    <div className="flex w-full flex-col rounded-2xl border border-border bg-card shadow-sm">
      {/* Mode switcher above input */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        {/* Mode switcher */}
        <div className="flex items-center rounded-lg border border-border bg-muted/50 p-0.5">
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "h-6 gap-1 rounded-md px-2 text-xs transition-colors",
              chatMode === "planning" && "bg-blue-50 text-blue-600 hover:bg-blue-50"
            )}
            onClick={() => setChatMode("planning")}
          >
            <Lightbulb className={cn("size-3", chatMode === "planning" ? "text-blue-600" : "")} />
            规划
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "h-6 gap-1 rounded-md px-2 text-xs transition-colors",
              chatMode === "execution" && "bg-blue-50 text-blue-600 hover:bg-blue-50"
            )}
            onClick={() => setChatMode("execution")}
          >
            <Play className="size-3" />
            执行
          </Button>
        </div>

        {/* Placeholder for alignment */}
        <div className="w-16" />
      </div>

      {/* Composer Primitive Root */}
      <ComposerPrimitive.Root
        className="flex w-full flex-col px-1 py-1 outline-none"
      >
        <ComposerAttachments />
        <ComposerPrimitive.Input
          placeholder="发送消息..."
          className="mb-1 max-h-32 min-h-14 w-full resize-none bg-transparent px-3 py-1 text-sm outline-none placeholder:text-muted-foreground"
          rows={1}
          submitMode="enter"
          autoFocus
        />
        <div className="relative mx-2 mb-2 flex items-center justify-between gap-2">
          <ModelSelector
            models={models}
            value={selectedModelId}
            onValueChange={onModelChange}
            variant="ghost"
            size="sm"
            className="text-xs"
          />
          <div className="flex items-center gap-1">
            <ComposerAddAttachment />
            <ComposerPrimitive.Dictate asChild>
              <TooltipWrapper tooltip="语音输入">
                <Button variant="ghost" size="icon" className="size-8 text-muted-foreground">
                  <Mic className="size-4" />
                </Button>
              </TooltipWrapper>
            </ComposerPrimitive.Dictate>
            <ComposerSendOrCancel />
          </div>
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
};

// `ComposerPrimitive.Cancel` / `Send` forward their internal `onClick` to the
// direct child via Radix Slot, so the Button MUST be the immediate child for
// the click handler to actually fire. The tooltip wrapper sits outside so its
// Trigger can use `asChild` against the Button. `AuiIf` toggles between the
// two branches declaratively based on `thread.isRunning`.
const ComposerSendOrCancel: FC = () => (
  <>
    <AuiIf condition={(s) => s.thread.isRunning}>
      <TooltipWrapper tooltip="停止生成" side="top">
        <ComposerPrimitive.Cancel asChild>
          <Button
            size="icon"
            variant="outline"
            className="size-8 rounded-full ml-2 border-border bg-background text-primary hover:bg-muted"
          >
            <Square className="size-4 fill-current" />
          </Button>
        </ComposerPrimitive.Cancel>
      </TooltipWrapper>
    </AuiIf>
    <AuiIf condition={(s) => !s.thread.isRunning}>
      <TooltipWrapper tooltip="发送" side="top">
        <ComposerPrimitive.Send asChild>
          <Button size="icon" className="size-8 rounded-full ml-2">
            <ArrowUp className="size-5" />
          </Button>
        </ComposerPrimitive.Send>
      </TooltipWrapper>
    </AuiIf>
  </>
);