"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { Sparkles, X } from "lucide-react";
import { useSearchParams } from "next/navigation";

import AgentSelectorHeader from "./components/agent-selector-header";
import AgentConfig from "./agent-config";
import AgentVersionManage from "./AgentVersionManage";
import AgentDebugPanel from "./agent-debug";
import { Nl2AgentChatPanel } from "../newchat/assistant-ui/nl2agent-chat-panel";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { useAgentStore } from "@/stores/agentStore";
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
  const searchParams = useSearchParams();
  const [isGenerationVisible, setIsGenerationVisible] = useState(true);
  const [isDebugVisible, setIsDebugVisible] = useState(false);
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] =
    useState(false);
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const permissionReadOnly = useAgentStore((state) => state.isReadOnly);
  const {
    isComposerDisabled,
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

  const handleStateEvent = useCallback(
    (event: Nl2AgentStateEvent) => {
      markPromptGenerationFailed(event.agent_id, event.failed_fields);
    },
    [markPromptGenerationFailed]
  );

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
