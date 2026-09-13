"use client";

import { forwardRef, useImperativeHandle, useMemo, useState, useEffect } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { NexusAgent, type NexusRunConfig } from "@/lib/assistant-ui/nexus-agent";
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
import { Chat } from "./chat";
import type { WelcomeSuggestion } from "./thread";
import { getAuthHeaders } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";

// Register nl2agent endpoint URL with NexusAgent
NexusAgent.registerEndpoint("nl2agent", API_ENDPOINTS.agent.nl2agentRun);

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
  onStateEvent?: (event: unknown) => void;
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

  // ---- NexusAgent: memoized with nl2agent endpoint -------------------------
  const nexusAgent = useMemo(
    () =>
      new NexusAgent({
        url: API_ENDPOINTS.agent.nl2agentRun,
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
          "x-agui-format": "true",
        },
      }),
    []
  );

  // ---- runConfig ----------------------------------------------------------
  const [runConfig, setRunConfig] = useState<NexusRunConfig>({
    agent_id: agentId ?? undefined,
    runtime_mode: "nl2agent",
  });

  useEffect(() => {
    nexusAgent.setRunConfig({
      agent_id: agentId ?? undefined,
      runtime_mode: "nl2agent",
    });
  }, [nexusAgent, agentId]);

  const adapters = useMemo(
    () => ({
      attachments: compositeAttachmentAdapter,
      dictation: new ServerDictationAdapter(() => modelConfig?.stt),
    }),
    [modelConfig?.stt]
  );

  // ---- useAgUiRuntime -----------------------------------------------------
  const runtime = useAgUiRuntime({
    agent: nexusAgent,
    adapters,
    showThinking: true,
    onError: (e) => console.error("[NL2Agent] AG-UI runtime error:", e),
  });

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
