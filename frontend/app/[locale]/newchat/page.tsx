// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  ComposerAttachment,
  ComposerDictation,
} from "@/app/newchat/assistant-ui/composer-tools";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
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
import toolbarStyles from "@/components/common/ConversationToolbar.module.css";
import { useRecentAgentIds } from "./assistant-ui/use-recent-agent-ids";
import {
  cacheHistoricalChatMode,
  createConversationThreadListAdapter,
  generateConversationTitle,
  restoreHistoricalChatMode,
  restoreHistoricalPlan,
  setHistoricalChatModeListener,
  setServerConversationIdState,
} from "./adapter/conversation-thread-list-adapter";
import {
  recordThreadActivity,
  startAgentConversation,
} from "./adapter/thread-agent-registry";
import { applyComposerRunConfig } from "./adapter/composer-run-config";
import { remoteChatModelAdapter } from "./adapter/remote-chat-model-adapter";
import { createNewChatAttachmentAdapter } from "./adapter/attachment-adapter";
import {
  clearLastChatView,
  readLastChatViewState,
  writeLastChatViewAgent,
  writeLastChatViewConversation,
  type LastChatViewState,
} from "./last-chat-view";
import { ConversationSidebarProvider } from "@/components/common/ConversationSidebarProvider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import {
  ConversationModelControlsProvider,
  useBindConversationModelThread,
} from "@/features/model-controls/ConversationModelControlsProvider";
import { ConversationLoadingBoundary } from "./components/ConversationLoadingBoundary";
import { message } from "antd";
import type { Agent } from "@/types/agentConfig";
import log from "@/lib/logger";
import { ConversationTitleGuard } from "@/lib/conversationTitle";
import { resolveAgentDeepLinkAction } from "@/lib/agentUsageGuide";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { useComposerKnowledgeBases } from "@/hooks/chat/useComposerResources";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useConfig } from "@/hooks/useConfig";
import { ServerDictationAdapter } from "./adapter/server-dictation-adapter";
import type { STTModelConfig } from "@/types/modelConfig";
import { conversationService } from "@/services/conversationService";
import { useQueryClient } from "@tanstack/react-query";
import { getWorkbenchPinStorageKey } from "./assistant-ui/thread-pins";
import {
  removeDeletedWorkbenchPins,
  workbenchPinsQueryKey,
} from "@/lib/workbenchPins";
import { useTranslation } from "react-i18next";
import { useConversationRouteGuard } from "@/features/workbench/hooks/useConversationRouteGuard";
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

export default function Home() {
  return <PersistentChatHome />;
}

