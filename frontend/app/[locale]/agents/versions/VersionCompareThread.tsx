"use client";

import {
  AssistantRuntimeProvider,
  useAuiState,
  type AssistantRuntime,
} from "@assistant-ui/react";
import { ThreadMessages } from "@/app/newchat/assistant-ui/thread";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";

function Messages({
  agent,
  emptyPlaceholder,
}: {
  agent: Agent;
  emptyPlaceholder: string;
}) {
  const hasMessages = useAuiState((state) => state.thread.messages.length > 0);
  return hasMessages ? (
    <ThreadMessages agent={agent} readOnly />
  ) : (
    <div className="flex h-full items-center justify-center text-sm text-gray-400">
      {emptyPlaceholder}
    </div>
  );
}

export function VersionCompareThread({
  runtime,
  agent,
  emptyPlaceholder,
}: {
  runtime: AssistantRuntime;
  agent: Agent;
  emptyPlaceholder: string;
}) {
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-[360px] overflow-y-auto custom-scrollbar">
          <Messages agent={agent} emptyPlaceholder={emptyPlaceholder} />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
}
