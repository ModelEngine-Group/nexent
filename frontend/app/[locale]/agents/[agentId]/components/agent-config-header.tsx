// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { Hint } from "@/components/common/Hint";
import { createElement, useState } from "react";
import { useTranslation } from "react-i18next";
import { Avatar } from "antd";
import { LockOpen, Send } from "lucide-react";
import { Button as ProjectButton } from "@/components/common/Button";
import { API_ENDPOINTS } from "@/services/api";
import {
  getAgentIcon,
  getAgentUploadedIconRevision,
} from "@/lib/chat/agentIconUtils";
import { useAgentStore, type AgentDraft } from "@/stores/agentStore";
interface AgentConfigHeaderProps {
  agent: AgentDraft;
  agentId: number | null;
  readOnly: boolean;
  debugVisible: boolean;
  publicationVisible?: boolean;
  onPublication?: () => void;
  canManualUnlock: boolean;
  onConfigure: () => void;
  onDebug: () => void;
  onPublish: () => void;
  onManualUnlock: () => void;
  actionAreaRef?: React.Ref<HTMLDivElement>;
  published?: boolean;
}
export function AgentConfigHeader({
  agent,
  agentId,
  readOnly,
  debugVisible,
  publicationVisible = false,
  onPublication,
  canManualUnlock,
  onConfigure,
  onDebug,
  onPublish,
  onManualUnlock,
  actionAreaRef,
  published = false,
}: AgentConfigHeaderProps) {
  const { t } = useTranslation("common");
  const [failedIcon, setFailedIcon] = useState<string>();
  const savedAt = useAgentStore((state) => state.lastSavedAt);
  const saveFailed = useAgentStore((state) =>
    Boolean(state.saveError || state.lastSaveFailed)
  );
  const savePending = useAgentStore(
    (state) =>
      (state.queue?.length ?? 0) > 0 ||
      (state.editedAgent !== state.savedAgent &&
        JSON.stringify(state.editedAgent) !== JSON.stringify(state.savedAgent))
  );
  const iconSource =
    agentId !== null && agent.icon_url
      ? API_ENDPOINTS.agent.icon(
          agentId,
          getAgentUploadedIconRevision(agent.icon_url)
        )
      : undefined;
  return (
    <div
      ref={actionAreaRef}
      data-testid="agent-config-header"
      className="relative flex min-h-[74px] shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-7 2xl:grid 2xl:grid-cols-[1fr_auto_1fr]"
    >
      <span
        aria-hidden="true"
        data-agent-guide="workflow"
        className="pointer-events-none absolute inset-y-0 left-0 right-0 2xl:left-[31.2%]"
      />
      <div className="flex min-w-0 max-w-full items-center gap-3">
        <Avatar
          size={50}
          shape="square"
          src={iconSource !== failedIcon ? iconSource : undefined}
          icon={createElement(getAgentIcon({ agent_id: agentId ?? 0 }), {
            size: 28,
          })}
          className="shrink-0 !flex !items-center !justify-center !rounded-lg !bg-primary/10 !text-primary !border !border-solid !border-[#c9c9c9]"
          onError={() => {
            setFailedIcon(iconSource);
            return false;
          }}
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 items-center gap-2">
            <span
              title={agent.display_name || agent.name}
              className="min-w-0 truncate text-xl font-medium leading-7 text-[#191919] [font-family:'HarmonyOS_Sans_SC',sans-serif]"
            >
              {agent.display_name || agent.name}
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs font-normal leading-[22px] text-[#808080]">
            <span>
              {saveFailed
                ? t("agent.highFidelity.saveFailed")
                : savePending
                  ? t("agent.highFidelity.savePending")
                  : savedAt
                    ? t("agent.highFidelity.saved", {
                        time: new Date(savedAt).toLocaleTimeString(undefined, {
                          hour12: false,
                        }),
                      })
                    : t("agent.highFidelity.savedWithoutTime")}
            </span>
            <span className="inline-flex items-center gap-1 text-[#191919]">
              <span className="size-1 rounded-full bg-primary" />
              {t(
                published
                  ? "agent.highFidelity.published"
                  : "agent.highFidelity.unpublished"
              )}
            </span>
          </div>
        </div>
      </div>
      <div
        className="flex shrink-0 items-center gap-1 rounded-[6px] bg-[rgba(25,25,25,0.05)] p-[2px] [&_[data-slot=button]]:!h-7 [&_[data-slot=button]]:!min-w-[102px] [&_[data-slot=button]]:!whitespace-nowrap [&_[data-slot=button]]:!px-4 [&_[data-slot=button]]:!py-[3px] [&_[data-slot=button]]:!text-sm [&_[data-slot=button]]:!font-normal [&_[data-slot=button]]:!leading-[22px] [&_[data-slot=button]]:[font-family:'HarmonyOS_Sans_SC',sans-serif]"
        role="group"
        aria-label={t("agent.highFidelity.workflowModes")}
      >
        <ProjectButton
          aria-pressed={!debugVisible && !publicationVisible}
          disabled={false}
          onClick={onConfigure}
          className={
            !debugVisible && !publicationVisible
              ? "!rounded-[4px] !bg-white !text-primary !shadow-[0_1px_6px_0_rgba(0,0,0,0.08)]"
              : "!text-[#777777]"
          }
          variant="ghost"
          size="sm"
        >
          {t("agent.highFidelity.configureMode")}
        </ProjectButton>
        <ProjectButton
          aria-pressed={debugVisible}
          disabled={agentId === null}
          onClick={onDebug}
          className={
            debugVisible
              ? "!rounded-[4px] !bg-white !text-primary !shadow-[0_1px_6px_0_rgba(0,0,0,0.08)]"
              : "!text-[#777777]"
          }
          variant="ghost"
          size="sm"
        >
          {t("agent.highFidelity.debugMode")}
        </ProjectButton>
        <ProjectButton
          aria-pressed={publicationVisible}
          disabled={agentId === null}
          onClick={onPublication}
          className={
            publicationVisible
              ? "!rounded-[4px] !bg-white !text-primary !shadow-[0_1px_6px_0_rgba(0,0,0,0.08)]"
              : "!text-[#777777]"
          }
          variant="ghost"
          size="sm"
        >
          {t("agent.highFidelity.publishMode")}
        </ProjectButton>
      </div>
      <div className="flex shrink-0 items-center gap-2 justify-self-end">
        {canManualUnlock && (
          <Hint content={t("agent.page.panel.nl2agent.manualUnlockAction")}>
            <ProjectButton
              aria-label={t("agent.page.panel.nl2agent.manualUnlockAction")}
              icon={<LockOpen size={16} />}
              onClick={onManualUnlock}
              variant="ghost"
              size="sm"
            />
          </Hint>
        )}
        <ProjectButton
          variant="default"
          icon={<Send size={16} />}
          disabled={agentId === null || readOnly}
          onClick={onPublish}
          size="sm"
        >
          {t("agent.config.button.publish")}
        </ProjectButton>
      </div>
    </div>
  );
}
