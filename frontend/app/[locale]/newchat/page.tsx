"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
  type ReactNode,
} from "react";
import {
  AssistantRuntimeProvider,
  useAuiState,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type AssistantRuntime,
} from "@assistant-ui/react";
import { Chat } from "./assistant-ui/chat";
import type { ChatMode } from "./assistant-ui/composer";
import { ThreadListSidebar } from "./assistant-ui/threadlist-sidebar";
import {
  cacheHistoricalChatMode,
  conversationThreadListAdapter,
  generateConversationTitle,
  restoreHistoricalChatMode,
  restoreHistoricalPlan,
  setHistoricalChatModeListener,
  setServerConversationIdState,
} from "./adapter/conversation-thread-list-adapter";
import { remoteChatModelAdapter } from "./adapter/remote-chat-model-adapter";
import { compositeAttachmentAdapter } from "./adapter/attachment-adapter";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Layout, message } from "antd";
import type { Agent, PublishedAgent } from "@/types/agentConfig";
import log from "@/lib/logger";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useConfig } from "@/hooks/useConfig";
import { ServerDictationAdapter } from "./adapter/server-dictation-adapter";
import type { STTModelConfig } from "@/types/modelConfig";
import { conversationService } from "@/services/conversationService";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
} from "@/types/knowledgeScope";

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

export default function Home() {
  return <PersistentChatHome />;
}

const PersistentChatHome: FC = () => {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
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

  const runtime: AssistantRuntime = useRemoteThreadListRuntime({
    runtimeHook: () => useLocalChatRuntime(dictationAdapter),
    adapter: conversationThreadListAdapter,
    threadId: requestedThreadId,
  });

  const { isLoading: isLoadingAgents, agents } = usePublishedAgentList();

  const handleAgentSelected = useCallback((agent: Agent) => {
    setSelectedAgent(agent);
    log.log(`[Home] Agent selected: ${agent.display_name || agent.name}`);
  }, []);

  const handleBack = useCallback(() => {
    setSelectedAgent(null);
    log.log(`[Home] Back to agent list`);
  }, []);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <HomeContent
          runtime={runtime}
          selectedAgent={selectedAgent}
          setSelectedAgent={setSelectedAgent}
          isLoadingAgents={isLoadingAgents}
          agents={agents}
          onAgentSelected={handleAgentSelected}
          onBack={handleBack}
          isDictationConfigured={isDictationConfigured(modelConfig?.stt)}
        />
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};

/**
 * Inner component that has access to the AuiState via useAuiState hook.
 * Must be rendered inside AssistantRuntimeProvider.
 */
