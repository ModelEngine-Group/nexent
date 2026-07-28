"use client";

import { useEffect, type FC } from "react";
import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import { compositeAttachmentAdapter } from "../adapter/attachment-adapter";
import { remoteChatModelAdapter } from "../adapter/remote-chat-model-adapter";
import { Chat } from "./chat";

const NL2AGENT_DISPLAY: Agent = {
  id: "__nl2agent_runtime__",
  name: "NL2Agent",
  display_name: "NL2Agent",
  description:
    "Describe the agent you want to build and search installed MCP tools.",
  model: "main_model",
  max_step: 5,
  provide_run_summary: false,
  tools: [],
};

export const Nl2AgentChatPanel: FC = () => {
  const runtime = useLocalRuntime(remoteChatModelAdapter, {
    adapters: {
      attachments: compositeAttachmentAdapter,
    },
  });

  useEffect(() => {
    runtime.thread.composer.setRunConfig({
      custom: { runtimeMode: "nl2agent" },
    });
  }, [runtime]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-full w-full">
          <Chat selectedAgent={NL2AGENT_DISPLAY} isLoadingAgents={false} />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};
