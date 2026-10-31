// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  ComposerAttachment,
  ComposerDictation,
} from "@/app/newchat/assistant-ui/composer-tools";
import { useEffect, useMemo, useState, type FC } from "react";
import { Button, Tooltip } from "antd";
import { Columns2, Maximize2, Minimize2, SquarePen, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useAui,
  useAuiState,
  type ChatModelAdapter,
} from "@assistant-ui/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { useConfig } from "@/hooks/useConfig";
import { useAgentStore, type AgentDraft } from "@/stores/agentStore";
import type { Agent } from "@/types/agentConfig";
import type { STTModelConfig } from "@/types/modelConfig";
import { compositeAttachmentAdapter } from "../../../../newchat/adapter/attachment-adapter";
import { ServerDictationAdapter } from "../../../../newchat/adapter/server-dictation-adapter";
import { remoteChatModelAdapter } from "../../../../newchat/adapter/remote-chat-model-adapter";
import { Thread } from "../../../../newchat/assistant-ui/thread";
import type { ChatMode } from "../../../../newchat/assistant-ui/composer";
import { AgentDebugComparePanel } from "./compare-panel";
import { AgentDebugWelcome } from "./agent-debug-welcome";
import "./agent-debug.css";

interface AgentDebugPanelProps {
  isCompareMode?: boolean;
  isFullscreen?: boolean;
  onCompareModeChange?: (value: boolean) => void;
  onToggleFullscreen?: () => void;
  onClose?: () => void;
}

const agentDebugChatModelAdapter: ChatModelAdapter = {
  run(options) {
    return remoteChatModelAdapter.run({
      ...options,
      runConfig: {
        custom: {
          ...options.runConfig?.custom,
          runtimeMode: "agent-debug",
        },
      },
    });
  },
};

const toDebugAgent = (agentId: number, draft: AgentDraft): Agent => ({
  id: String(agentId),
  ...draft,
});

const isDictationConfigured = (config: STTModelConfig | undefined): boolean => {
  if (!config?.modelName) return false;
  if (config.modelFactory === "volcengine") {
    return Boolean(config.modelAppid && config.accessToken);
  }
  return Boolean(config.apiConfig?.apiKey);
};

interface AgentDebugChatProps {
  agent: Agent;
  agentId: number;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  clearEpoch: number;
}

function DebugConversation({
  agent,
  chatMode,
  onChatModeChange,
  selectedModelId,
  onModelChange,
  dictationConfigured,
}: {
  agent: Agent;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  selectedModelId?: string;
  onModelChange: (id: string) => void;
  dictationConfigured: boolean;
}) {
  const aui = useAui();
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const { t } = useTranslation("common");
  return (
    <Thread
      agent={agent}
      chatMode={chatMode}
      onChatModeChange={onChatModeChange}
      selectedModelId={selectedModelId}
      onModelChange={onModelChange}
      showModelSelector
      showConversationTitle={false}
      debugLayout
      composerTools={
        <>
          <ComposerAttachment />
          <ComposerDictation configured={dictationConfigured} />
        </>
      }
      welcomeContent={
        <AgentDebugWelcome
          agent={agent}
          disabled={isRunning}
          onSelectQuestion={(question) => aui.composer().setText(question)}
        />
      }
      footerContent={
        <p className="agent-debug-disclaimer">{t("agent.debug.disclaimer")}</p>
      }
    />
  );
}

