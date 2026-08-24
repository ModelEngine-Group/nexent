"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Switch, Tag } from "antd";
import {
  History,
  Maximize2,
  Minimize2,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { useSearchParams } from "next/navigation";

import AgentSelectorHeader from "./agent-selector-header";
import AgentConfig from "./agent-config";
import AgentVersion from "./agent-version";
import AgentDebugPanel from "./agent-debug";
import { Nl2AgentChatPanel } from "../newchat/assistant-ui/nl2agent-chat-panel";
import {
  Nl2AgentFlowProvider,
  useNl2AgentFlow,
  type Nl2AgentConfigFocusTarget,
} from "@/contexts/nl2AgentFlow";
import { useAgentStore } from "@/stores/agentStore";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { searchAgentInfo } from "@/services/agentConfigService";
import log from "@/lib/logger";
import type {
  Nl2AgentDraftField,
  Nl2AgentStateEvent,
} from "../newchat/adapter/remote-chat-model-adapter";

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
  if (updatedFields.includes("description")) {
    return { section: "display_info" };
  }
  return null;
}

interface PanelCardProps {
  title: string;
  children: ReactNode;
  className?: string;
  leftAction?: ReactNode;
  rightAction?: ReactNode;
  icon?: ReactNode;
}

function PanelCard({
  title,
  children,
  className = "",
  leftAction,
  rightAction,
  icon,
}: PanelCardProps) {
  return (
    <section
      className={`flex min-h-0 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm ${className}`}
    >
        <div className="flex min-h-12 shrink-0 items-center justify-between border-b border-gray-200 px-4">
          <div className="flex items-center gap-2">
            {icon}
            <h3 className="text-base font-medium text-gray-900">{title}</h3>
            {leftAction}
          </div>
          {rightAction}
      </div>
      {children}
    </section>
  );
}

