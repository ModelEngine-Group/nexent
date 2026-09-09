"use client";
import { restoreKnowledgeDisplay } from "./knowledgeDisplay";

import { useCallback, useEffect, useRef, useState, type FC } from "react";
import { useAuiState } from "@assistant-ui/react";
import { Chat } from "@/app/newchat/assistant-ui/chat";
import type { ChatMode } from "@/app/newchat/assistant-ui/composer";
import { ThreadListSidebar } from "@/app/newchat/assistant-ui/threadlist-sidebar";
import {
  cacheHistoricalChatMode,
  generateConversationTitle,
  restoreHistoricalChatMode,
  restoreHistoricalPlan,
  setHistoricalChatModeListener,
  setServerConversationIdState,
} from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { useConversationResume } from "./hooks/useConversationResume";
import { SidebarProvider } from "@/components/ui/sidebar";
import { message } from "antd";
import type { Agent } from "@/types/agentConfig";
import log from "@/lib/logger";
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
} from "./conversationTransitions";
import { CreationActions } from "./components/CreationActions";
import { resolveRestoredWorkbench } from "./conversationRestore";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
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
  previewWorkbenchAgent,
  SkillPicker,
} from "@/features/workbench";

export default function WorkbenchPage() {
  return (
    <WorkbenchSessionProvider>
      <HomeContent />
    </WorkbenchSessionProvider>
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
    onAgentSelected,
    onRestoreAgent,
    onBack,
    isDictationConfigured,
    workbenchState,
    workbenchBootstrap,
    onWorkbenchModeChange,
    dispatchWorkbench,
  } = useWorkbenchSession();
  const { t } = useTranslation();
  const { canAccessRoute } = useAuthorizationContext();
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
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const [agentPickerOpen, setAgentPickerOpen] = useState(false);
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
        if (workbenchState.configVersion === 0) {
          dispatchWorkbench({ type: "set-version", version: 1 });
        }
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
    [chatMode, dispatchWorkbench, workbenchState.configVersion]
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
  const activeConversationIdRef = useRef(activeConversationId);
  activeConversationIdRef.current = activeConversationId;

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
    dispatchWorkbench({ type: "restore-start" });
    setKnowledgeScope(knowledgeScopesRef.current.get(activeThreadId) ?? null);
    setKnowledgePreview(
      knowledgePreviewsRef.current.get(activeThreadId) ?? null
    );
    void conversationService
      .getById(String(numericConversationId))
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
        const restoredScope = restored.config.knowledge_scope ?? null;
        let restoredPreview =
          knowledgePreviewsRef.current.get(activeThreadId) ?? null;
        try {
          restoredPreview = await restoreKnowledgeDisplay(restoredScope);
        } catch (error) {
          log.warn("Knowledge display lookup failed", error);
        }
        if (cancelled) return;
        knowledgeScopesRef.current.set(activeThreadId, restoredScope);
        knowledgePreviewsRef.current.set(activeThreadId, restoredPreview);
        setKnowledgeScope(restoredScope);
        setKnowledgePreview(restoredPreview);
      })
      .catch((error) => {
        if (!cancelled) {
          dispatchWorkbench({
            type: "resolve-agent-error",
            message: "会话资源恢复失败，请重新打开会话",
          });
          log.error("[HomeContent] Failed to restore knowledge scope:", error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeConversationId, activeThreadId, dispatchWorkbench]);

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
        if (Number(activeConversationIdRef.current) !== conversationId) {
          throw new Error("原会话配置已保存；当前会话已切换，请重新打开选择器");
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
          const current = await conversationService.getById(
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
          message.warning("配置已在其他页面更新，已加载最新版本");
        }
        throw error;
      }
    },
    [dispatchWorkbench, workbenchState.configVersion]
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
          throw new Error("创建模式不支持挂载知识库");
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
    [
      activeConversationId,
      activeThreadId,
      dispatchWorkbench,
      saveWorkbenchConfig,
      t,
      workbenchState,
    ]
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
            error instanceof Error ? error.message : "资源配置保存失败"
          );
        }
        return;
      }
      dispatchWorkbench({ type: "replace-skills", mounts });
    },
    [
      activeConversationId,
      saveWorkbenchConfig,
      workbenchState.config,
      dispatchWorkbench,
    ]
  );

  const handleReplaceWorkbenchSkills = useCallback(
    async (
      mounts: import("@/features/workbench").WorkbenchSkillMount[],
      skills: Array<{ skill_id: string; name: string }>
    ) => {
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
    ]
  );

  const handleModelChange = async (modelId: string) => {
    const id = Number(modelId);
    if (!Number.isInteger(id) || id <= 0) return;
    if (
      workbenchState.config.agent_mounts.length === 1 &&
      !selectedAgent?.model_ids?.includes(id)
    ) {
      message.warning("请选择当前智能体配置的模型");
      return;
    }
    const config = { ...workbenchState.config, model_id: id };
    try {
      if (Number(activeConversationId) > 0) {
        await saveWorkbenchConfig(Number(activeConversationId), config);
      } else {
        dispatchWorkbench({
          type: "restore",
          config,
          version: workbenchState.configVersion,
        });
      }
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "模型配置保存失败"
      );
    }
  };

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
        onWorkbenchConfigVersion: (version: number) =>
          activeConversationIdRef.current === activeConversationId &&
          dispatchWorkbench({ type: "set-version", version }),
        onWorkbenchConfigConflict: async (query: string) => {
          const current = await conversationService.getById(
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
          message.warning("配置已更新，已重新加载并保留输入；请确认后重新发送");
        },
        onKnowledgeScopeResolved: handleKnowledgeScopeResolved,
        onGenerationStopped: handleGenerationStopped,
        enablePlan: chatMode === "planning",
        ...(!["agent_create", "skill_create"].includes(
          workbenchState.config.mode
        )
          ? {
              workbenchConfig: workbenchState.config,
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
    workbenchState,
    dispatchWorkbench,
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
    selectedAgent,
    chatMode,
    resumedConversationIdsRef,
    handleGenerationStopped,
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
      try {
        await changeAgentTopology(runtime, () => onAgentSelected(agent));
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : "智能体切换失败"
        );
      }
    },
    [runtime, onAgentSelected]
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
      await changeAgentTopology(runtime, async () => {
        if (mounts.length === 0) {
          onBack();
          return;
        }
        if (mounts.length === 1) {
          const preview = await previewWorkbenchAgent(
            mounts[0].agent_id,
            mounts[0].version_no
          );
          dispatchWorkbench({ type: "resolve-agent-success", preview });
        } else {
          dispatchWorkbench({ type: "replace-agents", mounts });
        }
      });
    } catch (error) {
      message.error(error instanceof Error ? error.message : "智能体移除失败");
    }
  };
  const isCreating =
    workbenchState.config.mode === "skill_create" ||
    workbenchState.config.mode === "agent_create";
  const changeCreationMode = async (
    mode: "skill_create" | "agent_create" | "generic_chat"
  ) => {
    try {
      if (
        mode !== "generic_chat" &&
        !canAccessRoute(mode === "agent_create" ? "/agents" : "/skill-space")
      )
        return;
      if (runtime.thread.getState().isRunning) {
        message.warning("请等待当前回复完成后再开始创建");
        return;
      }
      await changeCreationThread(runtime, () => onWorkbenchModeChange(mode));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建会话失败");
    }
  };

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
          selectedModelId={workbenchState.config.model_id?.toString()}
          onModelChange={(id) => void handleModelChange(id)}
          onAgentSelected={handleAgentSelectedFromLanding}
          onBack={handleThreadBack}
          chatMode={chatMode}
          onChatModeChange={handleChatModeChange}
          isDictationConfigured={isDictationConfigured}
          knowledgeScope={isCreating ? null : knowledgeScope}
          knowledgePreview={isCreating ? null : knowledgePreview}
          knowledgeCapabilities={isCreating ? null : knowledgeCapabilities}
          onKnowledgeScopeChange={
            isCreating ? undefined : handleKnowledgeScopeChange
          }
          runtimeMetadata={runtimeMetadata}
          onRuntimeMetadataChange={handleRuntimeMetadataChange}
          readOnly={!workbenchSendability.canSend}
          readOnlyReason={workbenchSendability.reason}
          workbenchResources={
            isCreating
              ? undefined
              : {
                  agentName: selectedAgent?.display_name || selectedAgent?.name,
                  agents: workbenchState.config.agent_mounts.map((mount) => {
                    const agent = agents.find(
                      (item) => Number(item.id) === mount.agent_id
                    );
                    return {
                      id: mount.agent_id,
                      name:
                        agent?.display_name ||
                        agent?.name ||
                        `#${mount.agent_id}`,
                      remove: () => void removeMountedAgent(mount.agent_id),
                    };
                  }),
                  onSelectAgent: () => setAgentPickerOpen(true),
                  onRemoveAgent: () =>
                    void changeAgentTopology(runtime, onBack).catch((error) =>
                      message.error(error.message)
                    ),
                  skills: workbenchState.config.skill_mounts.map((mount) => ({
                    id: mount.skill_id,
                    name:
                      workbenchState.skillNames[mount.skill_id] ||
                      `#${mount.skill_id}`,
                  })),
                }
          }
          onRemoveWorkbenchSkill={handleRemoveWorkbenchSkill}
          onOpenWorkbenchSkillPicker={() => setSkillPickerOpen(true)}
          workbenchPresentation={{
            mode: workbenchState.config.mode,
            onExitCreation: () => void changeCreationMode("generic_chat"),
            actions: (
              <CreationActions
                canCreateAgent={canAccessRoute("/agents")}
                canCreateSkill={canAccessRoute("/skill-space")}
                disabled={isThreadRunning}
                onSelect={(mode) => void changeCreationMode(mode)}
              />
            ),
          }}
        />
        <SkillPicker
          open={skillPickerOpen}
          selected={workbenchState.config.skill_mounts}
          loadDefaults={
            workbenchState.config.agent_mounts.length === 1
              ? async () => {
                  const mount = workbenchState.config.agent_mounts[0];
                  const preview = await previewWorkbenchAgent(
                    mount.agent_id,
                    mount.version_no
                  );
                  return preview.default_skill_mounts;
                }
              : undefined
          }
          onCancel={() => setSkillPickerOpen(false)}
          onConfirm={handleReplaceWorkbenchSkills}
        />
        <AgentPicker
          open={agentPickerOpen}
          agents={agents}
          selectedId={selectedAgent?.id}
          selectedIds={workbenchState.config.agent_mounts.map((mount) =>
            String(mount.agent_id)
          )}
          onCancel={() => setAgentPickerOpen(false)}
          multiple={workbenchBootstrap?.modes.multi_agent_chat.enabled === true}
          onConfirm={async (selected) => {
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
            if (
              selected.length > 1 &&
              !workbenchBootstrap?.modes.multi_agent_chat.enabled
            )
              throw new Error("当前环境未启用多智能体模式");
            const previews = await Promise.all(
              selected.map((agent) =>
                previewWorkbenchAgent(
                  Number(agent.id),
                  agent.current_version_no
                )
              )
            );
            await changeAgentTopology(runtime, async () => {
              if (!selected.length) {
                onBack();
                return;
              }
              previews.forEach((preview, index) =>
                dispatchWorkbench({
                  type: "resolve-agent-success",
                  preview,
                  modelIds: selected[index].model_ids ?? [],
                  append: index > 0,
                })
              );
              onRestoreAgent(selected[0]);
            });
          }}
          onSelect={(agent) => {
            if (!workbenchBootstrap?.modes.multi_agent_chat.enabled)
              setAgentPickerOpen(false);
            void handleAgentSelectedFromLanding(agent);
          }}
        />
      </div>
    </div>
  );
};
