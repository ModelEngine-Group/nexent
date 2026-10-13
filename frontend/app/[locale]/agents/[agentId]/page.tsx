"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Modal, Spin, Tag } from "antd";
import { GitBranch, History, RefreshCw, Sparkles, X } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import AgentConfig from "./agent-config";
import { AgentCreationGuide } from "./components/agent-creation-guide";
import {
  agentCreationGuideKey,
  canStartAgentCreationGuide,
} from "@/lib/agentCreationGuide";
import AgentVersion from "../agent-version";
import AgentDebugPanel from "./components/debug/agent-debug";
import {
  Nl2AgentChatPanel,
  type Nl2AgentChatPanelHandle,
} from "../../newchat/assistant-ui/nl2agent-chat-panel";
import {
  Nl2AgentFlowProvider,
  useNl2AgentFlow,
  type Nl2AgentConfigFocusTarget,
} from "@/contexts/nl2AgentFlow";
import { useAgentStore } from "@/stores/agentStore";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { searchAgentInfo } from "@/services/agentConfigService";
import { buildAgentUsageGuidePath } from "@/lib/agentUsageGuide";
import log from "@/lib/logger";
import type {
  Nl2AgentDraftField,
  Nl2AgentStateEvent,
} from "../../newchat/adapter/remote-chat-model-adapter";

function resolveDraftFocusTarget(
  updatedFields: readonly Nl2AgentDraftField[]
): Nl2AgentConfigFocusTarget | null {
  if (
    updatedFields.includes("greeting_message") ||
    updatedFields.includes("example_questions")
  ) {
    return { section: "conversation_guide" };
  }
  if (updatedFields.includes("few_shots_prompt")) {
    return { section: "role_model", promptTab: "few-shots" };
  }
  if (updatedFields.includes("constraint_prompt")) {
    return { section: "role_model", promptTab: "constraint" };
  }
  if (updatedFields.includes("duty_prompt")) {
    return { section: "role_model", promptTab: "duty" };
  }
  if (updatedFields.includes("name") || updatedFields.includes("description")) {
    return { section: "display_info" };
  }
  return null;
}

interface PanelCardProps {
  title: string;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  leftAction?: ReactNode;
  rightAction?: ReactNode;
  icon?: ReactNode;
  panelRef?: Ref<HTMLElement>;
  frameless?: boolean;
  showHeader?: boolean;
  headerTestId?: string;
}

function PanelCard({
  title,
  children,
  className = "",
  headerClassName = "",
  leftAction,
  rightAction,
  icon,
  panelRef,
  frameless = false,
  showHeader = true,
  headerTestId,
}: PanelCardProps) {
  return (
    <section
      ref={panelRef}
      className={`flex min-h-0 min-w-0 flex-col overflow-hidden ${frameless ? "bg-[#f3f3f3]" : "border-l border-[#dfdfdf] bg-white"} ${className}`}
    >
      {showHeader && (
        <div
          data-testid={headerTestId}
          className={`flex min-h-12 shrink-0 items-center justify-between border-b border-gray-200 px-4 ${headerClassName}`}
        >
          <div className="flex items-center gap-2">
            {icon}
            <h3 className="max-w-[280px] truncate text-sm font-normal leading-[22px] text-[#191919]">
              {title}
            </h3>
            {leftAction}
          </div>
          {rightAction}
        </div>
      )}
      {children}
    </section>
  );
}

