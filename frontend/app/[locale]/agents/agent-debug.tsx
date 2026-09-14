"use client";

import { useCallback, useEffect, useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { NexusAgent, type NexusRunConfig } from "@/lib/assistant-ui/nexus-agent";

import { TooltipProvider } from "@/components/ui/tooltip";
import { useConfig } from "@/hooks/useConfig";
import { useAgentStore, type AgentDraft } from "@/stores/agentStore";
import type { Agent } from "@/types/agentConfig";
import type { STTModelConfig } from "@/types/modelConfig";
import { compositeAttachmentAdapter } from "../newchat/adapter/attachment-adapter";
import { ServerDictationAdapter } from "../newchat/adapter/server-dictation-adapter";
import { getAuthHeaders } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import { Chat } from "../newchat/assistant-ui/chat";
import type { ChatMode } from "../newchat/assistant-ui/composer";
import { AgentDebugComparePanel } from "./components/agentInfo/AgentDebugComparePanel";

interface AgentDebugPanelProps {
  isCompareMode?: boolean;
}

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
  const [runConfig, setRunConfig] = useState<NexusRunConfig>({
    agent_id: agentId,
    is_debug: true,
    enable_plan: false,
  });

  // ---- NexusAgent: memoized once per agentId/mode/modelId -----------------
  const nexusAgent = useMemo(
    () =>
      new NexusAgent({
        url: API_ENDPOINTS.agent.run,
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
          "x-agui-format": "true",
        },
      }),
    // New agent instance when agentId changes — AG-UI agents are single-use per thread
    [agentId]
  );

  const adapters = useMemo(
    () => ({
      attachments: compositeAttachmentAdapter,
      dictation: new ServerDictationAdapter(() => modelConfig?.stt),
    }),
    [modelConfig?.stt]
  );

  // ---- useAgUiRuntime ------------------------------------------------------
  // The NexusRunConfig (agent_id, enable_plan, model_id, etc.) travels through
  // the composer's runConfig.custom, which NexusAgent picks up via forwardedProps
  // in requestInit().
  const runtime = useAgUiRuntime({
    agent: nexusAgent,
    adapters,
    showThinking: true,
    onError: (e) => console.error("AG-UI runtime error:", e),
  });

  const handleChatModeChange = useCallback((mode: ChatMode) => {
    setChatMode(mode);
  }, []);

  // Sync runConfig with AG-UI runtime's forwardedProps
  useEffect(() => {
    setRunConfig({
      agent_id: agentId,
      is_debug: true,
      enable_plan: chatMode === "planning",
      model_id: selectedModelId ? Number(selectedModelId) : undefined,
    });
  }, [agentId, chatMode, selectedModelId]);

  // Sync runConfig changes to the NexusAgent instance — this is what gets
  // sent to the backend as AgentRequest fields when the user sends a message.
  useEffect(() => {
    nexusAgent.setRunConfig(runConfig);
  }, [nexusAgent, runConfig]);

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

  return (
    <div className="h-full w-full">
      <div className={isCompareMode ? "hidden h-full w-full" : "h-full w-full"}>
        <AgentDebugChat agent={debugAgent} agentId={agentId} />
      </div>
      <div className={isCompareMode ? "h-full w-full" : "hidden h-full w-full"}>
        <AgentDebugComparePanel agentId={agentId} />
      </div>
    </div>
  );
};

export default AgentDebugPanel;
