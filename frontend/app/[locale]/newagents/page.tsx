"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { App, Button } from "antd";
import { Sparkles, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import AgentSelectorHeader from "./components/agent-selector-header";
import AgentConfig from "./agent-config";
import AgentVersionManage from "./AgentVersionManage";
import AgentDebugPanel from "./agent-debug";
import { Nl2AgentChatPanel } from "../newchat/assistant-ui/nl2agent-chat-panel";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { searchAgentInfo } from "@/services/agentConfigService";
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
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isGenerationVisible, setIsGenerationVisible] = useState(true);
  const [isDebugVisible, setIsDebugVisible] = useState(false);
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] =
    useState(false);
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const permissionReadOnly = useAgentStore((state) => state.isReadOnly);
  const initializeAgent = useAgentStore((state) => state.initialize);
  const {
    agentId: flowAgentId,
    markDraftCreated,
    resetFlow,
    sessionGeneration,
  } = useNl2AgentFlow();
  const previousAgentIdRef = useRef<number | null>(currentAgentId);
  const promotedAgentIdRef = useRef<number | null>(null);
  const synchronizingCreatedIdsRef = useRef(new Set<number>());
  const requestedAgentId = Number(searchParams.get("agent_id"));
  const isRequestedAgentLoading =
    Number.isInteger(requestedAgentId) &&
    requestedAgentId > 0 &&
    requestedAgentId !== currentAgentId;

  useEffect(() => {
    if (previousAgentIdRef.current === currentAgentId) return;

    const isDraftPromotion =
      previousAgentIdRef.current === null &&
      promotedAgentIdRef.current === currentAgentId;
    previousAgentIdRef.current = currentAgentId;
    promotedAgentIdRef.current = null;
    if (!isDraftPromotion) {
      resetFlow(currentAgentId);
    }
  }, [currentAgentId, resetFlow]);

  const synchronizeCreatedDraft = useCallback(
    async (event: Nl2AgentStateEvent) => {
      if (synchronizingCreatedIdsRef.current.has(event.agent_id)) return;
      synchronizingCreatedIdsRef.current.add(event.agent_id);

      const startingAgentId = useAgentStore.getState().currentAgentId;
      if (startingAgentId !== null && startingAgentId !== event.agent_id) {
        return;
      }

      markDraftCreated(event.agent_id);
      const nextSearchParams = new URLSearchParams(searchParams.toString());
      nextSearchParams.set("agent_id", String(event.agent_id));
      router.replace(`${pathname}?${nextSearchParams.toString()}`);

      try {
        const result = await searchAgentInfo(event.agent_id, undefined, 0);
        if (!result.success || !result.data) {
          throw new Error(result.message);
        }
        if (useAgentStore.getState().currentAgentId !== startingAgentId) {
          return;
        }

        if (startingAgentId === null) {
          promotedAgentIdRef.current = event.agent_id;
        }
        initializeAgent(result.data);
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["agents"] }),
          queryClient.invalidateQueries({
            queryKey: ["agentInfo", event.agent_id],
          }),
        ]);
      } catch {
        synchronizingCreatedIdsRef.current.delete(event.agent_id);
        message.error(
          t(
            "nl2agent.draft.syncFailed",
            "The Agent draft was created, but its details could not be loaded."
          )
        );
      }
    },
    [
      initializeAgent,
      markDraftCreated,
      message,
      pathname,
      queryClient,
      router,
      searchParams,
      t,
    ]
  );

  const handleStateEvent = useCallback(
    (event: Nl2AgentStateEvent) => {
      void synchronizeCreatedDraft(event);
    },
    [synchronizeCreatedDraft]
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
              <div className="min-h-0 flex-1 overflow-hidden">
                <Nl2AgentChatPanel
                  key={sessionGeneration}
                  agentId={currentAgentId ?? flowAgentId}
                  disabled={
                    isRequestedAgentLoading ||
                    (currentAgentId !== null && permissionReadOnly)
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