function AgentSetupContent({
  onBack,
  onManageVersions,
}: {
  onBack: () => void;
  onManageVersions: () => void;
}) {
  const { t } = useTranslation("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [creationGuideActive, setCreationGuideActive] = useState(false);
  const { agentId, locale: routeLocale } = useParams<{
    agentId: string;
    locale: string;
  }>();
  const locale = routeLocale || "en";
  const queryClient = useQueryClient();
  const snapshotRefreshQueue = useRef<Promise<boolean>>(Promise.resolve(true));
  const nl2AgentChatPanelRef = useRef<Nl2AgentChatPanelHandle>(null);
  const actionAreaRef = useRef<HTMLDivElement>(null);
  const [isGenerationVisible, setIsGenerationVisible] = useState(true);
  const [isDebugVisible, setIsDebugVisible] = useState(false);
  const [isCompareMode, setIsCompareMode] = useState(false);
  const [isDebugFullscreen, setIsDebugFullscreen] = useState(false);
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] =
    useState(false);
  const panesBeforeFullscreen = useRef<{
    generation: boolean;
    versions: boolean;
  } | null>(null);
  const restoreDebugLayout = () => {
    if (panesBeforeFullscreen.current) {
      setIsGenerationVisible(panesBeforeFullscreen.current.generation);
      setIsShowVersionManagePanel(panesBeforeFullscreen.current.versions);
      panesBeforeFullscreen.current = null;
    }
    setIsDebugFullscreen(false);
  };
  const closeDebug = () => {
    restoreDebugLayout();
    setIsDebugVisible(false);
  };
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const resetAgentStore = useAgentStore((state) => state.reset);
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;
  const previousTenantIdRef = useRef<string | null | undefined>(undefined);
  const requestedAgentId = Number(agentId);
  const isRequestedAgentLoading =
    Number.isInteger(requestedAgentId) &&
    requestedAgentId > 0 &&
    requestedAgentId !== currentAgentId;
  const { agentInfo, refetch: refetchAgentInfo } = useAgentInfo(currentAgentId);
  const { total } = useAgentVersionList(currentAgentId);
  const shouldFetchVersionDetail = !isRequestedAgentLoading && total > 0;
  const { agentVersionDetail } = useAgentVersionDetail(
    currentAgentId,
    agentInfo?.current_version_no ?? null,
    shouldFetchVersionDetail
  );
  const permissionReadOnly = useAgentStore((state) => state.isReadOnly);
  const {
    agentId: flowAgentId,
    completionSyncFailed,
    isComposerDisabled,
    isFormLocked,
    markCompletionSynced,
    markCompletionSyncFailed,
    markGenerationCompleted,
    markGenerationStopped,
    markRunFinished,
    markRunStarted,
    markPromptGenerationFailed,
    requestConfigFocus,
    resetFlow,
    sessionGeneration,
  } = useNl2AgentFlow();
  const isNl2AgentUnavailable = currentAgentId === null || permissionReadOnly;
  const canManualUnlock =
    !isNl2AgentUnavailable &&
    flowAgentId === currentAgentId &&
    !isRequestedAgentLoading &&
    (isFormLocked || isComposerDisabled);
  const showOptimizationSuggestions =
    !isRequestedAgentLoading && !isNl2AgentUnavailable;
  const showCreationGuide = canStartAgentCreationGuide({
    creationEntry: searchParams.get("onboarding") === "1",
    ready:
      !isRequestedAgentLoading &&
      currentAgentId === requestedAgentId &&
      Boolean(agentInfo) &&
      isGenerationVisible &&
      !isDebugVisible,
    readOnly: permissionReadOnly,
    tenantId,
    userId: user?.id,
  });

  useEffect(() => {
    resetFlow(currentAgentId);
  }, [currentAgentId, resetFlow]);

  useEffect(() => {
    if (previousTenantIdRef.current === undefined) {
      previousTenantIdRef.current = tenantId;
      return;
    }

    if (previousTenantIdRef.current === tenantId) return;

    // Discard the previous tenant's draft before an agent id can be reused.
    previousTenantIdRef.current = tenantId;
    resetAgentStore();
    snapshotRefreshQueue.current = Promise.resolve(true);
    queryClient.removeQueries({ queryKey: ["agents"] });
    queryClient.removeQueries({ queryKey: ["tools"] });
  }, [queryClient, resetAgentStore, tenantId]);

  const enqueueSnapshotRefresh = useCallback(
    (agentId: number, focusTarget: Nl2AgentConfigFocusTarget | null = null) => {
      snapshotRefreshQueue.current = snapshotRefreshQueue.current
        .then(async () => {
          const initialState = useAgentStore.getState();
          if (initialState.currentAgentId !== agentId) return false;

          const autosaveSucceeded = await initialState.waitForIdle();
          if (!autosaveSucceeded) {
            throw new Error("Pending Agent edits could not be saved");
          }
          if (useAgentStore.getState().currentAgentId !== agentId) return false;

          const result = await searchAgentInfo(agentId, undefined, 0);
          if (!result.success || !result.data) {
            throw new Error(result.message);
          }
          const currentState = useAgentStore.getState();
          if (currentState.currentAgentId !== agentId) return false;
          if (!currentState.replaceServerSnapshot(agentId, result.data)) {
            throw new Error("Agent context changed during synchronization");
          }

          await queryClient.invalidateQueries({ queryKey: ["agents"] });
          if (focusTarget) requestConfigFocus(agentId, focusTarget);
          return true;
        })
        .catch((error) => {
          log.warn("[NL2Agent] Failed to refresh saved draft fields", {
            agentId,
            error,
          });
          return false;
        });
      return snapshotRefreshQueue.current;
    },
    [queryClient, requestConfigFocus]
  );

  const synchronizeCompletion = useCallback(
    (agentId: number) => {
      void enqueueSnapshotRefresh(agentId).then((synchronized) => {
        if (synchronized) markCompletionSynced(agentId);
        else markCompletionSyncFailed(agentId);
      });
    },
    [enqueueSnapshotRefresh, markCompletionSyncFailed, markCompletionSynced]
  );

  const handleStateEvent = useCallback(
    (event: Nl2AgentStateEvent) => {
      if (event.event === "prompt_generation_failed") {
        markPromptGenerationFailed(event.agent_id, event.failed_fields);
        return;
      }
      if (event.event === "agent_generation_completed") {
        markGenerationCompleted(event.agent_id);
        synchronizeCompletion(event.agent_id);
        return;
      }
      void enqueueSnapshotRefresh(
        event.agent_id,
        resolveDraftFocusTarget(event.updated_fields)
      );
    },
    [
      enqueueSnapshotRefresh,
      markGenerationCompleted,
      markPromptGenerationFailed,
      synchronizeCompletion,
    ]
  );

  const handleGenerationStopped = useCallback(
    (agentId: number) => markGenerationStopped(agentId),
    [markGenerationStopped]
  );

  const handleManualUnlock = useCallback(() => {
    if (!canManualUnlock || currentAgentId === null) return;
    nl2AgentChatPanelRef.current?.cancelRun();
    markGenerationStopped(currentAgentId);
  }, [canManualUnlock, currentAgentId, markGenerationStopped]);

  const retryCompletionSync = useCallback(() => {
    if (currentAgentId !== null) synchronizeCompletion(currentAgentId);
  }, [currentAgentId, synchronizeCompletion]);

  const handleAgentPublished = useCallback(() => {
    if (currentAgentId === null) return;

    void Promise.all([
      refetchAgentInfo(),
      queryClient.invalidateQueries({
        queryKey: ["agentVersions", currentAgentId],
      }),
    ]).catch((error) => {
      log.warn("[AgentVersion] Failed to refresh version information", {
        agentId: currentAgentId,
        error,
      });
    });
    router.push(buildAgentUsageGuidePath(locale, currentAgentId));
  }, [currentAgentId, locale, queryClient, refetchAgentInfo, router]);

  return (
    <div
      ref={workspaceRef}
      className="flex h-full w-full min-h-0 flex-col bg-[#f3f3f3]"
    >
      {showCreationGuide && user?.id && tenantId && (
        <AgentCreationGuide
          key={`${agentCreationGuideKey(tenantId, user.id)}/${requestedAgentId}`}
          preferenceKey={agentCreationGuideKey(tenantId, user.id)}
          workspaceRef={workspaceRef}
          onOpenChange={setCreationGuideActive}
        />
      )}
      <main
        data-testid="agent-config-workspace"
        className="relative flex min-h-0 flex-1 flex-row overflow-hidden"
      >
        <div
          className="flex min-w-0 min-h-0 flex-1 flex-row"
          style={{ visibility: isRequestedAgentLoading ? "hidden" : "visible" }}
        >
          <PanelCard
            frameless
            showHeader={false}
            title={t("agent.page.panel.nl2agent")}
            className={
              isGenerationVisible
                ? isDebugVisible
                  ? "w-[28%] shrink-0 2xl:w-[561px]"
                  : "w-[32%] shrink-0 2xl:w-[561px]"
                : "hidden"
            }
            rightAction={
              <button
                type="button"
                aria-label={t("agent.page.panel.nl2agent.closeAria")}
                onClick={() => setIsGenerationVisible(false)}
                className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
              >
                <X size={18} />
              </button>
            }
          >
            <div
              data-testid="agent-config-conversation-panel"
              data-agent-guide="assistant"
              className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white"
            >
              {completionSyncFailed ? (
                <div
                  className="flex shrink-0 items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900"
                  role="alert"
                >
                  <span>
                    {t(
                      "nl2agent.completion.syncFailed",
                      "The Agent was generated, but the form could not be refreshed."
                    )}
                  </span>
                  <Button
                    icon={<RefreshCw size={14} />}
                    onClick={retryCompletionSync}
                    size="small"
                  >
                    {t("nl2agent.completion.retry", "Retry")}
                  </Button>
                </div>
              ) : null}
              <Nl2AgentChatPanel
                ref={nl2AgentChatPanelRef}
                key={`${currentAgentId ?? "unselected"}-${sessionGeneration}`}
                agentId={currentAgentId}
                showOptimizationSuggestions={showOptimizationSuggestions}
                configurationLayout
                disabled={
                  isComposerDisabled ||
                  isRequestedAgentLoading ||
                  isNl2AgentUnavailable
                }
                onStateEvent={handleStateEvent}
                onStopped={handleGenerationStopped}
                onRunStart={markRunStarted}
                onRunEnd={markRunFinished}
              />
            </div>
          </PanelCard>

          <PanelCard
            frameless
            headerTestId="agent-config-page-tabs"
            title={t("agent.highFidelity.pageTab", {
              name:
                agentInfo?.display_name ||
                agentInfo?.name ||
                t("agent.page.panel.config"),
            })}
            className={"flex-1"}
            headerClassName="h-16 min-h-16 border-[#dfdfdf] pl-4 pr-[18px] py-3"
            leftAction={
              <Button
                type="text"
                aria-label={t("common.back")}
                icon={<X size={14} />}
                onClick={onBack}
                className="!size-6 !p-0"
              />
            }
            rightAction={
              <div className="flex items-center gap-2">
                <Button
                  type="text"
                  icon={<GitBranch size={16} />}
                  aria-label={t("agent.version.manage")}
                  onClick={onManageVersions}
                />
                {agentInfo?.current_version_no && total > 0 ? (
                  <div className="flex items-center gap-1">
                    <History size={16} />
                    {t("agent.version.current")}:
                    <Tag
                      color="cyan"
                      variant="outlined"
                      className="cursor-pointer rounded-md font-mono text-sm"
                      onClick={() => setIsShowVersionManagePanel(true)}
                    >
                      {agentVersionDetail?.version.version_name ||
                        `V${agentInfo.current_version_no}`}
                    </Tag>
                    <span className="text-xs text-gray-500">
                      / {t("agent.version.totalVersions", { count: total })}
                    </span>
                  </div>
                ) : null}
                <Button
                  icon={<Sparkles size={16} />}
                  onClick={() => setIsGenerationVisible((visible) => !visible)}
                  type="text"
                  aria-label={t("agent.page.panel.nl2agent")}
                ></Button>
              </div>
            }
          >
            <div className="min-h-0 flex-1 overflow-hidden">
              <AgentConfig
                creationGuideActive={showCreationGuide && creationGuideActive}
                published={Boolean(agentInfo?.current_version_no)}
                actionAreaRef={actionAreaRef}
                canManualUnlock={canManualUnlock}
                onManualUnlock={handleManualUnlock}
                onToggleDebug={() =>
                  isDebugVisible ? closeDebug() : setIsDebugVisible(true)
                }
                debugVisible={isDebugVisible}
                debugExpanded={isDebugFullscreen || isCompareMode}
                debugPanel={
                  <div
                    data-testid="agent-debug-pane"
                    className={
                      !isDebugVisible
                        ? "hidden"
                        : isDebugFullscreen || isCompareMode
                          ? "min-h-0 min-w-0 flex-1"
                          : "min-h-0 w-[488px] max-w-[52%] shrink-0"
                    }
                  >
                    <AgentDebugPanel
                      key={currentAgentId ?? "unselected"}
                      isCompareMode={isCompareMode}
                      isFullscreen={isDebugFullscreen}
                      onCompareModeChange={setIsCompareMode}
                      onClose={closeDebug}
                      onToggleFullscreen={() => {
                        if (isDebugFullscreen) {
                          restoreDebugLayout();
                        } else {
                          panesBeforeFullscreen.current = {
                            generation: isGenerationVisible,
                            versions: isShowVersionManagePanel,
                          };
                          setIsGenerationVisible(false);
                          setIsShowVersionManagePanel(false);
                          setIsDebugFullscreen(true);
                        }
                      }}
                    />
                  </div>
                }
                onConfigure={closeDebug}
                onOptimizePrompt={() => {
                  setIsGenerationVisible(true);
                  nl2AgentChatPanelRef.current?.sendPrompt(
                    t("nl2agent.optimization.prompt.input")
                  );
                }}
                onPublished={handleAgentPublished}
              />
            </div>
          </PanelCard>

          {isShowVersionManagePanel && (
            <PanelCard
              title={t("agent.version.manage")}
              className="flex-1"
              rightAction={
                <button
                  type="button"
                  aria-label={t("agent.page.panel.debug.closeAria")}
                  onClick={() => setIsShowVersionManagePanel(false)}
                  className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                >
                  <X size={18} />
                </button>
              }
            >
              <div className="min-h-0 flex-1 overflow-hidden">
                <AgentVersion
                  currentVersionNo={agentInfo?.current_version_no}
                  onRefreshAgentInfo={refetchAgentInfo}
                />
              </div>
            </PanelCard>
          )}
        </div>
        {isRequestedAgentLoading ? (
          <div
            className="absolute inset-0 z-10 flex items-center justify-center gap-3 bg-gray-50"
            role="status"
          >
            <Spin size="large" />
            <span className="text-sm text-gray-500">{t("common.loading")}</span>
          </div>
        ) : null}
      </main>
    </div>
  );
}

