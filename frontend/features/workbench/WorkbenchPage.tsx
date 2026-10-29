// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  ComposerAttachment,
  ComposerDictation,
} from "@/app/newchat/assistant-ui/composer-tools";
import { restoreKnowledgeDisplay } from "./knowledgeDisplay";

import {
  useCallback,
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FC,
} from "react";
import { useAuiState } from "@assistant-ui/react";
import { Chat } from "@/app/newchat/assistant-ui/chat";
import type {
  Nl2AgentStateEvent,
  Nl2SkillStreamEvent,
} from "@/app/newchat/adapter/remote-chat-model-adapter";
import type { ChatMode } from "@/app/newchat/assistant-ui/composer";
import { ThreadListSidebar } from "@/app/newchat/assistant-ui/threadlist-sidebar";
import { getWorkbenchPinStorageKey } from "@/app/newchat/assistant-ui/thread-pins";
import {
  cacheHistoricalChatMode,
  generateConversationTitle,
  restoreHistoricalChatMode,
  restoreHistoricalPlan,
  setHistoricalChatModeListener,
  setServerConversationIdState,
} from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { applyComposerRunConfig } from "@/app/newchat/adapter/composer-run-config";
import { useConversationResume } from "./hooks/useConversationResume";
import { useConversationScopedState } from "./hooks/useConversationScopedState";
import { WorkbenchConversationLayout } from "./components/WorkbenchConversationLayout";
import { message } from "antd";
import type { Agent } from "@/types/agentConfig";
import { useModelList } from "@/hooks/model/useModelList";
import { WorkbenchLoadingBoundary } from "./components/WorkbenchLoadingBoundary";
import log from "@/lib/logger";
import { ConversationTitleGuard } from "@/lib/conversationTitle";
import { conversationService } from "@/services/conversationService";
import { ApiError } from "@/services/api";
import {
  WorkbenchSessionProvider,
  useWorkbenchSession,
} from "./providers/WorkbenchSessionProvider";
import { AgentPicker } from "./components/AgentPicker";
import {
  changeAgentTopology,
  changeCreationThread,
  returnFromCreation,
} from "./conversationTransitions";
import { CreationActions } from "./components/CreationActions";
import { WorkbenchGreeting } from "./components/WorkbenchGreeting";
import { SkillCreationResultCard } from "./components/CreationResultCards";
import {
  applySkillCreationEvent,
  buildSkillSavePayload,
  initialSkillCreationDraft,
} from "./creationRuntime";
import { createSkill, searchAgentInfo } from "@/services/agentConfigService";
import { prepareWorkbenchAgentDraft } from "./agentCreationDraft";
import {
  isAgentCreationAwaitingDraft,
  shouldAutoCreateAgentDraft,
} from "./creationRecovery";
import { restoreCreationHistory } from "./creationHistory";
import { useAgentStore } from "@/stores/agentStore";
import { resolveRestoredWorkbench } from "./conversationRestore";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { useTranslation } from "react-i18next";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
  KnowledgeScopeResolution,
  KnowledgeScopeWarning,
} from "@/types/knowledgeScope";
import {
  getWorkbenchSendability,
  deriveConversationMode,
  previewWorkbenchAgent,
  SkillPicker,
} from "@/features/workbench";

type CreatedAgentResult = {
  agentId: number;
  displayName: string;
  description?: string;
};

export default function WorkbenchPage() {
  return (
    <Nl2AgentFlowProvider>
      <WorkbenchSessionProvider>
        <HomeContent />
      </WorkbenchSessionProvider>
    </Nl2AgentFlowProvider>
  );
}

/**
 * Inner component that has access to the AuiState via useAuiState hook.
 * Must be rendered inside AssistantRuntimeProvider.
 */
