"use client";

import { forwardRef, useImperativeHandle, useMemo } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import {
  MessageSquareIcon,
  SparklesIcon,
  WrenchIcon,
  ZapIcon,
} from "lucide-react";

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
import type { WelcomeSuggestion } from "./thread";

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
  showOptimizationSuggestions?: boolean;
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
  {
    agentId = null,
    disabled = false,
    showOptimizationSuggestions = false,
    onStateEvent,
    onStopped,
  },
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
  const welcomeSuggestions = useMemo<readonly WelcomeSuggestion[] | undefined>(
    () =>
      showOptimizationSuggestions
        ? [
            {
              id: "optimize-prompts",
              icon: SparklesIcon,
              title: t("nl2agent.optimization.prompt.title"),
              description: t("nl2agent.optimization.prompt.description"),
              prompt: t("nl2agent.optimization.prompt.input"),
            },
            {
              id: "recommend-tools",
              icon: WrenchIcon,
              title: t("nl2agent.optimization.tools.title"),
              description: t("nl2agent.optimization.tools.description"),
              prompt: t("nl2agent.optimization.tools.input"),
            },
            {
              id: "recommend-skills",
              icon: ZapIcon,
              title: t("nl2agent.optimization.skills.title"),
              description: t("nl2agent.optimization.skills.description"),
              prompt: t("nl2agent.optimization.skills.input"),
            },
            {
              id: "optimize-conversation-guide",
              icon: MessageSquareIcon,
              title: t("nl2agent.optimization.conversation.title"),
              description: t(
                "nl2agent.optimization.conversation.description"
              ),
              prompt: t("nl2agent.optimization.conversation.input"),
            },
          ]
        : undefined,
    [showOptimizationSuggestions, t]
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-full w-full">
          <Chat
            selectedAgent={nl2AgentDisplay}
            generatedTitle={assistantTitle}
            welcomeSuggestions={welcomeSuggestions}
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
