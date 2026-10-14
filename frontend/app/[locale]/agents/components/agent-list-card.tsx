// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Clock3 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StandardButton } from "@/components/common/StandardButton";
import type { Agent } from "@/types/agentConfig";

import AgentAvatar from "./agent-avatar";
import AgentConfigActions from "./agent-config-actions";
import AgentListIndicators from "./agent-list-indicators";

export interface AgentListCardProps {
  agent: Agent;
  onOpen: (agent: Agent) => void;
  onConfigure: (agentId: number) => void;
  onPublish: (agentId: number) => void;
  onManageVersions: (agentId: number) => void;
}

export function formatAgentListDate(agent: Agent): {
  date: string;
  isUpdate: boolean;
} | null {
  const source = agent.update_time || agent.create_time;
  if (!source) return null;

  const isoDate = /^\d{4}-\d{2}-\d{2}/.exec(source)?.[0];
  if (isoDate) return { date: isoDate, isUpdate: Boolean(agent.update_time) };

  const parsed = new Date(source);
  if (Number.isNaN(parsed.getTime())) return null;
  return {
    date: parsed.toLocaleDateString("sv-SE"),
    isUpdate: Boolean(agent.update_time),
  };
}

export default function AgentListCard({
  agent,
  onOpen,
  onConfigure,
  onPublish,
  onManageVersions,
}: AgentListCardProps) {
  const { t } = useTranslation("common");
  const title = agent.display_name || agent.name;
  const category = agent.tags?.[0];
  const date = formatAgentListDate(agent);
  const agentId = Number(agent.id);

  return (
    <article className="group relative flex h-[148px] min-w-0 flex-col justify-between rounded-[12px] bg-white px-6 py-4 ring-1 ring-[rgba(201,201,201,0.4)] hover:ring-[#0067d1] focus-within:ring-[#0067d1]">
      <button
        type="button"
        onClick={() => onOpen(agent)}
        data-testid="agent-card-body"
        className="flex h-[86px] min-w-0 shrink-0 cursor-pointer flex-col text-left"
        aria-label={title}
      >
        <div className="flex h-10 min-w-0 items-center gap-3 pr-7">
          <AgentAvatar agent={agent} size={40} iconSize={20} />
          <span className="min-w-0 truncate text-[16px] font-medium leading-6 ![letter-spacing:0px] text-[#191919]">
            {title}
          </span>
          {category ? (
            <span className="h-[22px] max-w-[35%] shrink-0 truncate rounded-[4px] border border-solid border-[#b3b3b3] bg-[rgba(25,25,25,0.05)] px-2 py-0.5 text-[12px] leading-4 ![letter-spacing:0px] text-[#191919]">
              {category}
            </span>
          ) : null}
          <AgentListIndicators agent={agent} />
        </div>
        <p className="mt-1 h-[42px] line-clamp-2 w-full text-[12px] font-normal leading-5 ![letter-spacing:0px] text-[#777777]">
          {agent.description || t("agentRepository.card.noDescription")}
        </p>
      </button>

      <div
        data-testid="agent-card-footer"
        className="flex h-[18px] shrink-0 items-center gap-[clamp(12px,calc(100%_-_314px),78px)] text-[12px] leading-[18px] ![letter-spacing:0px] group-hover:gap-2 group-focus-within:gap-2"
      >
        <span className="inline-flex min-w-0 items-center gap-1 text-[rgba(25,25,25,0.7)] group-hover:flex-1 group-focus-within:flex-1">
          <Clock3 className="size-3 shrink-0" aria-hidden="true" />
          {date ? (
            <span className="truncate">
              {t(
                date.isUpdate
                  ? "agentConfig.list.updatedAt"
                  : "agentConfig.list.createdAt",
                { date: date.date }
              )}
            </span>
          ) : (
            <span>-</span>
          )}
        </span>
        <span
          data-testid="agent-card-status"
          className="inline-flex shrink-0 items-center gap-1 text-[#191919] group-hover:hidden group-focus-within:hidden"
        >
          <span
            data-testid="agent-card-status-dot"
            aria-hidden="true"
            className={`size-2 shrink-0 rounded-full ${agent.current_version_no ? "bg-[#0067d1]" : "bg-[#d9d9d9]"}`}
          />
          {agent.current_version_no
            ? t("agentConfig.list.online")
            : t("agentConfig.list.offline")}
        </span>
        <div className="hidden shrink-0 items-center gap-2 self-end group-hover:flex group-focus-within:flex">
          <StandardButton
            variant="primary"
            onClick={() => onConfigure(agentId)}
          >
            {t("agentConfig.list.configure")}
          </StandardButton>
          <StandardButton
            disabled={agent.permission === "READ_ONLY"}
            onClick={() => onPublish(agentId)}
          >
            {t("agentConfig.list.publish")}
          </StandardButton>
        </div>
      </div>

      <div className="absolute right-[14px] top-[6px]">
        <AgentConfigActions
          agentId={agentId}
          agentName={title}
          readOnly={agent.permission === "READ_ONLY"}
          variant="menu"
          onManageVersions={onManageVersions}
        />
      </div>
    </article>
  );
}
