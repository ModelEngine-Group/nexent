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
import type { Agent } from "@/types/agentConfig";
import log from "@/lib/logger";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useConfig } from "@/hooks/useConfig";
import { ServerDictationAdapter } from "./adapter/server-dictation-adapter";
import type { STTModelConfig } from "@/types/modelConfig";
import { conversationService } from "@/services/conversationService";
import { useTranslation } from "react-i18next";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
  KnowledgeScopeResolution,
  KnowledgeScopeWarning,
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
  const { t } = useTranslation();
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const [knowledgeScope, setKnowledgeScope] =
    useState<ConversationKnowledgeScope | null>(null);
  const [knowledgePreview, setKnowledgePreview] =
    useState<KnowledgeScopeEffectivePreview | null>(null);
  const [knowledgeCapabilities, setKnowledgeCapabilities] =
    useState<KnowledgeCapabilities | null>(null);
  const [runtimeMetadata, setRuntimeMetadata] = useState<
    Record<string, unknown>
  >({});
  const [runtimeMetadataVersion, setRuntimeMetadataVersion] = useState(0);
  const [runtimeMetadataDirty, setRuntimeMetadataDirty] = useState(false);
  const resumedConversationIdsRef = useRef(new Set<number>());
  const knowledgeScopesRef = useRef<
    Map<string, ConversationKnowledgeScope | null>
  >(new Map());
  const knowledgePreviewsRef = useRef<
    Map<string, KnowledgeScopeEffectivePreview | null>
  >(new Map());

  // All hooks must be called before any early returns
  const runtimeMainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const isLoading = useAuiState((s) => s.threads.isLoading);
  const isThreadLoading = useAuiState((s) => s.thread.isLoading);
  const isThreadRunning = useAuiState((s) => s.thread.isRunning);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  const ready =
    runtimeMainThreadId !== undefined && !isLoading && !isThreadLoading;

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

  const handleGenerationStopped = useCallback((conversationId: number) => {
    // A user-initiated stop transitions assistant-ui to idle before the
    // backend has persisted the terminal message. Do not mistake that short
    // window for a disconnected stream and replay its existing chunks.
    resumedConversationIdsRef.current.add(conversationId);
  }, []);

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
    const versionNo = selectedAgent.current_version_no;
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
      setKnowledgePreview(null);
      return;
    }

    if (knowledgeScopesRef.current.has(activeThreadId)) {
      setKnowledgeScope(knowledgeScopesRef.current.get(activeThreadId) ?? null);
      setKnowledgePreview(
        knowledgePreviewsRef.current.get(activeThreadId) ?? null
      );
      return;
    }

    const numericConversationId = Number(activeConversationId);
    if (
      !Number.isInteger(numericConversationId) ||
      numericConversationId <= 0
    ) {
      knowledgeScopesRef.current.set(activeThreadId, null);
      knowledgePreviewsRef.current.set(activeThreadId, null);
      setKnowledgeScope(null);
      setKnowledgePreview(null);
      return;
    }

    let cancelled = false;
    setKnowledgeScope(null);
    setKnowledgePreview(null);
    void conversationService
      .getById(String(numericConversationId))
      .then((conversation) => {
        if (cancelled) return;
        const restoredScope = conversation.knowledge_scope ?? null;
        knowledgeScopesRef.current.set(activeThreadId, restoredScope);
        knowledgePreviewsRef.current.set(activeThreadId, null);
        setKnowledgeScope(restoredScope);
        setKnowledgePreview(null);
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

  useEffect(() => {
    const numericConversationId = Number(activeConversationId);
    setRuntimeMetadata({});
    setRuntimeMetadataVersion(0);
    setRuntimeMetadataDirty(false);
    if (
      !Number.isInteger(numericConversationId) ||
      numericConversationId <= 0
    ) {
      return;
    }

    let cancelled = false;
    void conversationService
      .getById(String(numericConversationId))
      .then((conversation) => {
        if (cancelled) return;
        setRuntimeMetadata(conversation.runtime_metadata ?? {});
        setRuntimeMetadataVersion(conversation.runtime_metadata_version ?? 0);
      })
      .catch((error) => {
        if (!cancelled) {
          log.error("[HomeContent] Failed to restore runtime metadata:", error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeConversationId]);

  const handleRuntimeMetadataChange = useCallback(
    (value: Record<string, unknown>) => {
      setRuntimeMetadata(value);
      setRuntimeMetadataDirty(true);
    },
    []
  );

  const handleRuntimeMetadataSent = useCallback((version?: number) => {
    setRuntimeMetadataDirty(false);
    if (version !== undefined) {
      setRuntimeMetadataVersion(version);
    } else {
      setRuntimeMetadataVersion((currentVersion) => currentVersion + 1);
    }
  }, []);

  const showKnowledgeScopeWarnings = useCallback(
    (warnings: KnowledgeScopeWarning[]) => {
      warnings.forEach((warning) => {
        const source =
          warning.source === "local"
            ? t("chat.knowledgeScope.localTab")
            : warning.source === "aidp"
              ? t("chat.knowledgeScope.aidpTab")
              : t("chat.knowledgeScope.title");
        if (warning.code === "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE") {
          message.warning(
            t("chat.knowledgeScope.itemUnavailableWarning", {
              source,
              count: warning.count,
            })
          );
          return;
        }
        if (warning.code === "KNOWLEDGE_SCOPE_CAPABILITY_UNSUPPORTED") {
          message.warning(
            t("chat.knowledgeScope.capabilityUnsupportedWarning", { source })
          );
          return;
        }
        message.warning(t("chat.knowledgeScope.partialWarning"));
      });
    },
    [t]
  );

  const handleKnowledgeScopeChange = useCallback(
    async (
      scope: ConversationKnowledgeScope | null,
      preview?: KnowledgeScopeEffectivePreview | null
    ) => {
      const numericConversationId = Number(activeConversationId);
      let nextPreview = preview ?? null;
      try {
        if (
          Number.isInteger(numericConversationId) &&
          numericConversationId > 0
        ) {
          const result = await conversationService.updateKnowledgeScope(
            numericConversationId,
            scope
          );
          nextPreview = result.effective_preview;
          showKnowledgeScopeWarnings(result.warnings);
        }
        if (activeThreadId) {
          knowledgeScopesRef.current.set(activeThreadId, scope);
          knowledgePreviewsRef.current.set(activeThreadId, nextPreview);
        }
        setKnowledgeScope(scope);
        setKnowledgePreview(nextPreview);
      } catch (error) {
        log.error("[HomeContent] Failed to update knowledge scope:", error);
        message.error(t("chat.knowledgeScope.saveFailed"));
        throw error;
      }
    },
    [activeConversationId, activeThreadId, showKnowledgeScopeWarnings, t]
  );

  const handleKnowledgeScopeResolved = useCallback(
    (resolution: KnowledgeScopeResolution) => {
      if (activeThreadId) {
        knowledgePreviewsRef.current.set(activeThreadId, resolution.effective);
      }
      setKnowledgePreview(resolution.effective);
      showKnowledgeScopeWarnings(resolution.warnings);
    },
    [activeThreadId, showKnowledgeScopeWarnings]
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
        ...(selectedAgent?.current_version_no
          ? {
              agentVersionNo: selectedAgent.current_version_no,
            }
          : {}),
        ...(activeConversationId ? { threadId: activeConversationId } : {}),
        ...(knowledgeScope ? { knowledgeScope } : {}),
        ...(runtimeMetadataDirty ? { runtimeMetadata } : {}),
        ...(runtimeMetadataDirty && Number(activeConversationId) > 0
          ? { runtimeMetadataVersion }
          : {}),
        onRuntimeMetadataSent: handleRuntimeMetadataSent,
        onKnowledgeScopeResolved: handleKnowledgeScopeResolved,
        onGenerationStopped: handleGenerationStopped,
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
    runtimeMetadata,
    runtimeMetadataDirty,
    runtimeMetadataVersion,
    handleRuntimeMetadataSent,
    handleKnowledgeScopeResolved,
    handleGenerationStopped,
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

  // A route change tears down the local stream, while the backend keeps the
  // conversation marked as streaming. Reconnect the assistant-ui runtime when
  // the historical load reports that state.
  useEffect(() => {
    const numericConversationId = Number(activeConversationId);
    if (
      !ready ||
      isThreadRunning ||
      !activeThreadId ||
      !Number.isInteger(numericConversationId) ||
      numericConversationId <= 0 ||
      resumedConversationIdsRef.current.has(numericConversationId)
    ) {
      return;
    }

    let cancelled = false;
    void conversationService
      .getById(String(numericConversationId))
      .then((conversation) => {
        if (
          cancelled ||
          conversation.streaming_message?.status !== "streaming" ||
          resumedConversationIdsRef.current.has(numericConversationId)
        ) {
          return;
        }

        resumedConversationIdsRef.current.add(numericConversationId);
        const messages = runtime.thread.getState().messages;
        const parentId = messages.at(-1)?.id ?? null;
        runtime.thread.resumeRun({
          parentId,
          sourceId: null,
          runConfig: {
            custom: {
              threadId: String(numericConversationId),
              ...(selectedAgent?.id ? { agentId: selectedAgent.id } : {}),
              ...(selectedAgent?.current_version_no
                ? { agentVersionNo: selectedAgent.current_version_no }
                : {}),
              onGenerationStopped: handleGenerationStopped,
              enablePlan: chatMode === "planning",
              resume: true,
            },
          },
          stream: async function* (options) {
            const resumedRun = remoteChatModelAdapter.run(options);
            if (Symbol.asyncIterator in resumedRun) {
              yield* resumedRun;
            } else {
              yield await resumedRun;
            }
          },
        });
      })
      .catch((error) => {
        if (!cancelled) {
          resumedConversationIdsRef.current.delete(numericConversationId);
          log.error(
            `[HomeContent] Failed to resume conversation ${numericConversationId}:`,
            error
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeConversationId,
    activeThreadId,
    chatMode,
    isThreadRunning,
    ready,
    runtime,
    selectedAgent,
    handleGenerationStopped,
  ]);

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

  const handlePrepareNewConversation = useCallback(() => {
    // Do not restore the agent from the thread that is being left.
    shouldRestoreAgentRef.current = false;
    onBack();
  }, [onBack]);

  const handleNewConversation = useCallback(async () => {
    handlePrepareNewConversation();
    await runtime.threads.switchToNewThread();
  }, [handlePrepareNewConversation, runtime]);

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
          <ThreadListSidebar
            generatedTitles={generatedTitles}
            onPrepareNewConversation={handlePrepareNewConversation}
            onNewConversation={handleNewConversation}
          />
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
          knowledgePreview={knowledgePreview}
          knowledgeCapabilities={knowledgeCapabilities}
          onKnowledgeScopeChange={handleKnowledgeScopeChange}
          runtimeMetadata={runtimeMetadata}
          onRuntimeMetadataChange={handleRuntimeMetadataChange}
        />
      </div>
    </div>
  );
};
