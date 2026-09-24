"use client";

import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
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
import { workbenchConversationThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { createNewChatAttachmentAdapter } from "@/app/newchat/adapter/attachment-adapter";
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
import { fetchWorkbenchBootstrap } from "../api";
import type { WorkbenchBootstrap } from "../types";
import { useConversationRouteGuard } from "../hooks/useConversationRouteGuard";

export type WorkbenchSession = {
  runtime: AssistantRuntime;
  selectedAgent: Agent | null;
  isLoadingAgents: boolean;
  agents: Agent[];
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
  const attachmentAdapter = useMemo(() => createNewChatAttachmentAdapter(), []);

  return useLocalRuntime(remoteChatModelAdapter, {
    adapters: {
      attachments: attachmentAdapter,
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
  useConversationRouteGuard("workbench");
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
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
    adapter: workbenchConversationThreadListAdapter,
    threadId: requestedThreadId,
  });

  const { isLoading: isLoadingAgents, agents } = usePublishedAgentList();

  const handleWorkbenchModeChange = useCallback(
    (mode: "agent_create" | "skill_create" | "generic_chat") => {
      setSelectedAgent(null);
      dispatchWorkbench({ type: "select-mode", mode });
    },
    []
  );

  const handleBack = useCallback(() => {
    setSelectedAgent(null);
    dispatchWorkbench({ type: "select-mode", mode: "generic_chat" });
    log.log(`[Home] Back to agent list`);
  }, []);

  const handleRestoreAgent = useCallback((agent: Agent | null) => {
    setSelectedAgent(agent);
  }, []);

  const value: WorkbenchSession = {
    runtime,
    selectedAgent,
    isLoadingAgents,
    agents,
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
