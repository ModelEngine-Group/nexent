// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
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
import { useCreatorModelControls } from "@/features/model-controls/useCreatorModelControls";
import { AgentWelcome } from "@/components/agent/agent-welcome";
import { CardSuggestion } from "@/components/agent/agent-suggestion";
import { NL2AGENT_DEFAULT_SUGGESTIONS } from "@/const/nl2agent";
import { AGENT_CREATION_EXAMPLES } from "@/const/agentCreationExamples";
import { message } from "antd";
import { conversationService } from "@/services/conversationService";
import { useCreatorHistories } from "@/hooks/chat/useCreatorHistories";
import { CreatorHistoryToolbar } from "./creator-history-toolbar";

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
  agentDescription?: string | null;
  disabled?: boolean;
  /** Controls visibility in both creation and optimization modes. */
  showOptimizationSuggestions?: boolean;
  onStateEvent?: (event: Nl2AgentStateEvent) => void;
  onStopped?: (agentId: number) => void;
  onRunStart?: (agentId: number) => void;
  onRunEnd?: (agentId: number) => void;
  onConversationChange?: (agentId: number) => void;
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
    agentDescription,
    disabled = false,
    showOptimizationSuggestions = true,
    onStateEvent,
    onStopped,
    onRunStart,
    onRunEnd,
    onConversationChange,
  },
  ref
) {
  const { t } = useTranslation("common");
  const { modelConfig } = useConfig();
  const historyRef = useRef<{ agentId: number | null; id?: string }>({
    agentId,
  });
  if (historyRef.current.agentId !== agentId) historyRef.current = { agentId };
  const history = useCreatorHistories("agent", agentId);
  const [selectedId, setSelectedId] = useState<string>();
  const [restoring, setRestoring] = useState(false);
  const loadGeneration = useRef(0);
  useEffect(
    () => () => {
      loadGeneration.current++;
    },
    [agentId]
  );
  const modelControls = useCreatorModelControls(
    NL2AGENT_DISPLAY_BASE,
    `nl2agent:${agentId ?? "new"}`,
    "agent:create"
  );
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
        if (!modelControls.canSend || restoring) return;
        if (agentId !== null) onRunStart?.(agentId);
        try {
          const runResult = remoteChatModelAdapter.run({
            ...options,
            runConfig: {
              custom: {
                ...options.runConfig?.custom,
                runtimeMode: "nl2agent",
                threadId: historyRef.current.id,
                onServerConversationId: (id: string) => {
                  historyRef.current.id = id;
                  setSelectedId(id);
                  void history.refresh();
                },
                agentId,
                turnModelControls: modelControls.snapshot,
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
          void history.refresh();
          if (agentId !== null) onRunEnd?.(agentId);
        }
      },
    }),
    [
      agentId,
      onRunEnd,
      onRunStart,
      onStateEvent,
      onStopped,
      modelControls.snapshot,
      modelControls.canSend,
      history.refresh,
      restoring,
    ]
  );
  const runtime = useLocalRuntime(chatModelAdapter, { adapters });
  const isRunning = useSyncExternalStore(
    runtime.thread.subscribe,
    () => runtime.thread.getState().isRunning,
    () => false
  );
  const selectHistory = async (id: number) => {
    if (runtime.thread.getState().isRunning || agentId == null) return;
    const generation = ++loadGeneration.current;
    setRestoring(true);
    try {
      const detail = await conversationService.getById(String(id));
      if (generation !== loadGeneration.current) return;
      if (
        detail.agent_system_key !== "nl2agent_main" ||
        detail.target?.type !== "agent" ||
        detail.target.id !== agentId
      ) {
        throw new Error("Creator history target mismatch");
      }
      const { RemoteConversationHistoryAdapter } =
        await import("../adapter/conversation-thread-list-adapter");
      if (generation !== loadGeneration.current) return;
      const saved = await new RemoteConversationHistoryAdapter(
        () => String(id),
        async () => ({ remoteId: String(id), externalId: String(id) }),
        async () => detail
      ).load();
      if (generation !== loadGeneration.current) return;
      await runtime.thread.composer.reset();
      if (generation !== loadGeneration.current) return;
      onConversationChange?.(agentId);
      runtime.thread.import(saved);
      historyRef.current.id = String(id);
      setSelectedId(String(id));
    } catch {
      if (generation === loadGeneration.current)
        message.error(t("nl2agent.history.restoreFailed"));
    } finally {
      if (generation === loadGeneration.current) setRestoring(false);
    }
  };
  const newConversation = async () => {
    if (runtime.thread.getState().isRunning || disabled || agentId == null)
      return;
    const generation = ++loadGeneration.current;
    setRestoring(true);
    try {
      await runtime.thread.composer.reset();
      if (generation !== loadGeneration.current) return;
      runtime.thread.reset();
      onConversationChange?.(agentId);
      historyRef.current.id = undefined;
      setSelectedId(undefined);
    } catch {
      if (generation === loadGeneration.current)
        message.error(t("nl2agent.history.newFailed"));
    } finally {
      if (generation === loadGeneration.current) setRestoring(false);
    }
  };

  useImperativeHandle(
    ref,
    () => ({
      cancelRun: () => runtime.thread.cancelRun(),
      sendPrompt: (prompt) => {
        if (
          disabled ||
          restoring ||
          agentId === null ||
          !prompt.trim() ||
          !modelControls.canSend ||
          runtime.thread.getState().isRunning
        )
          return;
        runtime.thread.append({
          role: "user",
          content: [{ type: "text", text: prompt.trim() }],
        });
      },
    }),
    [agentId, disabled, restoring, runtime, modelControls.canSend]
  );

  const assistantTitle = t("agentConfig.button.generationAssistant");
  const isOptimization = Boolean(agentDescription?.trim());
  const welcomeSuggestions = useMemo<readonly AgentSuggestionItem[]>(
    () =>
      showOptimizationSuggestions
        ? (isOptimization
            ? NL2AGENT_DEFAULT_SUGGESTIONS
            : AGENT_CREATION_EXAMPLES
          ).map((suggestion) => ({
            id: suggestion.id,
            title: t(suggestion.titleKey),
            description: t(suggestion.descriptionKey),
            prompt: t(suggestion.promptKey),
            icon: "icon" in suggestion ? suggestion.icon : undefined,
          }))
        : [],
    [showOptimizationSuggestions, isOptimization, t]
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
        <div
          className="flex h-full min-h-0 w-full flex-col"
          style={{
            background:
              "radial-gradient(ellipse at 0% 100%, #66ebff1a, transparent 48%), radial-gradient(ellipse at 100% 100%, #7a66ff12, transparent 48%), radial-gradient(ellipse at 80% 85%, #669fff0f, transparent 48%), #fff",
          }}
        >
          <CreatorHistoryToolbar
            history={history}
            selectedId={selectedId}
            disabled={agentId == null || disabled || isRunning}
            restoring={restoring}
            onSelect={selectHistory}
            onNew={newConversation}
          />
          <div className="min-h-0 flex-1 [&>div]:!bg-transparent">
            <Thread
              agent={nl2AgentDisplay}
              generatedTitle={assistantTitle}
              chatMode="execution"
              {...modelControls}
              modelSelectionScope="tenant"
              showModelSelector
              showConversationTitle={false}
              showAgentCreationResult={false}
              readOnly={disabled || restoring || !modelControls.canCreate}
              variant="embedded"
              welcomeContent={
                <AgentWelcome
                  title={t("nl2agent.configuration.title")}
                  greeting={t("nl2agent.configuration.description")}
                >
                  <CardSuggestion
                    disabled={disabled || !modelControls.canCreate || isRunning}
                    suggestions={welcomeSuggestions}
                    onSelect={(prompt) =>
                      runtime.thread.composer.setText(prompt)
                    }
                  />
                </AgentWelcome>
              }
            />
          </div>
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
});
