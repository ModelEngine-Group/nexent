"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
  type MutableRefObject,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type AssistantRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Select } from "antd";
import { useConfig } from "@/hooks/useConfig";
import { useAgentStore } from "@/stores/agentStore";
import { useModelList } from "@/hooks/model/useModelList";
import type { Agent } from "@/types/agentConfig";
import type { STTModelConfig } from "@/types/modelConfig";
import { compositeAttachmentAdapter } from "@/app/newchat/adapter/attachment-adapter";
import { ServerDictationAdapter } from "@/app/newchat/adapter/server-dictation-adapter";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { Composer, type ChatMode } from "@/app/newchat/assistant-ui/composer";
import { Thread } from "@/app/newchat/assistant-ui/thread";

const isDictationConfigured = (config: STTModelConfig | undefined): boolean => {
  if (!config?.modelName) return false;
  if (config.modelFactory === "volcengine") {
    return Boolean(config.modelAppid && config.accessToken);
  }
  return Boolean(config.apiConfig?.apiKey);
};

interface AgentDebugComparePanelProps {
  agentId?: number | null;
}

const toDebugAgent = (
  agentId: number,
  draft: ReturnType<typeof useAgentStore.getState>["editedAgent"]
): Agent | null => {
  if (!draft) return null;
  return { id: String(agentId), ...draft };
};

const createSideAdapter = (
  modelId: number,
  agentId: number,
  enablePlan: boolean
): ChatModelAdapter => ({
  run(options) {
    return remoteChatModelAdapter.run({
      ...options,
      runConfig: {
        ...options.runConfig,
        custom: {
          ...options.runConfig?.custom,
          runtimeMode: "agent-debug",
          agentId,
          modelId: String(modelId),
          enablePlan,
        },
      },
    });
  },
});

interface SideThreadProps {
  agent: Agent;
  modelId: number;
  availableModels: Array<{ id: number; displayName?: string; name: string }>;
  excludeModelId?: number | null;
  enablePlan: boolean;
  chatMode: ChatMode;
  isDictationConfigured: boolean;
  composerPortalTarget?: HTMLElement | null;
  rightRuntimeRef?: MutableRefObject<AssistantRuntime | null>;
  onChatModeChange: (mode: ChatMode) => void;
  onRuntimeReady: (runtime: AssistantRuntime, modelId: number) => void;
  onModelChange: (modelId: number) => void;
}

