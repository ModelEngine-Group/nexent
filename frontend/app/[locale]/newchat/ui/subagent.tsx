"use client";

import { useState } from "react";
import {
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  LoaderIcon,
} from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

const subAgentAccentByDepth: Array<{
  border: string;
  icon: string;
}> = [
  {
    border: "border-primary/35",
    icon: "text-primary",
  },
  {
    border: "border-amber-400/45",
    icon: "text-amber-500",
  },
  {
    border: "border-emerald-400/45",
    icon: "text-emerald-500",
  },
  {
    border: "border-sky-400/45",
    icon: "text-sky-500",
  },
];

function accentForDepth(depth: number) {
  return subAgentAccentByDepth[
    Math.min(Math.max(depth - 1, 0), subAgentAccentByDepth.length - 1)
  ];
}

export interface SubAgentContainerProps {
  agentName: string;
  depth: number;
  isRunning?: boolean;
  task?: string;
  runId?: string;
  subagentId?: number | string;
  children?: React.ReactNode;
}

export const SubAgentContainer = ({
  agentName,
  depth,
  isRunning,
  task,
  runId,
  subagentId,
  children,
}: SubAgentContainerProps) => {
  // Open by default while the sub-agent is still running so users can watch
  // the reasoning and tool calls unfold.
  const [open, setOpen] = useState(Boolean(isRunning));
  const accent = accentForDepth(depth);

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={cn(
        "my-3 ml-3 overflow-hidden rounded-lg border bg-card/80 shadow-sm",
        accent.border,
      )}
      data-subagent-depth={depth}
      data-subagent-run-id={runId}
      data-subagent-id={subagentId}
    >
      <CollapsibleTrigger
        className="group flex w-full cursor-pointer flex-col gap-1.5 px-3.5 py-3 text-left transition-colors hover:bg-muted/40 data-[state=open]:bg-muted/25"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={cn(
              "flex shrink-0 items-center justify-center rounded-md bg-muted/80",
              accent.icon,
            )}
          >
            <BotIcon className="size-4" aria-hidden />
          </span>
          <span className="text-foreground min-w-0 truncate text-sm font-semibold">
            {agentName}
          </span>
          <Badge
            variant={isRunning ? "warning" : "success"}
            size="sm"
            className="ml-auto shrink-0 gap-1 border-0"
          >
            {isRunning ? (
              <LoaderIcon className="animate-spin" aria-hidden />
            ) : (
              <CheckIcon aria-hidden />
            )}
            {isRunning ? "Running" : "Completed"}
          </Badge>
          <ChevronDownIcon className="chevron size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
        </div>
        <div className="flex min-w-0 items-start gap-2.5 pl-6">
          <span
            className="text-muted-foreground line-clamp-2 text-[11px] leading-relaxed"
            title={task}
          >
            {task || "No task description"}
          </span>
        </div>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-2 border-t border-border/60 px-3.5 py-3">
          {children}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};

// -----------------------------------------------------------------------------
// Sub-agent part rendering
// -----------------------------------------------------------------------------

// Sub-agent inner parts are rendered by ``MessagePrimitive.GroupedParts`` in
// ``thread.tsx`` directly: every member part carries the same ``metadata``,
// so the existing renderers (``Reasoning``, ``ToolFallback``, ``Sources``,
// ``MarkdownText``) are reused unchanged. The dedicated
// ``SubAgentMessageParts`` renderer previously needed for the nested content
// array has been removed; ``SubAgentContainer`` simply hosts the parts that
// ``GroupedParts`` renders as its ``children``.
export {};