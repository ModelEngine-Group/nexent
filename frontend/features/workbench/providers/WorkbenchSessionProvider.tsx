// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useQueryClient } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";
import { createConversationDetailLoader } from "@/lib/conversationDetails";
import type { ConversationDetailLoader } from "@/types/conversation";
import {
  removeDeletedWorkbenchPins,
  workbenchPinsQueryKey,
} from "@/lib/workbenchPins";
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
import { createConversationThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { getWorkbenchPinStorageKey } from "@/app/newchat/assistant-ui/thread-pins";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
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
  conversationDetails: ConversationDetailLoader;
  runtime: AssistantRuntime;
  selectedAgent: Agent | null;
  isLoadingAgents: boolean;
  agents: Agent[];
  onRestoreAgent: (agent: Agent | null) => void;
  onBack: () => void;
  isDictationConfigured: boolean;
  workbenchState: WorkbenchState;
  workbenchBootstrap: WorkbenchBootstrap | null;
  isLoadingWorkbenchBootstrap: boolean;
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
  const { user } = useAuthorizationContext();
  const queryClient = useQueryClient();
  const identity = JSON.stringify([user?.tenantId, user?.id]);
  const conversationDetails = useMemo(
    () => createConversationDetailLoader(queryClient, identity),
    [queryClient, identity]
  );
  useConversationRouteGuard("workbench", conversationDetails.load);
  const detailLeases = useRef(new Map<ConversationDetailLoader, number>());
  useEffect(() => {
    const leases = detailLeases.current;
    leases.set(conversationDetails, (leases.get(conversationDetails) ?? 0) + 1);
    return () => {
      leases.set(
        conversationDetails,
        (leases.get(conversationDetails) ?? 1) - 1
      );
      // Strict Mode replays setup synchronously; do not discard its shared read.
      queueMicrotask(() => {
        if (leases.get(conversationDetails) === 0) {
          conversationDetails.clear();
          leases.delete(conversationDetails);
        }
      });
    };
  }, [conversationDetails]);
  const pinStorageKey = user
    ? getWorkbenchPinStorageKey(user.id, user.tenantId)
    : undefined;
  const threadListAdapter = useMemo(
    () =>
      createConversationThreadListAdapter(
        "workbench",
        pinStorageKey,
        () =>
          queryClient.ensureQueryData({
            queryKey: workbenchPinsQueryKey(pinStorageKey),
            queryFn: () => conversationService.getWorkbenchPins(),
          }),
        (conversationId) => {
          conversationDetails.invalidate(String(conversationId));
          return removeDeletedWorkbenchPins(queryClient, [conversationId]);
        },
        conversationDetails
      ),
    [pinStorageKey, queryClient, conversationDetails]
  );
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [workbenchState, dispatchWorkbench] = useReducer(
    workbenchReducer,
    initialWorkbenchState
  );
  const [workbenchBootstrap, setWorkbenchBootstrap] =
    useState<WorkbenchBootstrap | null>(null);
  const [isLoadingWorkbenchBootstrap, setIsLoadingWorkbenchBootstrap] =
    useState(true);
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
    conversationDetails.activate(threadId || undefined);
    setRequestedThreadId(threadId || undefined);
  }, [conversationDetails]);

  const handleThreadIdChange = useCallback(
    (threadId: string | undefined) => {
      conversationDetails.activate(threadId);
      setRequestedThreadId(threadId);
      const url = new URL(window.location.href);
      url.searchParams.delete("thread_id");
      url.searchParams.delete("conversation_id");
      if (threadId && /^[1-9]\d*$/.test(threadId)) {
        url.searchParams.set("conversation_id", threadId);
      }
      const nextUrl = `${url.pathname}${url.search}${url.hash}`;
      if (
        nextUrl !==
        `${window.location.pathname}${window.location.search}${window.location.hash}`
      ) {
        // Keep the current document and its per-thread composer state mounted.
        window.history.replaceState(window.history.state, "", nextUrl);
      }
    },
    [conversationDetails]
  );

  useEffect(() => {
    let cancelled = false;
    void fetchWorkbenchBootstrap()
      .then((bootstrap) => {
        if (!cancelled) setWorkbenchBootstrap(bootstrap);
      })
      .catch((error) => {
        log.error("[Home] Failed to load Workbench capabilities:", error);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingWorkbenchBootstrap(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runtime: AssistantRuntime = useRemoteThreadListRuntime({
    runtimeHook: function useWorkbenchRuntime() {
      return useLocalChatRuntime(dictationAdapter);
    },
    adapter: threadListAdapter,
    threadId: requestedThreadId,
    onThreadIdChange: handleThreadIdChange,
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
    conversationDetails,
    runtime,
    selectedAgent,
    isLoadingAgents,
    agents,
    onRestoreAgent: handleRestoreAgent,
    onBack: handleBack,
    workbenchState,
    workbenchBootstrap,
    isLoadingWorkbenchBootstrap,
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
