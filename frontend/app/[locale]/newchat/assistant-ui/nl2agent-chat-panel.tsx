// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useSyncExternalStore,
} from "react";
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
import type { AgentSuggestionItem } from "@/types/agentSuggestion";
import { Thread } from "./thread";
import { AgentWelcome } from "@/components/agent/agent-welcome";
import { CardSuggestion } from "@/components/agent/agent-suggestion";
import { NL2AGENT_DEFAULT_SUGGESTIONS } from "@/const/nl2agent";

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
  onRunStart?: (agentId: number) => void;
  onRunEnd?: (agentId: number) => void;
}

export interface Nl2AgentChatPanelHandle {
  cancelRun: () => void;
  sendPrompt: (prompt: string) => void;
}

export const Nl2AgentChatPanel = forwardRef<
  Nl2AgentChatPanelHandle,
  Nl2AgentChatPanelProps
>(function Nl2AgentChatPanel(
  {
    agentId = null,
    disabled = false,
    showOptimizationSuggestions = true,
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
  const isRunning = useSyncExternalStore(
    runtime.thread.subscribe,
    () => runtime.thread.getState().isRunning,
    () => false
  );
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
  const welcomeSuggestions = useMemo<readonly AgentSuggestionItem[]>(
    () =>
      showOptimizationSuggestions
        ? NL2AGENT_DEFAULT_SUGGESTIONS.map(
            ({ id, titleKey, descriptionKey, promptKey }) => ({
              id,
              title: t(titleKey),
              description: t(descriptionKey),
              prompt: t(promptKey),
            })
          )
        : [],
    [showOptimizationSuggestions, t]
  );
  const nl2AgentDisplay: Agent = {
    ...NL2AGENT_DISPLAY_BASE,
    display_name: assistantTitle,
    description: t("nl2agent.assistant.description"),
    example_questions: welcomeSuggestions.map(
      (suggestion) => suggestion.prompt
    ),
  };

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-full w-full">
          <Thread
            agent={nl2AgentDisplay}
            generatedTitle={assistantTitle}
            chatMode="execution"
            onChatModeChange={() => undefined}
            showModelSelector={false}
            showConversationTitle={false}
            isDictationConfigured={Boolean(modelConfig?.stt)}
            readOnly={disabled}
            variant="embedded"
            welcomeContent={
              <AgentWelcome
                title={t("nl2agent.configuration.title")}
                greeting={t("nl2agent.configuration.description")}
              >
                <CardSuggestion
                  disabled={disabled || isRunning}
                  suggestions={welcomeSuggestions}
                  onSelect={(prompt) => runtime.thread.composer.setText(prompt)}
                />
              </AgentWelcome>
            }
          />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
});
