"use client";

import { Clock3 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StandardButton } from "@/components/common/StandardButton";
import type { Agent } from "@/types/agentConfig";

import AgentAvatar from "./agent-avatar";
import AgentConfigActions from "./agent-config-actions";

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
    <article className="group relative flex h-[148px] min-w-0 flex-col justify-between rounded-[12px] border border-solid border-[rgba(201,201,201,0.4)] bg-white px-6 py-4 hover:border-[#0067d1] focus-within:border-[#0067d1]">
      <button
        type="button"
        className="min-w-0 flex-1 cursor-pointer text-left"
        onClick={() => onOpen(agent)}
        aria-label={title}
      >
        <div className="flex h-10 min-w-0 items-center gap-3 pr-7">
          <AgentAvatar agent={agent} size={40} iconSize={20} />
          <span className="min-w-0 truncate text-[16px] font-medium leading-6 ![letter-spacing:0px] text-[#191919]">
            {title}
          </span>
          {category ? (
            <span className="h-[22px] shrink-0 rounded-[4px] border border-solid border-[#b3b3b3] bg-[rgba(25,25,25,0.05)] px-2 py-0.5 text-[12px] leading-4 ![letter-spacing:0px] text-[#191919]">
              {category}
            </span>
          ) : null}
        </div>
        <p className="mt-1 line-clamp-2 w-full text-[12px] font-normal leading-5 ![letter-spacing:0px] text-[#777777]">
          {agent.description || t("agentRepository.card.noDescription")}
        </p>
      </button>

      <div className="flex h-[18px] shrink-0 items-center gap-4 text-[12px] leading-[18px] ![letter-spacing:0px]">
        <span className="inline-flex min-w-0 items-center gap-1 text-[rgba(25,25,25,0.7)]">
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
        <span className="text-[#191919] group-hover:hidden group-focus-within:hidden">
          {agent.current_version_no
            ? t("agentConfig.list.online")
            : t("agentConfig.list.offline")}
        </span>
      </div>

      <div
        className="absolute right-4 top-3"
        onClick={(event) => event.stopPropagation()}
      >
        <AgentConfigActions
          agentId={agentId}
          readOnly={agent.permission === "READ_ONLY"}
          variant="menu"
          onManageVersions={onManageVersions}
        />
      </div>
      <div className="absolute bottom-4 right-6 hidden items-center gap-2 group-hover:flex group-focus-within:flex">
        <StandardButton variant="primary" onClick={() => onConfigure(agentId)}>
          {t("agentConfig.list.configure")}
        </StandardButton>
        <StandardButton
          disabled={agent.permission === "READ_ONLY"}
          onClick={() => onPublish(agentId)}
        >
          {t("agentConfig.list.publish")}
        </StandardButton>
      </div>
    </article>
  );
}
