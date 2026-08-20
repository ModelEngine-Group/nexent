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
import { Button } from "antd";
import { RefreshCw, Sparkles, X } from "lucide-react";
import { useSearchParams } from "next/navigation";

import AgentSelectorHeader from "./components/agent-selector-header";
import AgentConfig from "./agent-config";
import AgentVersionManage from "./AgentVersionManage";
import AgentDebugPanel from "./agent-debug";
import { Nl2AgentChatPanel } from "../newchat/assistant-ui/nl2agent-chat-panel";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { useAgentStore } from "@/stores/agentStore";
import { searchAgentInfo } from "@/services/agentConfigService";
import log from "@/lib/logger";
import type { Nl2AgentStateEvent } from "../newchat/adapter/remote-chat-model-adapter";

interface PanelCardProps {
  title: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
  icon?: ReactNode;
}

function PanelCard({
  title,
  children,
  className = "",
  action,
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
        </div>
        {action}
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
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] =
    useState(false);
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const permissionReadOnly = useAgentStore((state) => state.isReadOnly);
  const {
    isComposerDisabled,
    completionSyncFailed,
    markCompletionSynced,
    markCompletionSyncFailed,
    markGenerationCompleted,
    markPromptGenerationFailed,
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
    (agentId: number) => {
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
    [queryClient]
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
      void enqueueSnapshotRefresh(event.agent_id);
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
              action={
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
            className={
              !isGenerationVisible && isDebugVisible ? "flex-[1]" : "flex-[2]"
            }
            action={
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
                isDebugVisible={isDebugVisible}
                onToggleDebug={() => setIsDebugVisible((visible) => !visible)}
              />
            </div>
          </PanelCard>

          {isDebugVisible && (
            <PanelCard
              title={t("agent.page.panel.debug")}
              className={!isGenerationVisible ? "flex-1" : "flex-[1]"}
              action={
                <button
                  type="button"
                  aria-label={t("agent.page.panel.debug.closeAria")}
                  onClick={() => setIsDebugVisible(false)}
                  className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                >
                  <X size={18} />
                </button>
              }
            >
              <div className="min-h-0 flex-1 overflow-hidden">
                <AgentDebugPanel />
              </div>
            </PanelCard>
          )}
        </div>

        {isShowVersionManagePanel && (
          <aside className="h-full w-[360px] shrink-0 overflow-hidden">
            <AgentVersionManage
              onClose={() => setIsShowVersionManagePanel(false)}
            />
          </aside>
        )}
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