const SideThread: FC<SideThreadProps> = ({
  agent,
  modelId,
  availableModels,
  excludeModelId,
  enablePlan,
  chatMode,
  isDictationConfigured: dictationConfigured,
  composerPortalTarget,
  rightRuntimeRef,
  onChatModeChange,
  onRuntimeReady,
  onModelChange,
}) => {
  const { t } = useTranslation();
  const { modelConfig } = useConfig();
  const mirroredMessageIds = useRef(new Set<string>());

  const adapter = useMemo(
    () => createSideAdapter(modelId, Number(agent.id), enablePlan),
    [modelId, agent.id, enablePlan]
  );
  const runtime = useLocalRuntime(adapter, {
    adapters: {
      attachments: compositeAttachmentAdapter,
      dictation: new ServerDictationAdapter(() => modelConfig?.stt),
    },
  });

  useEffect(() => {
    runtime.thread.composer.setRunConfig({
      custom: {
        agentId: Number(agent.id),
        enablePlan,
        modelId: String(modelId),
      },
    });
  }, [agent.id, runtime, enablePlan, modelId]);

  useEffect(() => {
    onRuntimeReady(runtime, modelId);
  }, [modelId, onRuntimeReady, runtime]);

  useEffect(() => {
    if (!rightRuntimeRef) return;

    const mirrorLatestUserMessage = () => {
      const latestUserMessage = [...runtime.thread.getState().messages]
        .reverse()
        .find((message) => message.role === "user");
      if (!latestUserMessage || mirroredMessageIds.current.has(latestUserMessage.id)) {
        return;
      }

      mirroredMessageIds.current.add(latestUserMessage.id);
      const rightRuntime = rightRuntimeRef.current;
      if (!rightRuntime) return;

      rightRuntime.thread.append({
        role: "user",
        content: latestUserMessage.content,
        attachments: latestUserMessage.attachments,
        runConfig: rightRuntime.thread.composer.getState().runConfig,
        startRun: true,
      });
    };

    for (const message of runtime.thread.getState().messages) {
      if (message.role === "user") mirroredMessageIds.current.add(message.id);
    }
    return runtime.thread.subscribe(mirrorLatestUserMessage);
  }, [rightRuntimeRef, runtime]);

  const filteredModels = useMemo(
    () =>
      availableModels.filter((model) => model.id !== excludeModelId),
    [availableModels, excludeModelId]
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="flex h-full w-full flex-col">
          <div className="shrink-0 border-b border-gray-100 bg-gray-50 px-4 py-2">
            <Select
              value={modelId}
              onChange={onModelChange}
              options={filteredModels.map((model) => ({
                value: model.id,
                label: model.displayName || model.name,
              }))}
              placeholder={t("agent.debug.compareSelectModel", "Select model")}
              size="small"
              className="w-full"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            <Thread
            agent={agent}
            chatMode={chatMode}
            onChatModeChange={onChatModeChange}
            showModelSelector={false}
            showConversationTitle={false}
            isDictationConfigured={dictationConfigured}
            variant="embedded"
            showComposer={false}
          />
          {composerPortalTarget &&
            createPortal(
              <Composer
                models={[]}
                chatMode={chatMode}
                onChatModeChange={onChatModeChange}
                showModelSelector={false}
                isDictationConfigured={dictationConfigured}
              />,
              composerPortalTarget
            )}
          </div>
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};

export const AgentDebugComparePanel: FC<AgentDebugComparePanelProps> = ({
  agentId,
}) => {
  const { t } = useTranslation();
  const { modelConfig } = useConfig();
  const { editedAgent } = useAgentStore();
  const { availableLlmModels } = useModelList();
  const [compareLeftModelId, setCompareLeftModelId] = useState<number | null>(null);
  const [compareRightModelId, setCompareRightModelId] = useState<number | null>(null);
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const [composerPortalTarget, setComposerPortalTarget] = useState<HTMLElement | null>(null);
  const rightRuntimeRef = useRef<AssistantRuntime | null>(null);

  const debugAgent = useMemo(
    () => (agentId != null && editedAgent ? toDebugAgent(agentId, editedAgent) : null),
    [agentId, editedAgent]
  );
  const debugModelIds = useMemo<number[]>(() => {
    if (agentId != null && editedAgent?.model_ids) {
      return editedAgent.model_ids.filter((id: number) =>
        availableLlmModels.some((model) => model.id === id)
      );
    }
    return [];
  }, [agentId, editedAgent, availableLlmModels]);

  useEffect(() => {
    if (debugModelIds.length >= 2) {
      setCompareLeftModelId(debugModelIds[0]);
      setCompareRightModelId(
        availableLlmModels.find((model) => model.id !== debugModelIds[0])?.id ??
          debugModelIds[1]
      );
    } else if (debugModelIds.length === 1) {
      setCompareLeftModelId(debugModelIds[0]);
      setCompareRightModelId(
        availableLlmModels.find((model) => model.id !== debugModelIds[0])?.id ?? null
      );
    } else if (availableLlmModels.length >= 2) {
      setCompareLeftModelId(availableLlmModels[0].id);
      setCompareRightModelId(availableLlmModels[1].id);
    }
  }, [availableLlmModels, debugModelIds]);

  const handleRightRuntimeReady = useCallback(
    (runtime: AssistantRuntime, modelId: number) => {
      if (modelId === compareRightModelId) rightRuntimeRef.current = runtime;
    },
    [compareRightModelId]
  );
  const handleLeftRuntimeReady = useCallback(() => {}, []);

  if (!debugAgent) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("systemPrompt.nonEditing.subtitle")}
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="flex min-h-0 flex-1 flex-col border-r border-gray-200">
            {compareLeftModelId != null && (
              <SideThread
                agent={debugAgent}
                modelId={compareLeftModelId}
                availableModels={availableLlmModels}
                excludeModelId={compareRightModelId}
                enablePlan={chatMode === "planning"}
                chatMode={chatMode}
                isDictationConfigured={isDictationConfigured(modelConfig?.stt)}
                composerPortalTarget={composerPortalTarget}
                rightRuntimeRef={rightRuntimeRef}
                onChatModeChange={setChatMode}
                onRuntimeReady={handleLeftRuntimeReady}
                onModelChange={setCompareLeftModelId}
              />
            )}
          </div>
          <div className="flex min-h-0 flex-1 flex-col">
            {compareRightModelId != null && (
              <SideThread
                agent={debugAgent}
                modelId={compareRightModelId}
                availableModels={availableLlmModels}
                excludeModelId={compareLeftModelId}
                enablePlan={chatMode === "planning"}
                chatMode={chatMode}
                isDictationConfigured={isDictationConfigured(modelConfig?.stt)}
                onChatModeChange={setChatMode}
                onRuntimeReady={handleRightRuntimeReady}
                onModelChange={setCompareRightModelId}
              />
            )}
          </div>
        </div>
        <div
          ref={setComposerPortalTarget}
          className="shrink-0 border-t border-gray-200 bg-white px-4 pb-4 pt-3"
        />
      </div>
    </div>
  );
};