function AgentSetupContent() {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const snapshotRefreshQueue = useRef<Promise<boolean>>(Promise.resolve(true));
  const [isGenerationVisible, setIsGenerationVisible] = useState(true);
  const [isDebugVisible, setIsDebugVisible] = useState(false);
  const [isCompareMode, setIsCompareMode] = useState(false);
  const [isDebugFullscreen, setIsDebugFullscreen] = useState(false);
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] =
    useState(false);
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const { agentInfo } = useAgentInfo(currentAgentId);
  const { total } = useAgentVersionList(currentAgentId);
  const { agentVersionDetail } = useAgentVersionDetail(
    currentAgentId,
    agentInfo?.current_version_no ?? null
  );
  const permissionReadOnly = useAgentStore((state) => state.isReadOnly);
  const {
    isComposerDisabled,
    completionSyncFailed,
    markCompletionSynced,
    markCompletionSyncFailed,
    markGenerationCompleted,
    markPromptGenerationFailed,
    requestConfigFocus,
    resetFlow,
    sessionGeneration,
  } = useNl2AgentFlow();
  const requestedAgentId = Number(searchParams.get("agent_id"));
  const isRequestedAgentLoading =
    Number.isInteger(requestedAgentId) &&
    requestedAgentId > 0 &&
    requestedAgentId !== currentAgentId;
  const isNl2AgentUnavailable = currentAgentId === null || permissionReadOnly;

  useEffect(() => {
    resetFlow(currentAgentId);
  }, [currentAgentId, resetFlow]);

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

          queryClient.setQueryData(["agentInfo", agentId], result.data);
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
      void enqueueSnapshotRefresh(agentId, {
        section: "conversation_guide",
      }).then((synchronized) => {
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

  const retryCompletionSync = useCallback(() => {
    if (currentAgentId !== null) synchronizeCompletion(currentAgentId);
  }, [currentAgentId, synchronizeCompletion]);

  return (
    <div className="flex h-full w-full min-h-0 flex-col bg-gray-50">
      <div className="h-auto min-h-0 shrink-0 bg-white">
        <AgentSelectorHeader
          onToggleVersionManage={() =>
            setIsShowVersionManagePanel((visible) => !visible)
          }
          isVersionManageVisible={isShowVersionManagePanel}
        />
      </div>

      <main className="flex min-h-0 flex-1 flex-row gap-4 overflow-hidden p-6">
        <div className="flex min-w-0 min-h-0 flex-1 flex-row gap-4">
          {isGenerationVisible && (
            <PanelCard
              title={t("agent.page.panel.nl2agent")}
              className={isDebugVisible ? "flex-1" : "flex-[1]"}
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
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                {isNl2AgentUnavailable ? (
                  <div
                    className="shrink-0 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900"
                    role="status"
                  >
                    {t(
                      "nl2agent.unavailable",
                      "Create or select an editable Agent first."
                    )}
                  </div>
                ) : null}
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
                  key={sessionGeneration}
                  agentId={currentAgentId}
                  disabled={
                    isComposerDisabled ||
                    isRequestedAgentLoading ||
                    isNl2AgentUnavailable
                  }
                  onStateEvent={handleStateEvent}
                />
              </div>
            </PanelCard>
          )}

          <PanelCard
            title={t("agent.page.panel.config")}
            className={isDebugFullscreen ? "flex-1" : "flex-[2]"}
            leftAction={
              currentAgentId !== null &&
              agentInfo?.current_version_no !== 0 &&
              total > 0 ? (
                <div className="flex shrink-0 items-center gap-1 rounded-lg px-3 py-1.5 text-gray-700">
                  <History size={16} />
                  <Tag
                    color="cyan"
                    variant="outlined"
                    className="cursor-pointer rounded-md font-mono text-sm"
                    onClick={() => setIsShowVersionManagePanel(true)}
                  >
                    {agentVersionDetail?.version.version_name}
                  </Tag>
                  <span className="text-xs text-gray-500">
                    / {t("agent.version.totalVersions", { count: total })}
                  </span>
                </div>
              ) : null
            }
            rightAction={
              <Button
                icon={<Sparkles size={16} />}
                onClick={() => setIsGenerationVisible((visible) => !visible)}
                type={isGenerationVisible ? "primary" : "default"}
              >
                {t("agent.page.panel.nl2agent")}
              </Button>
            }
          >
            <div className="min-h-0 flex-1 overflow-auto px-4 py-2">
              <AgentConfig
                onToggleDebug={() => setIsDebugVisible((visible) => !visible)}
              />
            </div>
          </PanelCard>

          {isDebugVisible && (
            <PanelCard
              title={t("agent.page.panel.debug")}
              className={isDebugFullscreen ? "flex-[2]" : "flex-1"}
              leftAction={
                <div className="flex items-center gap-2 text-sm text-gray-600">
                  <span>{t("agent.debug.compareMode")}</span>
                  <Switch
                    checked={isCompareMode}
                    onChange={setIsCompareMode}
                    size="small"
                  />
                </div>
              }
              rightAction={
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-label={
                      isDebugFullscreen
                        ? "Restore debug panel size"
                        : "Maximize debug panel"
                    }
                    onClick={() => {
                      if (isDebugFullscreen) {
                        setIsDebugFullscreen(false);
                        return;
                      }

                      setIsGenerationVisible(false);
                      setIsShowVersionManagePanel(false);
                      setIsDebugFullscreen(true);
                    }}
                    className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                  >
                    {isDebugFullscreen ? (
                      <Minimize2 size={18} />
                    ) : (
                      <Maximize2 size={18} />
                    )}
                  </button>
                  <button
                    type="button"
                    aria-label={t("agent.page.panel.debug.closeAria")}
                    onClick={() => {
                      setIsDebugVisible(false);
                      setIsDebugFullscreen(false);
                    }}
                    className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                  >
                    <X size={18} />
                  </button>
                </div>
              }
            >
              <div className="min-h-0 flex-1 overflow-hidden">
                <AgentDebugPanel isCompareMode={isCompareMode} />
              </div>
            </PanelCard>
          )}

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
                <AgentVersion />
              </div>
            </PanelCard>
          )}
        </div>
      </main>
    </div>
  );
}

export default function AgentSetupOrchestrator() {
  return (
    <Nl2AgentFlowProvider>
      <AgentSetupContent />
    </Nl2AgentFlowProvider>
  );
}
