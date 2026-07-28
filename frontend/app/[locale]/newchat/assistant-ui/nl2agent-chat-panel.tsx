"use client";

import { useEffect, type FC } from "react";
import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import { compositeAttachmentAdapter } from "../adapter/attachment-adapter";
import { remoteChatModelAdapter } from "../adapter/remote-chat-model-adapter";
import { Chat } from "./chat";

const NL2AGENT_DISPLAY_BASE: Agent = {
  id: "__nl2agent_runtime__",
  name: "NL2Agent",
  description: "",
  model: "main_model",
  max_step: 5,
  provide_run_summary: false,
  tools: [],
};

export const Nl2AgentChatPanel: FC = () => {
  const { t } = useTranslation("common");
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

  const assistantTitle = t("agentConfig.button.generationAssistant");
  const nl2AgentDisplay: Agent = {
    ...NL2AGENT_DISPLAY_BASE,
    display_name: assistantTitle,
    description: t("nl2agent.assistant.description"),
  };

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-full w-full">
          <Chat
            selectedAgent={nl2AgentDisplay}
            generatedTitle={assistantTitle}
            isLoadingAgents={false}
          />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};
