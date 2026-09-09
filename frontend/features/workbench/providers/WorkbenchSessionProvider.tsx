"use client";

import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
} from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type AssistantRuntime,
} from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { conversationThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { compositeAttachmentAdapter } from "@/app/newchat/adapter/attachment-adapter";
import { ServerDictationAdapter } from "@/app/newchat/adapter/server-dictation-adapter";
import { TooltipProvider } from "@/components/ui/tooltip";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useConfig } from "@/hooks/useConfig";
import type { STTModelConfig } from "@/types/modelConfig";
import type { Agent } from "@/types/agentConfig";
import log from "@/lib/logger";
import {
  initialWorkbenchState,
  workbenchReducer,
  type WorkbenchState,
} from "../state";
import { fetchWorkbenchBootstrap, previewWorkbenchAgent } from "../api";
import type { WorkbenchBootstrap } from "../types";

export type WorkbenchSession = {
  runtime: AssistantRuntime;
  selectedAgent: Agent | null;
  isLoadingAgents: boolean;
  agents: Agent[];
  onAgentSelected: (agent: Agent) => Promise<void>;
  onRestoreAgent: (agent: Agent | null) => void;
  onBack: () => void;
  isDictationConfigured: boolean;
  workbenchState: WorkbenchState;
  workbenchBootstrap: WorkbenchBootstrap | null;
  onWorkbenchModeChange: (
    mode: "agent_create" | "skill_create" | "generic_chat"
  ) => void;
  dispatchWorkbench: Dispatch<import("@/features/workbench").WorkbenchAction>;
};

const SessionContext = createContext<WorkbenchSession | null>(null);

export function useWorkbenchSession(): WorkbenchSession {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Workbench session provider is missing");
  return session;
}

function useLocalChatRuntime(
  dictationAdapter: ServerDictationAdapter
): AssistantRuntime {
  return useLocalRuntime(remoteChatModelAdapter, {
    adapters: {
      attachments: compositeAttachmentAdapter,
      dictation: dictationAdapter,
    },
  });
}

const isDictationConfigured = (config: STTModelConfig | undefined): boolean => {
  if (!config?.modelName) return false;
  if (config.modelFactory === "volcengine") {
    return Boolean(config.modelAppid && config.accessToken);
  }
  return Boolean(config.apiConfig?.apiKey);
};

export function WorkbenchSessionProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const selectionRequest = useRef(0);
  const [workbenchState, dispatchWorkbench] = useReducer(
    workbenchReducer,
    initialWorkbenchState
  );
  const [workbenchBootstrap, setWorkbenchBootstrap] =
    useState<WorkbenchBootstrap | null>(null);
  const [requestedThreadId, setRequestedThreadId] = useState<
    string | undefined
  >(undefined);
  const { modelConfig } = useConfig();
  const dictationAdapter = useMemo(
    () => new ServerDictationAdapter(() => modelConfig?.stt),
    [modelConfig?.stt]
  );

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search);
    const threadId =
      searchParams.get("thread_id") ?? searchParams.get("conversation_id");
    setRequestedThreadId(threadId || undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchWorkbenchBootstrap()
      .then((bootstrap) => {
        if (!cancelled) setWorkbenchBootstrap(bootstrap);
      })
      .catch((error) => {
        log.error("[Home] Failed to load Workbench capabilities:", error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runtime: AssistantRuntime = useRemoteThreadListRuntime({
    runtimeHook: function useWorkbenchRuntime() {
      return useLocalChatRuntime(dictationAdapter);
    },
    adapter: conversationThreadListAdapter,
    threadId: requestedThreadId,
  });

  const { isLoading: isLoadingAgents, agents } = usePublishedAgentList();

  const handleAgentSelected = useCallback(
    async (agent: Agent) => {
      const requestId = ++selectionRequest.current;
      const threadId = runtime.threads.getState().mainThreadId;
      const agentId = Number(
        (agent as Agent & { agent_id?: number }).agent_id ?? agent.id
      );
      dispatchWorkbench({ type: "resolve-agent-start", agentId });
      try {
        const preview = await previewWorkbenchAgent(
          agentId,
          agent.current_version_no
        );
        if (
          requestId !== selectionRequest.current ||
          runtime.threads.getState().mainThreadId !== threadId
        )
          return;
        dispatchWorkbench({
          type: "resolve-agent-success",
          preview,
          modelIds: agent.model_ids ?? [],
          append: workbenchBootstrap?.modes.multi_agent_chat.enabled === true,
        });
        setSelectedAgent(agent);
        log.log(`[Home] Agent selected: ${agent.display_name || agent.name}`);
      } catch (error) {
        if (
          requestId !== selectionRequest.current ||
          runtime.threads.getState().mainThreadId !== threadId
        )
          return;
        const text = error instanceof Error ? error.message : "智能体不可用";
        dispatchWorkbench({ type: "resolve-agent-error", message: text });
        throw error;
      }
    },
    [workbenchBootstrap, runtime]
  );

  const handleWorkbenchModeChange = useCallback(
    (mode: "agent_create" | "skill_create" | "generic_chat") => {
      selectionRequest.current += 1;
      setSelectedAgent(null);
      dispatchWorkbench({ type: "select-mode", mode });
    },
    []
  );

  const handleBack = useCallback(() => {
    selectionRequest.current += 1;
    setSelectedAgent(null);
    dispatchWorkbench({ type: "select-mode", mode: "generic_chat" });
    log.log(`[Home] Back to agent list`);
  }, []);

  const handleRestoreAgent = useCallback((agent: Agent | null) => {
    selectionRequest.current += 1;
    setSelectedAgent(agent);
  }, []);

  const value: WorkbenchSession = {
    runtime,
    selectedAgent,
    isLoadingAgents,
    agents,
    onAgentSelected: handleAgentSelected,
    onRestoreAgent: handleRestoreAgent,
    onBack: handleBack,
    workbenchState,
    workbenchBootstrap,
    onWorkbenchModeChange: handleWorkbenchModeChange,
    dispatchWorkbench,
    isDictationConfigured: isDictationConfigured(modelConfig?.stt),
  };
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <SessionContext.Provider value={value}>
        <TooltipProvider>{children}</TooltipProvider>
      </SessionContext.Provider>
    </AssistantRuntimeProvider>
  );
}