const HomeContent: FC<{
  runtime: AssistantRuntime;
  selectedAgent: Agent | null;
  setSelectedAgent: (agent: Agent | null) => void;
  isLoadingAgents: boolean;
  agents: Agent[];
  onAgentSelected: (agent: Agent) => void;
  onBack: () => void;
  isDictationConfigured: boolean;
}> = ({
  runtime,
  selectedAgent,
  setSelectedAgent,
  isLoadingAgents,
  agents,
  onAgentSelected,
  onBack,
  isDictationConfigured,
}) => {
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const [knowledgeScope, setKnowledgeScope] =
    useState<ConversationKnowledgeScope | null>(null);
  const [knowledgeCapabilities, setKnowledgeCapabilities] =
    useState<KnowledgeCapabilities | null>(null);
  const knowledgeScopesRef = useRef<
    Map<string, ConversationKnowledgeScope | null>
  >(new Map());

  // All hooks must be called before any early returns
  const runtimeMainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const isLoading = useAuiState((s) => s.threads.isLoading);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  const ready = runtimeMainThreadId !== undefined && !isLoading;

  // Maintain thread ID state to pass conversation_id to the adapter reliably
  const [activeThreadId, setActiveThreadId] = useState<string | undefined>(
    runtimeMainThreadId
  );

  // Update local state when the runtime's active thread changes
  useEffect(() => {
    setActiveThreadId(runtimeMainThreadId);
  }, [runtimeMainThreadId]);

  // Server-side conversation IDs, keyed by assistant-ui thread id.
  //
  // When the user sends the first message in a new thread, the remote-chat
  // adapter makes a `POST /api/agent/run` request without `conversation_id`.
  // The backend auto-creates the conversation and returns the new id via the
  // `conversation_id` response header. The adapter forwards that id here, and
  // we cache it so that:
  //   1. Subsequent messages in the same thread send `conversation_id` and
  //      reuse the existing conversation instead of creating a new one.
  //   2. Switching back and forth between threads keeps each thread bound to
  //      its own server-side conversation.
  const serverConversationIdsRef = useRef<Map<string, string>>(new Map());
  const [generatedTitles, setGeneratedTitles] = useState<Map<string, string>>(
    new Map()
  );
  const [, forceServerIdTick] = useState(0);

  const handleServerConversationId = useCallback(
    (threadId: string, serverId: string, initialQuestion?: string) => {
      const map = serverConversationIdsRef.current;
      const previous = map.get(threadId);
      const numericId = String(Number(serverId));
      if (previous !== numericId) {
        map.set(threadId, numericId);
        cacheHistoricalChatMode(numericId, chatMode);
        // Trigger a re-render so the `setRunConfig` effect below picks up the
        // new id. We don't store the map in state because we never need to
        // diff/render it directly — only react when an entry changes.
        forceServerIdTick((tick) => tick + 1);
      }

      if (initialQuestion && previous !== numericId) {
        void generateConversationTitle(numericId, initialQuestion)
          .then((title) => {
            setGeneratedTitles((titles) => {
              const next = new Map(titles);
              next.set(threadId, title);
              return next;
            });
          })
          .catch((error) => {
            log.error(
              `[HomeContent] Failed to generate title for ${numericId}:`,
              error
            );
          });
      }
    },
    [chatMode]
  );

  const activeThread = (
    threadItems as ReadonlyArray<{
      id: string;
      remoteId?: string;
      custom?: { agentId?: number | string };
    }>
  ).find(
    (item) => item.id === activeThreadId || item.remoteId === activeThreadId
  );
  const activeAgentId = activeThread?.custom?.agentId;
  const serverConversationIdForActiveThread = activeThreadId
    ? serverConversationIdsRef.current.get(activeThreadId)
    : undefined;
  // Prefer the server-issued id (set after the backend auto-creates the
  // conversation), then fall back to the thread's `remoteId` (used when the
  // user opens an existing conversation from the sidebar), then finally the
  // local assistant-ui thread id as a temporary placeholder.
  const activeConversationId =
    serverConversationIdForActiveThread ??
    activeThread?.remoteId ??
    activeThreadId;

  useEffect(() => {
    if (!selectedAgent?.id) {
      setKnowledgeCapabilities(null);
      return;
    }

    let cancelled = false;
    const versionNo = (selectedAgent as unknown as PublishedAgent)
      .current_version_no;
    void conversationService
      .getKnowledgeCapabilities(Number(selectedAgent.id), versionNo)
      .then((capabilities) => {
        if (!cancelled) setKnowledgeCapabilities(capabilities);
      })
      .catch((error) => {
        if (!cancelled) setKnowledgeCapabilities(null);
        log.error(
          "[HomeContent] Failed to load knowledge capabilities:",
          error
        );
      });

    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  useEffect(() => {
    if (!activeThreadId) {
      setKnowledgeScope(null);
      return;
    }

    if (knowledgeScopesRef.current.has(activeThreadId)) {
      setKnowledgeScope(knowledgeScopesRef.current.get(activeThreadId) ?? null);
      return;
    }

    const numericConversationId = Number(activeConversationId);
    if (
      !Number.isInteger(numericConversationId) ||
      numericConversationId <= 0
    ) {
      knowledgeScopesRef.current.set(activeThreadId, null);
      setKnowledgeScope(null);
      return;
    }

    let cancelled = false;
    setKnowledgeScope(null);
    void conversationService
      .getById(String(numericConversationId))
      .then((conversation) => {
        if (cancelled) return;
        const restoredScope = conversation.knowledge_scope ?? null;
        knowledgeScopesRef.current.set(activeThreadId, restoredScope);
        setKnowledgeScope(restoredScope);
      })
      .catch((error) => {
        if (!cancelled) {
          log.error("[HomeContent] Failed to restore knowledge scope:", error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeConversationId, activeThreadId]);

  const handleKnowledgeScopeChange = useCallback(
    async (scope: ConversationKnowledgeScope | null) => {
      const numericConversationId = Number(activeConversationId);
      try {
        if (
          Number.isInteger(numericConversationId) &&
          numericConversationId > 0
        ) {
          await conversationService.updateKnowledgeScope(
            numericConversationId,
            scope
          );
        }
        if (activeThreadId) {
          knowledgeScopesRef.current.set(activeThreadId, scope);
        }
        setKnowledgeScope(scope);
      } catch (error) {
        log.error("[HomeContent] Failed to update knowledge scope:", error);
        message.error("知识库配置保存失败");
        throw error;
      }
    },
    [activeConversationId, activeThreadId]
  );

  const handleChatModeChange = useCallback((mode: ChatMode) => {
    setChatMode(mode);
  }, []);

  const shouldRestoreAgentRef = useRef(true);
  const previousActiveThreadIdRef = useRef(activeThreadId);

  useEffect(() => {
    if (
      previousActiveThreadIdRef.current !== activeThreadId &&
      activeThreadId
    ) {
      shouldRestoreAgentRef.current = true;
    }
    previousActiveThreadIdRef.current = activeThreadId;
  }, [activeThreadId]);

  // Resolve the selected conversation's agent from thread metadata.
  useEffect(() => {
    if (
      !shouldRestoreAgentRef.current ||
      !activeThreadId ||
      agents.length === 0
    )
      return;

    const agentId = activeAgentId;
    if (agentId === undefined || agentId === null) return;

    const matchedAgent = agents.find((agent) => agent.id === String(agentId));
    if (matchedAgent && matchedAgent.id !== selectedAgent?.id) {
      log.log(
        `[HomeContent] Thread changed to ${activeThreadId}, updating selectedAgent to: ${matchedAgent.display_name || matchedAgent.name}`
      );
      setSelectedAgent(matchedAgent);
    }
  }, [
    activeThreadId,
    activeAgentId,
    agents,
    selectedAgent?.id,
    setSelectedAgent,
  ]);

  // Sync selected agent and active thread into composer's runConfig so the
  // ChatModelAdapter can forward both agent_id and conversation_id reliably.
  // `onServerConversationId` lets the adapter report back the server-issued
  // conversation_id returned in the response header, which we then reuse as
  // `threadId` for future runs in the same thread.
  useEffect(() => {
    runtime.thread.composer.setRunConfig({
      custom: {
        ...(selectedAgent?.id ? { agentId: selectedAgent.id } : {}),
        ...(activeConversationId ? { threadId: activeConversationId } : {}),
        ...(knowledgeScope ? { knowledgeScope } : {}),
        enablePlan: chatMode === "planning",
        ...(activeThreadId
          ? {
              onServerConversationId: (
                serverId: string,
                initialQuestion?: string
              ) =>
                handleServerConversationId(
                  activeThreadId,
                  serverId,
                  initialQuestion
                ),
            }
          : {}),
      },
    });
  }, [
    runtime,
    selectedAgent,
    activeConversationId,
    activeThreadId,
    chatMode,
    knowledgeScope,
    handleServerConversationId,
  ]);

  // Restore historical plan and chat mode from the same conversation detail
  // response that the history adapter uses to load messages.
  useEffect(() => {
    setHistoricalChatModeListener((mode) => {
      setChatMode(mode);
    });
    return () => setHistoricalChatModeListener(undefined);
  }, [activeThreadId]);

  useEffect(() => {
    const conversationId = activeConversationId
      ? String(activeConversationId)
      : undefined;
    restoreHistoricalPlan(conversationId);

    restoreHistoricalChatMode(conversationId);
  }, [activeConversationId, activeThreadId]);

  // Publish the server conversation id registry to the thread-list adapter so
  // `generateTitle` can wait for the real backend id before issuing its
  // request. Without this, a brand-new thread would forward an empty-string
  // `remoteId` (placeholder from `initialize()`), which `Number("")` coerces
  // to `0`, and the backend's `rename_conversation(0, ...)` would silently
  // no-op via `WHERE conversation_id = 0`.
  useEffect(() => {
    setServerConversationIdState({
      idsRef: serverConversationIdsRef,
      getActiveThreadId: () => activeThreadId,
    });
    return () => setServerConversationIdState(null);
  }, [serverConversationIdsRef, activeThreadId]);

  const handleThreadBack = useCallback(() => {
    shouldRestoreAgentRef.current = false;
    onBack();
  }, [onBack]);

  const handleAgentSelectedFromLanding = useCallback(
    async (agent: Agent) => {
      shouldRestoreAgentRef.current = true;
      await runtime.threads.switchToNewThread();
      onAgentSelected(agent);
    },
    [runtime, onAgentSelected]
  );

  // Conditional rendering must happen after all hooks
  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading conversation…
      </div>
    );
  }

  return (
    <div className="flex w-full h-full">
      <div className="shrink-0 h-full">
        <SidebarProvider className="w-auto h-full">
          <ThreadListSidebar generatedTitles={generatedTitles} />
        </SidebarProvider>
      </div>

      <div className="flex-1 min-w-0">
        <Chat
          generatedTitle={
            activeThreadId ? generatedTitles.get(activeThreadId) : undefined
          }
          conversationId={
            activeConversationId && Number(activeConversationId) > 0
              ? Number(activeConversationId)
              : undefined
          }
          isLoadingAgents={isLoadingAgents}
          selectedAgent={selectedAgent}
          onAgentSelected={handleAgentSelectedFromLanding}
          onBack={handleThreadBack}
          chatMode={chatMode}
          onChatModeChange={handleChatModeChange}
          isDictationConfigured={isDictationConfigured}
          knowledgeScope={knowledgeScope}
          knowledgeCapabilities={knowledgeCapabilities}
          onKnowledgeScopeChange={handleKnowledgeScopeChange}
        />
      </div>
    </div>
  );
};
