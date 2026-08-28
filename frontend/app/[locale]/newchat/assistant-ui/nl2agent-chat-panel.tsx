"use client";

import { forwardRef, useImperativeHandle, useMemo } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { useTranslation } from "react-i18next";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import { compositeAttachmentAdapter } from "../adapter/attachment-adapter";
import { useConfig } from "@/hooks/useConfig";
import { ServerDictationAdapter } from "../adapter/server-dictation-adapter";
import {
  remoteChatModelAdapter,
  type Nl2AgentStateEvent,
} from "../adapter/remote-chat-model-adapter";
import { Chat } from "./chat";

const NL2AGENT_DISPLAY_BASE: Agent = {
  id: "__nl2agent_runtime__",
  name: "NL2Agent",
  description: "",
  model: "main_model",
  max_step: 8,
  provide_run_summary: false,
  tools: [],
};

export interface Nl2AgentChatPanelProps {
  agentId?: number | null;
  disabled?: boolean;
  onStateEvent?: (event: Nl2AgentStateEvent) => void;
  onStopped?: (agentId: number) => void;
}

export interface Nl2AgentChatPanelHandle {
  cancelRun: () => void;
}

export const Nl2AgentChatPanel = forwardRef<
  Nl2AgentChatPanelHandle,
  Nl2AgentChatPanelProps
>(function Nl2AgentChatPanel(
  { agentId = null, disabled = false, onStateEvent, onStopped },
  ref
) {
  const { t } = useTranslation("common");
  const { modelConfig } = useConfig();
  const adapters = useMemo(
    () => ({
      attachments: compositeAttachmentAdapter,
      dictation: new ServerDictationAdapter(() => modelConfig?.stt),
    }),
    [modelConfig?.stt]
  );
  const chatModelAdapter = useMemo<ChatModelAdapter>(
    () => ({
      run(options) {
        return remoteChatModelAdapter.run({
          ...options,
          runConfig: {
            custom: {
              ...options.runConfig?.custom,
              runtimeMode: "nl2agent",
              agentId,
              onNl2AgentState: onStateEvent,
              onNl2AgentStopped: onStopped,
            },
          },
        });
      },
    }),
    [agentId, onStateEvent, onStopped]
  );
  const runtime = useLocalRuntime(chatModelAdapter, { adapters });
  useImperativeHandle(
    ref,
    () => ({
      cancelRun: () => runtime.thread.cancelRun(),
    }),
    [runtime]
  );

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
            showModelSelector={false}
            showConversationTitle={false}
            readOnly={disabled}
            variant="embedded"
          />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
});