export default function AgentEditor() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const router = useRouter();
  const { agentId } = useParams<{ agentId: string }>();
  const requestedAgentId = Number(agentId);
  const isValidAgentId =
    Number.isInteger(requestedAgentId) && requestedAgentId > 0;
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const initialize = useAgentStore((state) => state.initialize);
  const reset = useAgentStore((state) => state.reset);
  const [isVersionManageOpen, setIsVersionManageOpen] = useState(false);
  const isReturningRef = useRef(false);
  const { agentInfo, refetch: refetchAgentInfo } = useAgentInfo(currentAgentId);

  useEffect(() => {
    if (isReturningRef.current) return;

    if (!isValidAgentId) {
      router.replace("/agents");
      return;
    }
    if (currentAgentId === requestedAgentId) return;

    void (async () => {
      const result = await searchAgentInfo(requestedAgentId);
      if (!result.success || !result.data) {
        message.error(
          result.message || t("agentConfig.agents.detailsLoadFailed")
        );
        router.replace("/agents");
        return;
      }
      initialize(result.data);
    })();
  }, [
    currentAgentId,
    initialize,
    isValidAgentId,
    message,
    requestedAgentId,
    router,
    t,
  ]);

  if (!isValidAgentId) return null;

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#f3f3f3]">
      <div className="min-h-0 flex-1">
        <Nl2AgentFlowProvider>
          <AgentSetupContent
            onBack={() => {
              isReturningRef.current = true;
              reset();
              router.push("/agents");
            }}
            onManageVersions={() => setIsVersionManageOpen(true)}
          />
        </Nl2AgentFlowProvider>
      </div>
      <Modal
        centered
        width={900}
        open={isVersionManageOpen}
        title={t("agent.version.manage")}
        onCancel={() => setIsVersionManageOpen(false)}
        footer={null}
      >
        <AgentVersion
          currentVersionNo={agentInfo?.current_version_no}
          onRefreshAgentInfo={refetchAgentInfo}
        />
      </Modal>
    </div>
  );
}