const AgentDebugChat: FC<AgentDebugChatProps> = ({
  agent,
  agentId,
  chatMode,
  onChatModeChange,
  clearEpoch,
}) => {
  const { modelConfig } = useConfig();
  const [selectedModelId, setSelectedModelId] = useState<string | undefined>(
    agent.model_ids?.[0]?.toString()
  );
  const effectiveModelId = agent.model_ids?.includes(Number(selectedModelId))
    ? selectedModelId
    : agent.model_ids?.[0]?.toString();
  const adapters = useMemo(
    () => ({
      attachments: compositeAttachmentAdapter,
      dictation: new ServerDictationAdapter(() => modelConfig?.stt),
    }),
    [modelConfig?.stt]
  );
  const runtime = useLocalRuntime(agentDebugChatModelAdapter, { adapters });

  useEffect(() => {
    if (clearEpoch === 0) return;
    runtime.thread.cancelRun();
    runtime.thread.reset();
  }, [clearEpoch, runtime]);

  useEffect(() => {
    runtime.thread.composer.setRunConfig({
      custom: {
        agentId,
        enablePlan: chatMode === "planning",
        modelId: effectiveModelId,
      },
    });
  }, [agentId, runtime, chatMode, effectiveModelId]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-full w-full">
          <DebugConversation
            agent={agent}
            chatMode={chatMode}
            onChatModeChange={onChatModeChange}
            selectedModelId={effectiveModelId}
            onModelChange={setSelectedModelId}
            dictationConfigured={isDictationConfigured(modelConfig?.stt)}
          />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};

const AgentDebugPanel: FC<AgentDebugPanelProps> = ({
  isCompareMode = false,
  isFullscreen = false,
  onCompareModeChange,
  onToggleFullscreen,
  onClose,
}) => {
  const { t } = useTranslation("common");
  const agentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const [clearEpoch, setClearEpoch] = useState(0);
  const [compareClearEpoch, setCompareClearEpoch] = useState(0);
  const debugAgent = useMemo(
    () =>
      agentId !== null && editedAgent
        ? toDebugAgent(agentId, editedAgent)
        : null,
    [agentId, editedAgent]
  );

  if (!debugAgent || agentId === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("systemPrompt.nonEditing.subtitle")}
      </div>
    );
  }

  return (
    <section
      className="agent-debug-panel"
      data-testid="agent-debug-panel"
      aria-label={t("agent.debug.title")}
    >
      <header className="agent-debug-header">
        <div className="flex min-w-0 items-center gap-4">
          <span
            className="agent-debug-header-title"
            title={debugAgent.display_name || debugAgent.name}
          >
            {debugAgent.display_name || debugAgent.name}
          </span>
          <Tooltip title={t("agent.debug.toggleCompareMode")}>
            <Button
              type="text"
              aria-label={t("agent.debug.toggleCompareMode")}
              aria-pressed={isCompareMode}
              icon={<Columns2 size={24} />}
              className="!size-6 shrink-0 !p-0 !text-[#4d4d4d]"
              onClick={() => onCompareModeChange?.(!isCompareMode)}
            />
          </Tooltip>
        </div>
        <div className="agent-debug-header-actions">
          <Tooltip title={t("agent.debug.clear")}>
            <Button
              type="text"
              aria-label={t("agent.debug.clear")}
              icon={<SquarePen size={24} />}
              className="!size-6 !p-0 !text-[#4d4d4d]"
              onClick={() =>
                isCompareMode
                  ? setCompareClearEpoch((value) => value + 1)
                  : setClearEpoch((value) => value + 1)
              }
            />
          </Tooltip>
          <Tooltip
            title={t(
              isFullscreen ? "agent.debug.restore" : "agent.debug.maximize"
            )}
          >
            <Button
              type="text"
              aria-label={t(
                isFullscreen ? "agent.debug.restore" : "agent.debug.maximize"
              )}
              icon={
                isFullscreen ? <Minimize2 size={24} /> : <Maximize2 size={24} />
              }
              className="!size-6 !p-0 !text-[#4d4d4d]"
              onClick={onToggleFullscreen}
            />
          </Tooltip>
          <Tooltip title={t("agent.page.panel.debug.closeAria")}>
            <Button
              type="text"
              aria-label={t("agent.page.panel.debug.closeAria")}
              icon={<X size={24} />}
              className="!size-6 !p-0 !text-[#4d4d4d]"
              onClick={onClose}
            />
          </Tooltip>
        </div>
      </header>
      <div className="min-h-0 flex-1">
        <div
          className={isCompareMode ? "hidden h-full w-full" : "h-full w-full"}
        >
          <AgentDebugChat
            agent={debugAgent}
            agentId={agentId}
            chatMode={chatMode}
            onChatModeChange={setChatMode}
            clearEpoch={clearEpoch}
          />
        </div>
        <div
          className={isCompareMode ? "h-full w-full" : "hidden h-full w-full"}
        >
          <AgentDebugComparePanel
            clearEpoch={compareClearEpoch}
            agentId={agentId}
            chatMode={chatMode}
            onChatModeChange={setChatMode}
          />
        </div>
      </div>
    </section>
  );
};

export default AgentDebugPanel;
