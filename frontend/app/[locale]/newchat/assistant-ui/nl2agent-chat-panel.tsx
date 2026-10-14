"use client";

import { forwardRef, useImperativeHandle, useMemo } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
  useAuiState,
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
import { Thread } from "./thread";
import { AgentConfigurationWelcome } from "./agent-configuration-welcome";

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
  configurationLayout?: boolean;
  onStateEvent?: (event: Nl2AgentStateEvent) => void;
  onStopped?: (agentId: number) => void;
  onRunStart?: (agentId: number) => void;
  onRunEnd?: (agentId: number) => void;
}

export interface Nl2AgentChatPanelHandle {
  cancelRun: () => void;
  sendPrompt: (prompt: string) => void;
}

function ConfigurationThread({
  agent,
  disabled,
  dictationConfigured,
}: {
  agent: Agent;
  disabled: boolean;
  dictationConfigured: boolean;
}) {
  const hasMessages = useAuiState((state) => state.thread.messages.length > 0);
  return (
    <Thread
      agent={agent}
      chatMode="execution"
      onChatModeChange={() => undefined}
      showConversationTitle={false}
      showModelSelector={false}
      variant="embedded"
      readOnly={disabled}
      configurationLayout
      showComposer={hasMessages}
      isDictationConfigured={dictationConfigured}
      welcomeContent={
        <AgentConfigurationWelcome
          disabled={disabled}
          dictationConfigured={dictationConfigured}
        />
      }
    />
  );
}

export const Nl2AgentChatPanel = forwardRef<
  Nl2AgentChatPanelHandle,
  Nl2AgentChatPanelProps
>(function Nl2AgentChatPanel(
  {
    agentId = null,
    disabled = false,
    showOptimizationSuggestions = false,
    configurationLayout = false,
    onStateEvent,
    onStopped,
    onRunStart,
    onRunEnd,
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
      async *run(options) {
        if (agentId !== null) onRunStart?.(agentId);
        try {
          const runResult = remoteChatModelAdapter.run({
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
          if ("then" in runResult) {
            yield await runResult;
          } else {
            yield* runResult;
          }
        } finally {
          if (agentId !== null) onRunEnd?.(agentId);
        }
      },
    }),
    [agentId, onRunEnd, onRunStart, onStateEvent, onStopped]
  );
  const runtime = useLocalRuntime(chatModelAdapter, { adapters });
  useImperativeHandle(
    ref,
    () => ({
      cancelRun: () => runtime.thread.cancelRun(),
      sendPrompt: (prompt) => {
        if (
          disabled ||
          agentId === null ||
          !prompt.trim() ||
          runtime.thread.getState().isRunning
        )
          return;
        runtime.thread.append({
          role: "user",
          content: [{ type: "text", text: prompt.trim() }],
        });
      },
    }),
    [agentId, disabled, runtime]
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
              description: t("nl2agent.optimization.conversation.description"),
              prompt: t("nl2agent.optimization.conversation.input"),
            },
          ]
        : undefined,
    [showOptimizationSuggestions, t]
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div
          className={
            configurationLayout
              ? "h-full w-full bg-[radial-gradient(ellipse_at_20%_48%,rgba(222,248,251,0.45),transparent_48%),radial-gradient(ellipse_at_85%_52%,rgba(234,224,251,0.4),transparent_50%)] [font-family:'HarmonyOS_Sans_SC',sans-serif]"
              : "h-full w-full"
          }
        >
          {configurationLayout ? (
            <ConfigurationThread
              agent={nl2AgentDisplay}
              disabled={disabled}
              dictationConfigured={Boolean(modelConfig?.stt)}
            />
          ) : (
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
          )}
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
});