const HomeContent: FC = () => {
  const {
    runtime,
    selectedAgent,
    isLoadingAgents,
    agents,
    onRestoreAgent,
    onBack,
    isDictationConfigured,
    workbenchState,
    workbenchBootstrap,
    isLoadingWorkbenchBootstrap,
    onWorkbenchModeChange,
    dispatchWorkbench,
    conversationDetails,
  } = useWorkbenchSession();
  const { llmModels, isLoading: isLoadingModels } = useModelList();
  const effectiveWorkbenchConfig = workbenchState.config;
  const { t, i18n } = useTranslation();

  const { hasPermission, user } = useAuthorizationContext();
  const {
    resetFlow: resetNl2AgentFlow,
    markGenerationCompleted,
    markCompletionSynced,
    markPromptGenerationFailed,
    isComposerDisabled: nl2AgentComposerDisabled,
  } = useNl2AgentFlow();
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const [agentPickerOpen, setAgentPickerOpen] = useState(false);
  const [creationAgentsByThread, setCreationAgentsByThread] = useState<
    Record<string, CreatedAgentResult>
  >({});
  const creationAgentsByThreadRef = useRef<Record<string, CreatedAgentResult>>(
    {}
  );
  const [recoverableCreationThreads, setRecoverableCreationThreads] = useState<
    ReadonlySet<string>
  >(new Set());
  const skillDraftRef = useRef(initialSkillCreationDraft);
  const [skillDraft, setSkillDraft] = useState(initialSkillCreationDraft);
  const [savedSkillName, setSavedSkillName] = useState<string | null>(null);
  const creationReturnRef = useRef<string | null>(null);
  const [localThreadSnapshots, setLocalThreadSnapshots] = useState(
    new Map<
      string,
      {
        state: typeof workbenchState;
        skillDraft: typeof initialSkillCreationDraft;
        savedSkillName: string | null;
        selectedAgent: Agent | null;
        scope: ConversationKnowledgeScope | null;
        preview: KnowledgeScopeEffectivePreview | null;
      }
    >()
  );
  const resumedConversationIdsRef = useRef(new Set<number>());
  const [knowledgeCache, setKnowledgeCache] = useState(
    new Map<
      string,
      {
        scope: ConversationKnowledgeScope | null;
        preview: KnowledgeScopeEffectivePreview | null;
      }
    >()
  );
  const cacheKnowledge = useCallback(
    (
      threadId: string,
      patch: Partial<{
        scope: ConversationKnowledgeScope | null;
        preview: KnowledgeScopeEffectivePreview | null;
      }>
    ) => {
      setKnowledgeCache((cache) =>
        new Map(cache).set(threadId, {
          scope: null,
          preview: null,
          ...cache.get(threadId),
          ...patch,
        })
      );
    },
    []
  );
  const readLocalSnapshot = useEffectEvent((threadId: string) =>
    localThreadSnapshots.get(threadId)
  );
  const readKnowledgeCache = useEffectEvent((threadId: string) =>
    knowledgeCache.get(threadId)
  );

  // All hooks must be called before any early returns
  const runtimeMainThreadId = useAuiState((s) => s.threads.mainThreadId);
  const isThreadLoading = useAuiState((s) => s.thread.isLoading);
  const isThreadRunning = useAuiState((s) => s.thread.isRunning);
  const threadItems = useAuiState((s) => s.threads.threadItems);
  // Sidebar metadata reloads must not unmount the active chat and composer.
  const ready = runtimeMainThreadId !== undefined && !isThreadLoading;

  const activeThreadId = runtimeMainThreadId;

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
        map.set(threadId, numericId);
        cacheHistoricalChatMode(numericId, chatMode);
        // Keep the sidebar and run configuration in sync with the server id.
        setServerConversationIds(new Map(map));
        if (workbenchState.configVersion === 0) {
          dispatchWorkbench({ type: "set-version", version: 1 });
        }
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
              return next;
            });
          })
          .catch((error) => {
            if (!titleGuard.current.isCurrent(threadId, revision)) return;
            log.error(
              `[HomeContent] Failed to generate title for ${numericId}:`,
              error
            );
            // A title-model outage must not leave a persisted creation session
            // indefinitely labelled "新对话" in the sidebar.
            const fallbackTitle = initialQuestion.trim().slice(0, 40);
            if (!fallbackTitle) return;
            void conversationService
              .rename(Number(numericId), fallbackTitle, true)
              .then((renamed) => {
                if (!renamed) return;
                setGeneratedTitles((titles) => {
                  if (!titleGuard.current.isCurrent(threadId, revision))
                    return titles;
                  const next = new Map(titles);
                  next.set(threadId, fallbackTitle);
                  return next;
                });
              })
              .catch((renameError) => {
                log.error(
                  `[HomeContent] Failed to save fallback title for ${numericId}:`,
                  renameError
                );
              });
          });
      }
    },
    [chatMode, dispatchWorkbench, workbenchState.configVersion]
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
    ? serverConversationIds.get(activeThreadId)
    : undefined;
  // Prefer the server-issued id (set after the backend auto-creates the
  // conversation), then fall back to the thread's `remoteId` (used when the
  // user opens an existing conversation from the sidebar), then finally the
  // local assistant-ui thread id as a temporary placeholder.
  const rawConversationId =
    serverConversationIdForActiveThread ??
    activeThread?.remoteId ??
    activeThreadId;
  const activeConversationId =
    rawConversationId == null ? undefined : String(rawConversationId);
  const activeConversationIdRef = useRef(activeConversationId);
  const historyRestoreOwnerRef = useRef({
    threadId: undefined as string | undefined,
    startedLocal: false,
  });
  useLayoutEffect(() => {
    activeConversationIdRef.current = activeConversationId;
    if (historyRestoreOwnerRef.current.threadId !== activeThreadId) {
      const id = Number(activeConversationId);
      historyRestoreOwnerRef.current = {
        threadId: activeThreadId,
        startedLocal: !Number.isInteger(id) || id <= 0,
      };
    }
  }, [activeConversationId, activeThreadId]);

  const numericConversationId = Number(activeConversationId);
  const isPersistedConversation =
    Number.isInteger(numericConversationId) && numericConversationId > 0;
  const localSnapshot =
    activeThreadId && !isPersistedConversation
      ? localThreadSnapshots.get(activeThreadId)
      : undefined;
  const cachedKnowledge = activeThreadId
    ? knowledgeCache.get(activeThreadId)
    : undefined;
  // A live thread keeps its UI state when the backend first assigns its ID.
  const scopeKey = activeThreadId ?? "";
  const [knowledgeScope, setKnowledgeScope] =
    useConversationScopedState<ConversationKnowledgeScope | null>(
      scopeKey,
      (isPersistedConversation
        ? cachedKnowledge?.scope
        : localSnapshot?.scope) ?? null
    );
  const [knowledgePreview, setKnowledgePreview] =
    useConversationScopedState<KnowledgeScopeEffectivePreview | null>(
      scopeKey,
      (isPersistedConversation
        ? cachedKnowledge?.preview
        : localSnapshot?.preview) ?? null
    );
  const [runtimeMetadata, setRuntimeMetadata] = useConversationScopedState<
    Record<string, unknown>
  >(scopeKey, {});
  const [runtimeMetadataVersion, setRuntimeMetadataVersion] =
    useConversationScopedState(scopeKey, 0);
  const [runtimeMetadataDirty, setRuntimeMetadataDirty] =
    useConversationScopedState(scopeKey, false);
  const genericAgentId = workbenchBootstrap?.generic_agent?.agent_id;
  const genericAgentVersion = workbenchBootstrap?.generic_agent?.version_no;
  const [knowledgeCapabilities, setKnowledgeCapabilities] =
    useConversationScopedState<KnowledgeCapabilities | null>(
      JSON.stringify([genericAgentId, genericAgentVersion]),
      null
    );

  const [restoredLocalSnapshot, setRestoredLocalSnapshot] =
    useState(localSnapshot);
  if (restoredLocalSnapshot !== localSnapshot) {
    setRestoredLocalSnapshot(localSnapshot);
    if (localSnapshot) {
      setSkillDraft(localSnapshot.skillDraft);
      setSavedSkillName(localSnapshot.savedSkillName);
    }
  }
  const creationAgent = activeThreadId
    ? creationAgentsByThread[activeThreadId]
    : undefined;

  const handleNl2SkillEvent = useCallback((event: Nl2SkillStreamEvent) => {
    const next = applySkillCreationEvent(skillDraftRef.current, event);
    if (next === skillDraftRef.current) return;
    skillDraftRef.current = next;
    setSkillDraft(next);
    if (event.type === "agent_new_run" || event.type === "skill_body") {
      setSavedSkillName(null);
    }
  }, []);

  const nl2AgentSnapshotRefresh = useRef<Promise<void>>(Promise.resolve());
  const handleNl2AgentState = useCallback(
    (event: Nl2AgentStateEvent) => {
      if (event.event === "prompt_generation_failed") {
        markPromptGenerationFailed(event.agent_id, event.failed_fields);
        return;
      }
      const completed = event.event === "agent_generation_completed";
      if (completed) markGenerationCompleted(event.agent_id);
      nl2AgentSnapshotRefresh.current = nl2AgentSnapshotRefresh.current
        .then(() => searchAgentInfo(event.agent_id, undefined, 0))
        .then((result) => {
          if (!result.success || !result.data) {
            throw new Error(result.message || "Failed to refresh Agent draft");
          }
          if (
            !useAgentStore
              .getState()
              .replaceServerSnapshot(event.agent_id, result.data)
          ) {
            throw new Error("Agent context changed during synchronization");
          }
          if (completed) markCompletionSynced(event.agent_id);
        })
        .catch((error) => {
          log.warn("[Workbench] Failed to refresh generated Agent", error);
          // The generated Agent remains available; do not permanently lock the composer.
          if (completed) markCompletionSynced(event.agent_id);
        });
    },
    [markCompletionSynced, markGenerationCompleted, markPromptGenerationFailed]
  );

  useEffect(() => {
    const agentId = genericAgentId;
    if (!agentId) return;

    let cancelled = false;
    const versionNo = genericAgentVersion;
    void conversationService
      .getKnowledgeCapabilities(agentId, versionNo)
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
  }, [genericAgentId, genericAgentVersion, setKnowledgeCapabilities]);

  useEffect(() => {
    const numericConversationId = Number(activeConversationId);
    if (!activeThreadId) return;

    // First persistence updates the current live session; only a real thread
    // switch should reload its saved configuration and enter restore loading.
    if (
      historyRestoreOwnerRef.current.startedLocal &&
      serverConversationIdsRef.current.get(activeThreadId) ===
        activeConversationId
    ) {
      return;
    }

    if (
      !Number.isInteger(numericConversationId) ||
      numericConversationId <= 0
    ) {
      const cached = readLocalSnapshot(activeThreadId);
      if (cached) {
        dispatchWorkbench({
          type: "restore",
          config: cached.state.config,
          version: cached.state.configVersion,
        });
        dispatchWorkbench({
          type: "set-skill-names",
          names: cached.state.skillNames,
        });
        onRestoreAgent(cached.selectedAgent);
        skillDraftRef.current = cached.skillDraft;
      }
      return;
    }

    let cancelled = false;
    dispatchWorkbench({ type: "restore-start" });
    void conversationDetails
      .load(String(numericConversationId))
      .then(async (conversation) => {
        if (cancelled) return;
        const restored = await resolveRestoredWorkbench(conversation);
        if (cancelled) return;
        dispatchWorkbench({
          type: "set-skill-names",
          names: restored.skillNames,
        });
        dispatchWorkbench({
          type: "restore",
          config: restored.config,
          version: restored.version,
        });
        if (!serverConversationIdsRef.current.has(activeThreadId)) {
          const artifacts = restoreCreationHistory(conversation);
          if (restored.config.mode === "skill_create") {
            skillDraftRef.current = artifacts.skillDraft;
            setSkillDraft(artifacts.skillDraft);
            setSavedSkillName(null);
          } else if (
            restored.config.mode === "agent_create" &&
            Number.isInteger(Number(conversation.agent_id)) &&
            Number(conversation.agent_id) > 0
          ) {
            const agentId = Number(conversation.agent_id);
            const result = await searchAgentInfo(agentId, undefined, 0);
            if (cancelled) return;
            if (!result.success || !result.data) {
              // The historical Agent may have been deleted. Keep its messages,
              // but let the next send create a fresh draft in this conversation.
              const remaining = { ...creationAgentsByThreadRef.current };
              delete remaining[activeThreadId];
              creationAgentsByThreadRef.current = remaining;
              setCreationAgentsByThread(remaining);
              setRecoverableCreationThreads((threads) =>
                new Set(threads).add(activeThreadId)
              );
              resetNl2AgentFlow(null);
            } else {
              await prepareWorkbenchAgentDraft(agentId);
              if (cancelled) return;
              const created = {
                agentId,
                displayName: String(
                  result.data.display_name || result.data.name || "Agent"
                ),
                description: result.data.description || undefined,
              };
              creationAgentsByThreadRef.current = {
                ...creationAgentsByThreadRef.current,
                [activeThreadId]: created,
              };
              setCreationAgentsByThread(creationAgentsByThreadRef.current);
              setRecoverableCreationThreads((threads) => {
                const next = new Set(threads);
                next.delete(activeThreadId);
                return next;
              });
              resetNl2AgentFlow(agentId);
            }
          }
        }
        const restoredScope = restored.config.knowledge_scope ?? null;
        let restoredPreview =
          readKnowledgeCache(activeThreadId)?.preview ?? null;
        try {
          restoredPreview = await restoreKnowledgeDisplay(restoredScope);
        } catch (error) {
          log.warn("Knowledge display lookup failed", error);
        }
        if (cancelled) return;
        cacheKnowledge(activeThreadId, {
          scope: restoredScope,
          preview: restoredPreview,
        });
        setKnowledgeScope(restoredScope);
        setKnowledgePreview(restoredPreview);
      })
      .catch((error) => {
        if (!cancelled) {
          dispatchWorkbench({
            type: "resolve-agent-error",
            message: t("ui.localization.resourceRestoreFailed"),
          });
          log.error("[HomeContent] Failed to restore knowledge scope:", error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeConversationId,
    activeThreadId,
    dispatchWorkbench,
    resetNl2AgentFlow,
    onRestoreAgent,
    cacheKnowledge,
    setKnowledgeScope,
    setKnowledgePreview,
    t,
    conversationDetails,
  ]);

  useEffect(() => {
    const numericConversationId = Number(activeConversationId);
    if (
      activeThreadId &&
      historyRestoreOwnerRef.current.startedLocal &&
      serverConversationIdsRef.current.get(activeThreadId) ===
        activeConversationId
    ) {
      return;
    }
    if (
      !Number.isInteger(numericConversationId) ||
      numericConversationId <= 0
    ) {
      return;
    }

    let cancelled = false;
    void conversationDetails
      .load(String(numericConversationId))
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
  }, [
    activeConversationId,
    activeThreadId,
    setRuntimeMetadata,
    setRuntimeMetadataVersion,
    conversationDetails,
  ]);

  const handleRuntimeMetadataChange = useCallback(
    (value: Record<string, unknown>) => {
      setRuntimeMetadata(value);
      setRuntimeMetadataDirty(true);
    },
    [setRuntimeMetadata, setRuntimeMetadataDirty]
  );

  const handleRuntimeMetadataSent = useCallback(
    (version?: number) => {
      setRuntimeMetadataDirty(false);
      if (version !== undefined) {
        setRuntimeMetadataVersion(version);
      } else {
        setRuntimeMetadataVersion((currentVersion) => currentVersion + 1);
      }
    },
    [setRuntimeMetadataDirty, setRuntimeMetadataVersion]
  );

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

  const saveWorkbenchConfig = useCallback(
    async (
      conversationId: number,
      config: import("@/features/workbench").WorkbenchSessionConfig
    ) => {
      try {
        const result = await conversationService.updateWorkbenchConfig(
          conversationId,
          config,
          workbenchState.configVersion
        );
        conversationDetails.invalidate(String(conversationId));
        if (Number(activeConversationIdRef.current) !== conversationId) {
          throw new Error(t("ui.localization.conversationChanged"));
        }
        dispatchWorkbench({
          type: "restore",
          config: result.workbench_config,
          version: result.workbench_config_version,
        });
        return result;
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.code === "WORKBENCH_CONFIG_VERSION_CONFLICT"
        ) {
          const current = await conversationDetails.refresh(
            String(conversationId)
          );
          if (Number(activeConversationIdRef.current) !== conversationId)
            throw error;
          if (current.workbench_config) {
            dispatchWorkbench({
              type: "restore",
              config: current.workbench_config,
              version: current.workbench_config_version ?? 0,
            });
            setKnowledgeScope(current.workbench_config.knowledge_scope ?? null);
            setKnowledgePreview(null);
          }
          message.warning(t("ui.localization.configurationUpdated"));
        }
        throw error;
      }
    },
    [
      dispatchWorkbench,
      t,
      workbenchState.configVersion,
      setKnowledgeScope,
      setKnowledgePreview,
      conversationDetails,
    ]
  );

  const handleKnowledgeScopeChange = useCallback(
    async (
      scope: ConversationKnowledgeScope | null,
      preview?: KnowledgeScopeEffectivePreview | null
    ) => {
      const numericConversationId = Number(activeConversationId);
      const nextPreview = preview ?? null;
      try {
        if (
          workbenchState.config.mode !== "agent_create" &&
          workbenchState.config.mode !== "skill_create"
        ) {
          const nextConfig = {
            ...workbenchState.config,
            knowledge_scope: scope ?? undefined,
          };
          if (
            Number.isInteger(numericConversationId) &&
            numericConversationId > 0
          ) {
            await saveWorkbenchConfig(numericConversationId, nextConfig);
          } else {
            dispatchWorkbench({
              type: "restore",
              config: nextConfig,
              version: workbenchState.configVersion,
            });
          }
        } else {
          throw new Error(t("ui.localization.creationKnowledgeUnavailable"));
        }
        if (activeThreadId) {
          cacheKnowledge(activeThreadId, { scope, preview: nextPreview });
        }
        setKnowledgeScope(scope);
        setKnowledgePreview(nextPreview);
      } catch (error) {
        log.error("[HomeContent] Failed to update knowledge scope:", error);
        message.error(t("chat.knowledgeScope.saveFailed"));
        throw error;
      }
    },
    [
      activeConversationId,
      activeThreadId,
      dispatchWorkbench,
      saveWorkbenchConfig,
      t,
      workbenchState,
      cacheKnowledge,
      setKnowledgeScope,
      setKnowledgePreview,
    ]
  );

  const handleKnowledgeScopeResolved = useCallback(
    (resolution: KnowledgeScopeResolution) => {
      if (activeThreadId) {
        cacheKnowledge(activeThreadId, { preview: resolution.effective });
      }
      setKnowledgePreview(resolution.effective);
      showKnowledgeScopeWarnings(resolution.warnings);
    },
    [
      activeThreadId,
      showKnowledgeScopeWarnings,
      cacheKnowledge,
      setKnowledgePreview,
    ]
  );

  const handleChatModeChange = useCallback((mode: ChatMode) => {
    setChatMode(mode);
  }, []);

  const handleRemoveWorkbenchSkill = useCallback(
    async (skillId: number) => {
      const mounts = workbenchState.config.skill_mounts.filter(
        (mount) => mount.skill_id !== skillId
      );
      const numericConversationId = Number(activeConversationId);
      if (
        Number.isInteger(numericConversationId) &&
        numericConversationId > 0
      ) {
        try {
          await saveWorkbenchConfig(numericConversationId, {
            ...workbenchState.config,
            skill_mounts: mounts,
          });
        } catch (error) {
          message.error(
            error instanceof Error
              ? error.message
              : t("workbench.resources.saveFailed")
          );
        }
        return;
      }
      dispatchWorkbench({ type: "replace-skills", mounts });
    },
    [
      activeConversationId,
      saveWorkbenchConfig,
      t,
      workbenchState.config,
      dispatchWorkbench,
    ]
  );

  const handleReplaceWorkbenchSkills = useCallback(
    async (
      mounts: import("@/features/workbench").WorkbenchSkillMount[],
      skills: Array<{ skill_id: string; name: string }>
    ) => {
      if (runtime.thread.getState().isRunning)
        throw new Error(
          t("workbench.controls.waitForReply", "请等待当前回复完成")
        );
      const nextConfig = { ...workbenchState.config, skill_mounts: mounts };
      const numericConversationId = Number(activeConversationId);
      if (
        Number.isInteger(numericConversationId) &&
        numericConversationId > 0
      ) {
        await saveWorkbenchConfig(numericConversationId, nextConfig);
      } else {
        dispatchWorkbench({ type: "replace-skills", mounts });
      }
      dispatchWorkbench({
        type: "set-skill-names",
        names: Object.fromEntries(
          skills.map((skill) => [Number(skill.skill_id), skill.name])
        ),
      });
      setSkillPickerOpen(false);
    },
    [
      activeConversationId,
      dispatchWorkbench,
      saveWorkbenchConfig,
      workbenchState.config,
      runtime.thread,
      t,
    ]
  );

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
      agents.length === 0 ||
      workbenchState.resolving
    )
      return;

    const mount = workbenchState.config.agent_mounts[0];
    const agentId = mount?.agent_id;
    if (agentId === undefined || agentId === null) {
      onRestoreAgent(null);
      return;
    }

    const matchedAgent = agents.find((agent) => agent.id === String(agentId));
    if (
      matchedAgent &&
      (matchedAgent.id !== selectedAgent?.id ||
        mount.version_no !== selectedAgent?.current_version_no)
    ) {
      log.log(
        `[HomeContent] Thread changed to ${activeThreadId}, updating selectedAgent to: ${matchedAgent.display_name || matchedAgent.name}`
      );
      onRestoreAgent({ ...matchedAgent, current_version_no: mount.version_no });
    }
  }, [
    activeThreadId,
    activeAgentId,
    agents,
    selectedAgent?.id,
    selectedAgent?.current_version_no,
    onRestoreAgent,
    workbenchState.config.agent_mounts,
    workbenchState.resolving,
  ]);

  // Sync selected agent and active thread into composer's runConfig so the
  // ChatModelAdapter can forward both agent_id and conversation_id reliably.
  // `onServerConversationId` lets the adapter report back the server-issued
  // conversation_id returned in the response header, which we then reuse as
  // `threadId` for future runs in the same thread.
  useEffect(() => {
    applyComposerRunConfig(runtime, activeThreadId, {
      ...(workbenchState.config.mode === "agent_create" && creationAgent
        ? { agentId: creationAgent.agentId }
        : {}),
      ...(activeConversationId ? { threadId: activeConversationId } : {}),
      ...(knowledgeScope ? { knowledgeScope } : {}),
      ...(runtimeMetadataDirty ? { runtimeMetadata } : {}),
      ...(runtimeMetadataDirty && Number(activeConversationId) > 0
        ? { runtimeMetadataVersion }
        : {}),
      onRuntimeMetadataSent: handleRuntimeMetadataSent,
      onWorkbenchConfigVersion: (version: number) =>
        activeConversationIdRef.current === activeConversationId &&
        dispatchWorkbench({ type: "set-version", version }),
      onWorkbenchConfigConflict: async (query: string) => {
        const current = await conversationDetails.refresh(
          String(activeConversationId)
        );
        if (activeConversationIdRef.current !== activeConversationId) return;
        if (current.workbench_config) {
          dispatchWorkbench({
            type: "restore",
            config: current.workbench_config,
            version: current.workbench_config_version ?? 0,
          });
          setKnowledgeScope(current.workbench_config.knowledge_scope ?? null);
          setKnowledgePreview(null);
        }
        if (!runtime.thread.composer.getState().text)
          runtime.thread.composer.setText(query);
        message.warning(t("ui.localization.reloadRetainedInput"));
      },
      onKnowledgeScopeResolved: handleKnowledgeScopeResolved,
      onGenerationStopped: handleGenerationStopped,
      enablePlan: chatMode === "planning",
      ...(workbenchState.config.mode === "agent_create"
        ? {
            runtimeMode: "nl2agent" as const,
            persistCreationHistory: true,
            creationWorkbenchConfig: effectiveWorkbenchConfig,
            autoCreateAgentDraft: shouldAutoCreateAgentDraft(
              activeConversationId,
              activeThreadId != null &&
                recoverableCreationThreads.has(activeThreadId)
            ),
            agentAuthor: user?.email || "",
            onNl2AgentDraftCreated: async (created: CreatedAgentResult) => {
              await prepareWorkbenchAgentDraft(created.agentId);
              resetNl2AgentFlow(created.agentId);
              const threadId = runtime.threads.getState().mainThreadId;
              if (!threadId) return;
              creationAgentsByThreadRef.current = {
                ...creationAgentsByThreadRef.current,
                [threadId]: created,
              };
              setCreationAgentsByThread(creationAgentsByThreadRef.current);
              setRecoverableCreationThreads((threads) => {
                const next = new Set(threads);
                next.delete(threadId);
                return next;
              });
            },
            onNl2AgentState: handleNl2AgentState,
          }
        : workbenchState.config.mode === "skill_create"
          ? {
              runtimeMode: "nl2skill" as const,
              persistCreationHistory: true,
              creationWorkbenchConfig: effectiveWorkbenchConfig,
              complexity: "complicated" as const,
              language: i18n.language?.startsWith("en")
                ? ("en" as const)
                : ("zh" as const),
              draftSnapshot: {
                ...(buildSkillSavePayload(skillDraftRef.current) ?? {}),
                files: Object.entries(skillDraftRef.current.files).map(
                  ([path, content]) => ({ path, content })
                ),
              },
              onNl2SkillEvent: handleNl2SkillEvent,
            }
          : {}),
      ...(!["agent_create", "skill_create"].includes(workbenchState.config.mode)
        ? {
            workbenchConfig: effectiveWorkbenchConfig,
            workbenchConfigVersion: workbenchState.configVersion,
          }
        : {}),
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
    creationAgent,
    recoverableCreationThreads,
    activeConversationId,
    activeThreadId,
    chatMode,
    handleNl2AgentState,
    handleNl2SkillEvent,
    resetNl2AgentFlow,
    i18n.language,
    user?.email,
    skillDraft,
    knowledgeScope,
    runtimeMetadata,
    runtimeMetadataDirty,
    runtimeMetadataVersion,
    handleRuntimeMetadataSent,
    handleKnowledgeScopeResolved,
    handleGenerationStopped,
    handleServerConversationId,
    workbenchState,
    effectiveWorkbenchConfig,
    dispatchWorkbench,
    setKnowledgeScope,
    setKnowledgePreview,
    t,
    conversationDetails,
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

  useConversationResume({
    runtime,
    activeConversationId,
    activeThreadId,
    ready,
    isThreadRunning,
    selectedAgent: null,
    chatMode,
    resumedConversationIdsRef,
    handleGenerationStopped,
    loadDetail: conversationDetails.load,
    invalidateDetail: conversationDetails.invalidate,
  });

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

  const handlePrepareNewConversation = useCallback(() => {
    // Do not restore the agent from the thread that is being left.
    shouldRestoreAgentRef.current = false;
    onBack();
  }, [onBack]);

  const handleNewConversation = useCallback(async () => {
    handlePrepareNewConversation();
    await runtime.threads.switchToNewThread();
    // Re-fetch the conversation list: the thread the user just left only
    // became a server-side conversation when its first message was sent, and
    // without a reload it would disappear from the sidebar until a manual
    // page refresh (the newchat page already reloads at this point).
    await runtime.threads.reload();
  }, [handlePrepareNewConversation, runtime]);

  const applyAgentMounts = useCallback(
    async (mounts: import("@/features/workbench").WorkbenchAgentMount[]) => {
      const nextConfig = {
        ...workbenchState.config,
        mode: deriveConversationMode(mounts),
        agent_mounts: mounts,
      };
      const conversationId = Number(activeConversationId);
      if (Number.isInteger(conversationId) && conversationId > 0) {
        await saveWorkbenchConfig(conversationId, nextConfig);
      } else {
        dispatchWorkbench({
          type: "restore",
          config: nextConfig,
          version: workbenchState.configVersion,
        });
      }
      const first = mounts[0];
      const agent =
        first && agents.find((item) => Number(item.id) === first.agent_id);
      onRestoreAgent(
        agent ? { ...agent, current_version_no: first.version_no } : null
      );
    },
    [
      activeConversationId,
      agents,
      dispatchWorkbench,
      onRestoreAgent,
      saveWorkbenchConfig,
      workbenchState.config,
      workbenchState.configVersion,
    ]
  );

  const handleAgentSelectedFromLanding = useCallback(
    async (agent: Agent) => {
      try {
        const preview = await previewWorkbenchAgent(
          Number(agent.id),
          agent.current_version_no
        );
        await changeAgentTopology(runtime, () =>
          applyAgentMounts([
            { agent_id: preview.agent_id, version_no: preview.version_no },
          ])
        );
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : t("ui.localization.agentSwitchFailed")
        );
      }
    },
    [applyAgentMounts, runtime, t]
  );

  const workbenchSendability = getWorkbenchSendability(
    workbenchState,
    workbenchBootstrap ?? undefined
  );
  const removeMountedAgent = async (agentId: number) => {
    const mounts = workbenchState.config.agent_mounts.filter(
      (mount) => mount.agent_id !== agentId
    );
    try {
      await changeAgentTopology(runtime, () => applyAgentMounts(mounts));
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("ui.localization.agentRemoveFailed")
      );
    }
  };
  const isCreating =
    workbenchState.config.mode === "skill_create" ||
    workbenchState.config.mode === "agent_create";
  const changeCreationMode = async (
    mode: "skill_create" | "agent_create" | "generic_chat"
  ): Promise<boolean> => {
    try {
      if (
        mode !== "generic_chat" &&
        !hasPermission(
          mode === "agent_create" ? "agent:create" : "skill:create"
        )
      )
        return false;
      if (runtime.thread.getState().isRunning) {
        message.warning(t("ui.localization.waitReplyCreation"));
        return false;
      }
      if (mode === workbenchState.config.mode) return true;
      const currentId = runtime.threads.getState().mainThreadId;
      if (currentId) {
        const snapshot = {
          state: structuredClone(workbenchState),
          skillDraft: structuredClone(skillDraftRef.current),
          savedSkillName,
          selectedAgent,
          scope: knowledgeScope,
          preview: knowledgePreview,
        };
        setLocalThreadSnapshots((snapshots) =>
          new Map(snapshots).set(currentId, snapshot)
        );
      }
      if (mode === "generic_chat" && creationReturnRef.current) {
        const returnId = creationReturnRef.current;
        await returnFromCreation(runtime, returnId, () => {
          const cached = localThreadSnapshots.get(returnId);
          if (cached) {
            dispatchWorkbench({
              type: "restore",
              config: cached.state.config,
              version: cached.state.configVersion,
            });
            dispatchWorkbench({
              type: "set-skill-names",
              names: cached.state.skillNames,
            });
            onRestoreAgent(cached.selectedAgent);
            setKnowledgeScope(cached.scope);
            setKnowledgePreview(cached.preview);
          } else onWorkbenchModeChange("generic_chat");
        });
        creationReturnRef.current = null;
        return true;
      }
      if (!isCreating) creationReturnRef.current = currentId ?? null;
      await changeCreationThread(runtime, () => onWorkbenchModeChange(mode));
      setSkillPickerOpen(false);
      setAgentPickerOpen(false);
      skillDraftRef.current = initialSkillCreationDraft;
      setSkillDraft(initialSkillCreationDraft);
      setSavedSkillName(null);
      resetNl2AgentFlow(null);
      return true;
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("ui.localization.conversationCreateFailed")
      );
      return false;
    }
  };

  const handleSaveSkill = async (
    payload: NonNullable<ReturnType<typeof buildSkillSavePayload>>
  ) => {
    const result = await createSkill(payload);
    if (!result.success) {
      message.error(result.message || t("ui.localization.skillSaveFailed"));
      return;
    }
    setSavedSkillName(payload.name);
    message.success(t("ui.localization.skillSaved"));
  };

  const content = (
    <>
      <div className="shrink-0 h-full">
        <ThreadListSidebar
          collapseToFloatingButton
          pinStorageKey={
            user ? getWorkbenchPinStorageKey(user.id, user.tenantId) : null
          }
          generatedTitles={generatedTitles}
          serverConversationIds={serverConversationIds}
          onRenameSuccess={handleConversationRenamed}
          onPrepareNewConversation={handlePrepareNewConversation}
          onNewConversation={handleNewConversation}
        />
      </div>

      <WorkbenchLoadingBoundary
        conversationReady={ready}
        modelsLoading={isLoadingModels}
        bootstrapLoading={isLoadingWorkbenchBootstrap}
        resourcesResolving={workbenchState.resolving}
      >
        <div className="flex min-h-0 flex-1 min-w-0 flex-col">
          <div className="min-h-0 flex-1">
            <Chat
              showConversationTitle={false}
              generatedTitle={
                activeThreadId ? generatedTitles.get(activeThreadId) : undefined
              }
              conversationId={
                activeConversationId && Number(activeConversationId) > 0
                  ? Number(activeConversationId)
                  : undefined
              }
              isLoadingAgents={isLoadingAgents}
              interactionContent={
                <>
                  {workbenchState.config.mode === "skill_create" &&
                    skillDraft.complete && (
                      <SkillCreationResultCard
                        payload={buildSkillSavePayload(skillDraft)}
                        saved={
                          savedSkillName !== null &&
                          savedSkillName ===
                            buildSkillSavePayload(skillDraft)?.name
                        }
                        onSave={handleSaveSkill}
                      />
                    )}
                </>
              }
              selectedAgent={null}
              modelSelectionScope="tenant"
              fallbackAgentName={t(
                "workbench.genericAgentName",
                "智能体工作台"
              )}
              landingContent={<WorkbenchGreeting />}
              showModelSelector={true}
              onAgentSelected={handleAgentSelectedFromLanding}
              chatMode={chatMode}
              onChatModeChange={handleChatModeChange}
              composerTools={
                <>
                  <ComposerAttachment />
                  <ComposerDictation configured={isDictationConfigured} />
                </>
              }
              knowledgeScope={isCreating ? null : knowledgeScope}
              knowledgePreview={isCreating ? null : knowledgePreview}
              knowledgeCapabilities={isCreating ? null : knowledgeCapabilities}
              onKnowledgeScopeChange={
                isCreating ? undefined : handleKnowledgeScopeChange
              }
              runtimeMetadata={runtimeMetadata}
              onRuntimeMetadataChange={handleRuntimeMetadataChange}
              readOnly={
                !workbenchSendability.canSend ||
                (workbenchState.config.mode === "agent_create" &&
                  isAgentCreationAwaitingDraft(
                    activeThread?.remoteId,
                    !!creationAgent,
                    !!(
                      activeThreadId &&
                      recoverableCreationThreads.has(activeThreadId)
                    )
                  )) ||
                (workbenchState.config.mode === "agent_create" &&
                  nl2AgentComposerDisabled)
              }
              readOnlyReason={
                !isCreating && llmModels.length === 0
                  ? isLoadingModels
                    ? t("ui.localization.loadingModels")
                    : t("ui.localization.noModels")
                  : workbenchSendability.reason
              }
              skillFiles={
                workbenchState.config.mode === "skill_create" &&
                Object.keys(skillDraft.files).length > 0
                  ? Object.entries(skillDraft.files).map(([path, content]) => ({
                      path,
                      content,
                    }))
                  : undefined
              }
              workbenchResources={
                isCreating
                  ? undefined
                  : {
                      agentName:
                        selectedAgent?.display_name || selectedAgent?.name,
                      agents: workbenchState.config.agent_mounts.map(
                        (mount) => {
                          const agent = agents.find(
                            (item) => Number(item.id) === mount.agent_id
                          );
                          return {
                            id: mount.agent_id,
                            name:
                              agent?.display_name ||
                              agent?.name ||
                              `#${mount.agent_id}`,
                            remove: () =>
                              void removeMountedAgent(mount.agent_id),
                          };
                        }
                      ),
                      onSelectAgent: () => setAgentPickerOpen(true),
                      onRemoveAgent: () =>
                        void changeAgentTopology(runtime, () =>
                          applyAgentMounts([])
                        ).catch((error) => message.error(error.message)),
                      skills: workbenchState.config.skill_mounts.map(
                        (mount) => ({
                          id: mount.skill_id,
                          name:
                            workbenchState.skillNames[mount.skill_id] ||
                            `#${mount.skill_id}`,
                        })
                      ),
                    }
              }
              onRemoveWorkbenchSkill={handleRemoveWorkbenchSkill}
              onOpenWorkbenchSkillPicker={() => setSkillPickerOpen(true)}
              workbenchPresentation={{
                mode: workbenchState.config.mode,
                onExitCreation: () => void changeCreationMode("generic_chat"),
                actions: (
                  <CreationActions
                    canCreateAgent={hasPermission("agent:create")}
                    canCreateSkill={hasPermission("skill:create")}
                    mode={workbenchState.config.mode}
                    onExit={() => void changeCreationMode("generic_chat")}
                    disabled={isThreadRunning}
                    onSelect={(mode) => void changeCreationMode(mode)}
                  />
                ),
              }}
            />
          </div>
          <SkillPicker
            disabled={isThreadRunning}
            open={skillPickerOpen}
            selected={workbenchState.config.skill_mounts}
            onCancel={() => setSkillPickerOpen(false)}
            onConfirm={handleReplaceWorkbenchSkills}
          />
          <AgentPicker
            disabled={isThreadRunning}
            open={agentPickerOpen}
            agents={agents}
            selectedId={selectedAgent?.id}
            selectedIds={workbenchState.config.agent_mounts.map((mount) =>
              String(mount.agent_id)
            )}
            onCancel={() => setAgentPickerOpen(false)}
            multiple={true}
            onConfirm={async (selected) => {
              if (runtime.thread.getState().isRunning)
                throw new Error(
                  t("workbench.controls.waitForReply", "请等待当前回复完成")
                );
              const current = workbenchState.config.agent_mounts;
              if (
                current.length === selected.length &&
                selected.every((agent) =>
                  current.some(
                    (mount) =>
                      mount.agent_id === Number(agent.id) &&
                      mount.version_no === agent.current_version_no
                  )
                )
              )
                return;
              if (selected.length > 8)
                throw new Error(t("ui.localization.agentLimit"));
              const previews = await Promise.all(
                selected.map((agent) =>
                  previewWorkbenchAgent(
                    Number(agent.id),
                    agent.current_version_no
                  )
                )
              );
              await changeAgentTopology(runtime, () =>
                applyAgentMounts(
                  previews.map((preview) => ({
                    agent_id: preview.agent_id,
                    version_no: preview.version_no,
                  }))
                )
              );
            }}
            onSelect={(agent) => void handleAgentSelectedFromLanding(agent)}
          />
        </div>
      </WorkbenchLoadingBoundary>
    </>
  );

  return (
    <WorkbenchConversationLayout ready>{content}</WorkbenchConversationLayout>
  );
};