const PersistentChatHome: FC = () => {
  const { user } = useAuthorizationContext();
  useConversationRouteGuard("agent_chat");
  const queryClient = useQueryClient();
  const pinScope = user
    ? getWorkbenchPinStorageKey(user.id, user.tenantId)
    : undefined;
  const threadListAdapter = useMemo(
    () =>
      createConversationThreadListAdapter(
        "agent_chat",
        pinScope,
        () =>
          queryClient.ensureQueryData({
            queryKey: workbenchPinsQueryKey(pinScope),
            queryFn: () => conversationService.getWorkbenchPins(),
          }),
        (id) => removeDeletedWorkbenchPins(queryClient, [id])
      ),
    [pinScope, queryClient]
  );
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [requestedThreadId, setRequestedThreadId] = useState<
    string | undefined
  >(undefined);
  const [deepLinkedAgentId, setDeepLinkedAgentId] = useState<number | null>(
    null
  );
  const consumedDeepLinkRef = useRef(false);
  // Read once at mount: what (if anything) should this refresh restore? Deep
  // links win, so this is null whenever the URL carries linking parameters.
  const [lastChatView] = useState<LastChatViewState | null>(
    readLastChatViewState
  );
  const didRestoreLastAgentRef = useRef(false);
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
    const agentId = searchParams.get("agent_id");
    setDeepLinkedAgentId(
      agentId && Number.isInteger(Number(agentId)) && Number(agentId) > 0
        ? Number(agentId)
        : null
    );
  }, []);

  const runtime: AssistantRuntime = useRemoteThreadListRuntime({
    runtimeHook: function useChatRuntime() {
      return useLocalChatRuntime(dictationAdapter);
    },
    adapter: threadListAdapter,
    threadId: requestedThreadId,
    // Return to the conversation the user was viewing before the refresh.
    // The runtime switches to it once the adapter is ready; when the stored
    // conversation no longer exists the switch fails silently and the page
    // shows the default landing view.
    initialThreadId: lastChatView?.conversationId,
  });

  const { isLoading: isLoadingAgents, agents } = usePublishedAgentList();

  const handleAgentSelected = useCallback(
    async (agent: Agent) => {
      // Reflect the selection before awaiting the runtime thread switch so a
      // deep-linked Agent opens its chat right away instead of waiting for the
      // thread list runtime to settle.
      setSelectedAgent(agent);
      log.log(`[Home] Agent selected: ${agent.display_name || agent.name}`);
      try {
        await startAgentConversation(runtime, Number(agent.id));
      } catch (error) {
        log.error("[Home] Failed to switch to a new agent thread:", error);
      }
    },
    [runtime]
  );

  useEffect(() => {
    const action = resolveAgentDeepLinkAction({
      agentId: deepLinkedAgentId,
      agents,
      consumed: consumedDeepLinkRef.current,
      isLoading: isLoadingAgents,
      getAgentId: (agent) => Number((agent as { agent_id?: number }).agent_id),
    });
    if (action.action === "wait") return;
    if (deepLinkedAgentId != null) {
      consumedDeepLinkRef.current = true;
    }
    if (action.action === "select") {
      handleAgentSelected(action.agent);
    }
  }, [agents, deepLinkedAgentId, handleAgentSelected, isLoadingAgents]);

  // A refresh in a brand-new conversation has no server-side conversation to
  // restore; bring back a blank conversation of the same agent instead so the
  // composer state (selected agent) survives the reload.
  useEffect(() => {
    if (didRestoreLastAgentRef.current || isLoadingAgents) return;
    didRestoreLastAgentRef.current = true;
    // A saved conversation owns the restore; its metadata selects the agent.
    if (!lastChatView || lastChatView.conversationId) return;
    const agent = agents.find(
      (candidate) => Number(candidate.id) === Number(lastChatView.agentId)
    );
    if (agent) {
      void handleAgentSelected(agent);
    }
  }, [agents, isLoadingAgents, handleAgentSelected, lastChatView]);

  const handleBack = useCallback(() => {
    setSelectedAgent(null);
    log.log(`[Home] Back to agent list`);
  }, []);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <ConversationModelControlsProvider
          key={JSON.stringify([user?.tenantId, user?.id])}
        >
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
        </ConversationModelControlsProvider>
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
  onAgentSelected: (agent: Agent) => Promise<void>;
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
  const bindModelThread = useBindConversationModelThread();
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const [knowledgeScope, setKnowledgeScope] =
    useState<ConversationKnowledgeScope | null>(null);
  const [knowledgePreview, setKnowledgePreview] =
    useState<KnowledgeScopeEffectivePreview | null>(null);
  const { enableAidpKnowledge } = useDeployment();
  // Observe the composer's catalog updates without starting another list request.
  const { dataUpdatedAt: knowledgeCatalogUpdatedAt } =
    useComposerKnowledgeBases(false, enableAidpKnowledge);
  const knowledgeCapabilityKey = JSON.stringify([
    selectedAgent?.id,
    selectedAgent?.current_version_no,
    enableAidpKnowledge,
    knowledgeCatalogUpdatedAt,
  ]);
  const [knowledgeCapabilityState, setKnowledgeCapabilityState] = useState<{
    key: string;
    value: KnowledgeCapabilities | null;
  }>({ key: knowledgeCapabilityKey, value: null });
  if (knowledgeCapabilityState.key !== knowledgeCapabilityKey) {
    setKnowledgeCapabilityState({ key: knowledgeCapabilityKey, value: null });
  }
  const knowledgeCapabilities =
    knowledgeCapabilityState?.key === knowledgeCapabilityKey
      ? knowledgeCapabilityState.value
      : null;
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
  // Skip resync during saves and discard reads started before a newer read or save.
  const knowledgeScopeSavingRef = useRef(false);
  const knowledgeScopeSyncRevisionRef = useRef(0);

  // All hooks must be called before any early returns
  const runtimeMainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const isThreadLoading = useAuiState((s) => s.thread.isLoading);
  const isThreadRunning = useAuiState((s) => s.thread.isRunning);
  useEffect(() => {
    if (isThreadRunning && runtimeMainThreadId) {
      recordThreadActivity(runtimeMainThreadId);
    }
  }, [isThreadRunning, runtimeMainThreadId]);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  // Sidebar metadata reloads must not unmount the active chat and composer.
  const ready = runtimeMainThreadId !== undefined && !isThreadLoading;

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
  const titleGuard = useRef(new ConversationTitleGuard());
  const [generatedTitles, setGeneratedTitles] = useState<Map<string, string>>(
    new Map()
  );
  const [serverConversationIds, setServerConversationIds] = useState<
    Map<string, string>
  >(new Map());

  const handleServerConversationId = useCallback(
    (threadId: string, serverId: string, initialQuestion?: string) => {
      const map = serverConversationIdsRef.current;
      const previous = map.get(threadId);
      const numericId = String(Number(serverId));
      if (previous !== numericId) {
        // The existing callback marks new runs even when the query is empty.
        // Historical runs already use a server key and must not be rebound.
        if (initialQuestion !== undefined) {
          bindModelThread?.(threadId, numericId);
        }
        map.set(threadId, numericId);
        cacheHistoricalChatMode(numericId, chatMode);
        // Keep the sidebar and run configuration in sync with the server id.
        setServerConversationIds(new Map(map));
      }

      if (initialQuestion && previous !== numericId) {
        const revision = titleGuard.current.capture(threadId);
        void generateConversationTitle(numericId, initialQuestion)
          .then((title) => {
            setGeneratedTitles((titles) => {
              if (!titleGuard.current.isCurrent(threadId, revision))
                return titles;
              const next = new Map(titles);
              next.set(threadId, title);
              next.set(numericId, title);
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
    [chatMode, bindModelThread]
  );

  const handleConversationRenamed = useCallback(
    (threadId: string, remoteId: string | undefined, title: string) => {
      titleGuard.current.renamed(threadId);
      setGeneratedTitles((titles) => {
        const next = new Map(titles);
        next.set(threadId, title);
        if (remoteId) next.set(remoteId, title);
        return next;
      });
    },
    []
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
      return;
    }

    let cancelled = false;
    const versionNo = selectedAgent.current_version_no;
    void conversationService
      .getKnowledgeCapabilities(Number(selectedAgent.id), versionNo)
      .then((capabilities) => {
        if (!cancelled) {
          const matches =
            capabilities?.agent_id === Number(selectedAgent.id) &&
            (versionNo === undefined || capabilities.version_no === versionNo);
          setKnowledgeCapabilityState({
            key: knowledgeCapabilityKey,
            value: matches ? capabilities : null,
          });
        }
      })
      .catch((error) => {
        if (!cancelled)
          setKnowledgeCapabilityState({
            key: knowledgeCapabilityKey,
            value: null,
          });
        log.error(
          "[HomeContent] Failed to load knowledge capabilities:",
          error
        );
      });

    return () => {
      cancelled = true;
    };
  }, [selectedAgent, knowledgeCapabilityKey]);

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

  // Resync the conversation's saved knowledge selection whenever the page
  // becomes visible again. Deletion cascades on the server, so a knowledge
  // base removed from another page or browser is already gone from the stored
  // scope; this read makes it disappear from the composer without a refresh.
  useEffect(() => {
    let cancelled = false;
    const resyncKnowledgeScope = () => {
      if (document.visibilityState !== "visible") return;
      if (knowledgeScopeSavingRef.current) return;
      const numericConversationId = Number(activeConversationId);
      if (
        !Number.isInteger(numericConversationId) ||
        numericConversationId <= 0
      ) {
        return;
      }
      const revision = ++knowledgeScopeSyncRevisionRef.current;
      void conversationService
        .getById(String(numericConversationId))
        .then((conversation) => {
          if (
            cancelled ||
            knowledgeScopeSavingRef.current ||
            revision !== knowledgeScopeSyncRevisionRef.current
          ) {
            return;
          }
          const serverScope = conversation.knowledge_scope ?? null;
          if (activeThreadId) {
            knowledgeScopesRef.current.set(activeThreadId, serverScope);
            knowledgePreviewsRef.current.set(activeThreadId, null);
          }
          setKnowledgeScope(serverScope);
          setKnowledgePreview(null);
        })
        .catch((error) => {
          log.warn("[HomeContent] Failed to resync knowledge scope:", error);
        });
    };
    document.addEventListener("visibilitychange", resyncKnowledgeScope);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", resyncKnowledgeScope);
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
      knowledgeScopeSyncRevisionRef.current += 1;
      knowledgeScopeSavingRef.current = true;
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
      } finally {
        knowledgeScopeSavingRef.current = false;
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

  // Whether the user has entered any view during this page load. The agent
  // selection is transiently empty while the saved view is still being
  // restored at startup; clearing the marker in that window would lose the
  // restore target if the user refreshed again before initialization
  // finished.
  const viewEstablishedRef = useRef(false);

  // Keep the "return here after a refresh" marker in sync with what the user
  // is actually viewing: a saved conversation (restorable by id), the agent
  // of an unsent blank conversation, or nothing on the landing page.
  useEffect(() => {
    if (!selectedAgent) {
      // Only clear after a view was established in this page load.
      if (viewEstablishedRef.current) {
        clearLastChatView();
      }
      return;
    }
    viewEstablishedRef.current = true;
    const numericConversationId = Number(activeConversationId);
    if (Number.isInteger(numericConversationId) && numericConversationId > 0) {
      writeLastChatViewConversation(String(numericConversationId));
      return;
    }
    // No server-side conversation yet: remember the agent so the refresh can
    // reopen a blank conversation with the same selection.
    writeLastChatViewAgent(String(selectedAgent.id));
  }, [selectedAgent, activeConversationId]);

  // Leaving the chat route via navigation (e.g. to the agent workbench)
  // ends the "return here" session the marker tracks: returning through
  // the menu then starts on the agent landing page again. A browser
  // refresh never runs this cleanup because the document is destroyed
  // without unmounting, so only a refresh keeps the marker and restores
  // the previous view.
  useEffect(() => {
    return () => clearLastChatView();
  }, []);

  // Sync selected agent and active thread into composer's runConfig so the
  // ChatModelAdapter can forward both agent_id and conversation_id reliably.
  // `onServerConversationId` lets the adapter report back the server-issued
  // conversation_id returned in the response header, which we then reuse as
  // `threadId` for future runs in the same thread.
  useEffect(() => {
    applyComposerRunConfig(runtime, activeThreadId, {
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

  const handleThreadBack = useCallback(async () => {
    shouldRestoreAgentRef.current = false;
    try {
      await runtime.threads.switchToNewThread();
      await runtime.threads.reload();
    } catch (error) {
      log.error("[HomeContent] Failed to return to agent list:", error);
    } finally {
      onBack();
    }
  }, [onBack, runtime]);

  const handlePrepareNewConversation = useCallback(() => {
    // Do not restore the agent from the thread that is being left.
    shouldRestoreAgentRef.current = false;
    onBack();
  }, [onBack]);

  const recentAgentIds = useRecentAgentIds();
  const { availableMainAgents } = usePublishedAgentList();

  const handleNewConversation = useCallback(async () => {
    shouldRestoreAgentRef.current = false;
    try {
      if (!selectedAgent) {
        // On the landing there is no active conversation: enter a blank
        // conversation of the agent the top-bar selector displays (the most
        // recently used one).
        const lastUsed = recentAgentIds
          .map((id) =>
            availableMainAgents.find((agent) => Number(agent.id) === id)
          )
          .find((agent) => agent !== undefined);
        if (lastUsed) {
          setSelectedAgent(lastUsed);
        }
      }
      await runtime.threads.switchToNewThread();
      await runtime.threads.reload();
    } catch (error) {
      log.error("[HomeContent] Failed to start a new conversation:", error);
    }
  }, [
    runtime,
    selectedAgent,
    recentAgentIds,
    availableMainAgents,
    setSelectedAgent,
  ]);

  const handleHistoryAgentSelected = useCallback(
    (agentId: number) => {
      shouldRestoreAgentRef.current = true;
      const agent = agents.find(
        (candidate) => Number(candidate.id) === agentId
      );
      if (agent) setSelectedAgent(agent);
    },
    [agents, setSelectedAgent]
  );

  const handleAgentSelectedFromLanding = useCallback(
    async (agent: Agent) => {
      shouldRestoreAgentRef.current = true;
      await onAgentSelected(agent);
    },
    [onAgentSelected]
  );

  const handleAgentSwitched = useCallback(
    async (agent: Agent) => {
      try {
        shouldRestoreAgentRef.current = true;
        await startAgentConversation(runtime, Number(agent.id));
        setSelectedAgent(agent);
      } catch (error) {
        log.error("[HomeContent] Failed to switch agent conversation:", error);
        message.error(t("chatInterface.errorFetchingConversationDetailsError"));
      }
    },
    [runtime, setSelectedAgent, t]
  );

  return (
    <div
      data-agent-chat-page
      className={`relative flex w-full h-full [&:has([data-floating-sidebar-trigger])_[data-agent-landing-title]]:pl-10 [&:has([data-agent-landing-title])_[data-floating-sidebar-trigger]]:top-[22px] ${toolbarStyles.page}`}
    >
      <div className="shrink-0 h-full">
        <ConversationSidebarProvider className="w-auto h-full">
          <ThreadListSidebar
            onHistoryAgentSelected={handleHistoryAgentSelected}
            collapseToFloatingButton
            newChatDesign
            activeThreadId={selectedAgent ? runtimeMainThreadId : undefined}
            generatedTitles={generatedTitles}
            serverConversationIds={serverConversationIds}
            onRenameSuccess={handleConversationRenamed}
            onPrepareNewConversation={handlePrepareNewConversation}
            onNewConversation={handleNewConversation}
            selectedAgent={selectedAgent}
            onAgentSelected={handleAgentSwitched}
          />
        </ConversationSidebarProvider>
      </div>

      <div className="flex min-h-0 flex-1 min-w-0 flex-col">
        <ConversationLoadingBoundary loading={!ready}>
          <Chat
            readOnly={!ready}
            newChatDesign
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
            composerTools={
              <>
                <ComposerAttachment />
                <ComposerDictation configured={isDictationConfigured} />
              </>
            }
            knowledgeScope={knowledgeScope}
            knowledgePreview={knowledgePreview}
            knowledgeCapabilities={knowledgeCapabilities}
            onKnowledgeScopeChange={handleKnowledgeScopeChange}
            runtimeMetadata={runtimeMetadata}
            onRuntimeMetadataChange={handleRuntimeMetadataChange}
          />
        </ConversationLoadingBoundary>
      </div>
    </div>
  );
};
