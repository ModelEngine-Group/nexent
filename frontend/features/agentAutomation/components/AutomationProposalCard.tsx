"use client";

import { Button, Space, Tag } from "antd";
import { Bot, CalendarClock, Loader2, Pencil, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AgentAutomationProposalData } from "@/types/agentAutomation";

function formatInterval(
  seconds: number,
  t: ReturnType<typeof useTranslation>["t"]
): string {
  const values = [
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
    [1, "second"],
  ] as const;
  const [divisor, unit] =
    values.find(([candidate]) => seconds % candidate === 0) || values[3];
  const count = seconds / divisor;
  return t(`agentAutomation.proposal.units.${unit}${count === 1 ? "" : "s"}`, {
    count,
  });
}

function formatSchedule(
  proposal: AgentAutomationProposalData,
  language: string,
  t: ReturnType<typeof useTranslation>["t"]
): string | null {
  const trigger = proposal.task?.schedule_trigger;
  if (!trigger) return null;
  if (trigger.rule_type === "INTERVAL" && trigger.interval_seconds) {
    return t("agentAutomation.proposal.intervalSchedule", {
      interval: formatInterval(trigger.interval_seconds, t),
      timezone: trigger.timezone,
    });
  }
  if (trigger.rule_type === "CRON" && trigger.cron_expr) {
    return `Cron ${trigger.cron_expr} (${trigger.timezone})`;
  }
  try {
    const formatted = new Intl.DateTimeFormat(
      language === "zh" ? "zh-CN" : "en-US",
      {
        timeZone: trigger.timezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      }
    ).format(new Date(trigger.start_at));
    return `${formatted} (${trigger.timezone})`;
  } catch {
    return `${trigger.start_at} (${trigger.timezone})`;
  }
}

interface AutomationProposalCardProps {
  proposal: AgentAutomationProposalData;
  onConfirm?: () => void;
  onEdit?: () => void;
  onConfigureAgent?: () => void;
  confirming?: boolean;
}

export default function AutomationProposalCard({
  proposal,
  onConfirm,
  onEdit,
  onConfigureAgent,
  confirming = false,
}: AutomationProposalCardProps) {
  const { t, i18n } = useTranslation("common");
  if (proposal.ui_state === "PREPARING") {
    return (
      <div
        className="border border-blue-200 rounded-md p-4 bg-blue-50/60"
        role="status"
        aria-live="polite"
      >
        <div className="flex items-start gap-3">
          <Loader2 size={20} className="mt-0.5 text-blue-600 animate-spin" />
          <div>
            <div className="font-medium text-blue-900">
              {t("agentAutomation.proposal.preparingTitle")}
            </div>
            <div className="text-sm text-blue-700 mt-1">
              {t("agentAutomation.proposal.preparingDescription")}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const matched = proposal.capability_resolution?.matched_capabilities || [];
  const missing = proposal.capability_resolution?.missing_capabilities || [];
  const schedule = formatSchedule(proposal, i18n.language, t);
  const agentSnapshot = proposal.capability_resolution?.agent_snapshot;
  const snapshotAgentName =
    typeof agentSnapshot?.display_name === "string"
      ? agentSnapshot.display_name
      : typeof agentSnapshot?.name === "string"
        ? agentSnapshot.name
        : undefined;
  const agentName = proposal.task?.agent_name || snapshotAgentName;
  const editable = Boolean(onEdit);
  const openEditor = () => {
    if (editable) onEdit?.();
  };

  return (
    <div
      className={`border rounded-md p-4 bg-white transition-colors ${
        editable
          ? "border-gray-200 cursor-pointer hover:border-blue-400 hover:bg-blue-50/20"
          : "border-gray-200"
      }`}
      role={editable ? "button" : undefined}
      tabIndex={editable ? 0 : undefined}
      aria-label={
        editable ? t("agentAutomation.proposal.clickToEdit") : undefined
      }
      onClick={openEditor}
      onKeyDown={(event) => {
        if (editable && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          openEditor();
        }
      }}
    >
      <div className="flex items-start gap-3">
        <CalendarClock size={20} className="mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-3">
            <div className="font-medium">
              {proposal.task?.title ||
                t("agentAutomation.proposal.defaultTitle")}
            </div>
            {editable && (
              <Button
                type="text"
                size="small"
                icon={<Pencil size={14} />}
                onClick={(event) => {
                  event.stopPropagation();
                  openEditor();
                }}
              >
                {t("agentAutomation.proposal.edit")}
              </Button>
            )}
          </div>
          <div className="text-sm text-gray-600 mt-1 whitespace-pre-wrap">
            {proposal.task?.instruction}
          </div>
          {agentName && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-gray-500">
              <Bot size={14} aria-hidden />
              <span>
                {t("agentAutomation.proposal.agent", { name: agentName })}
              </span>
            </div>
          )}
          {schedule && (
            <div className="text-xs text-gray-500 mt-2 rounded bg-gray-50 px-2 py-1.5">
              {t("agentAutomation.proposal.schedule")}: {schedule}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {matched.map((capability) => (
              <Tag
                key={capability.binding_ref || capability.name}
                color="green"
              >
                {capability.display_name || capability.name}
              </Tag>
            ))}
            {missing.map((capability) => (
              <Tag key={capability.name} color="red">
                {t("agentAutomation.proposal.missingCapability", {
                  name: capability.name,
                })}
              </Tag>
            ))}
          </div>
          {missing.length > 0 && (
            <div className="text-xs text-red-500 mt-2">
              {t("agentAutomation.proposal.capabilityHint")}
            </div>
          )}
          {proposal.confirmed_task_id && (
            <div className="text-xs text-green-600 mt-2">
              {t("agentAutomation.proposal.confirmed", {
                id: proposal.confirmed_task_id,
              })}
            </div>
          )}
          <Space className="mt-4" onClick={(event) => event.stopPropagation()}>
            {proposal.executable && !proposal.confirmed_task_id ? (
              <Button
                type="primary"
                size="small"
                loading={confirming}
                onClick={onConfirm}
              >
                {t("agentAutomation.proposal.create")}
              </Button>
            ) : !proposal.confirmed_task_id ? (
              <Button
                size="small"
                icon={<Settings size={14} />}
                onClick={onConfigureAgent}
              >
                {t("agentAutomation.proposal.configureAgent")}
              </Button>
            ) : null}
          </Space>
        </div>
      </div>
    </div>
  );
}
