"use client";

import { useCallback, useEffect, useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { useConfig } from "@/hooks/useConfig";
import { useAgentStore, type AgentDraft } from "@/stores/agentStore";
import type { Agent } from "@/types/agentConfig";
import type { STTModelConfig } from "@/types/modelConfig";
import { compositeAttachmentAdapter } from "../newchat/adapter/attachment-adapter";
import { ServerDictationAdapter } from "../newchat/adapter/server-dictation-adapter";
import { remoteChatModelAdapter } from "../newchat/adapter/remote-chat-model-adapter";
import { Chat } from "../newchat/assistant-ui/chat";
import type { ChatMode } from "../newchat/assistant-ui/composer";
import { AgentDebugComparePanel } from "./components/agentInfo/AgentDebugComparePanel";

interface AgentDebugPanelProps {
  isCompareMode?: boolean;
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
}

const AgentDebugChat: FC<AgentDebugChatProps> = ({ agent, agentId }) => {
  const { modelConfig } = useConfig();
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const [selectedModelId, setSelectedModelId] = useState<string | undefined>(undefined);
  const adapters = useMemo(
    () => ({
      attachments: compositeAttachmentAdapter,
      dictation: new ServerDictationAdapter(() => modelConfig?.stt),
    }),
    [modelConfig?.stt]
  );
  const runtime = useLocalRuntime(agentDebugChatModelAdapter, { adapters });

  const handleChatModeChange = useCallback((mode: ChatMode) => {
    setChatMode(mode);
  }, []);

  useEffect(() => {
    runtime.thread.composer.setRunConfig({
      custom: {
        agentId,
        enablePlan: chatMode === "planning",
        modelId: selectedModelId,
      },
    });
  }, [agentId, runtime, chatMode, selectedModelId]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-full w-full">
          <Chat
            selectedAgent={agent}
            isLoadingAgents={false}
            chatMode={chatMode}
            onChatModeChange={handleChatModeChange}
            showModelSelector={true}
            showConversationTitle={false}
            isDictationConfigured={isDictationConfigured(modelConfig?.stt)}
            variant="default"
          />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};

const AgentDebugPanel: FC<AgentDebugPanelProps> = ({ isCompareMode = false }) => {
  const { t } = useTranslation("common");
  const agentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const debugAgent = useMemo(
    () => (agentId !== null && editedAgent ? toDebugAgent(agentId, editedAgent) : null),
    [agentId, editedAgent]
  );

  if (!debugAgent || agentId === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("systemPrompt.nonEditing.subtitle")}
      </div>
    );
  }

  if (isCompareMode) {
    return (
      <div className="h-full w-full">
        <AgentDebugComparePanel agentId={agentId} />
      </div>
    );
  }

  return <AgentDebugChat agent={debugAgent} agentId={agentId} />;
};

export default AgentDebugPanel;
