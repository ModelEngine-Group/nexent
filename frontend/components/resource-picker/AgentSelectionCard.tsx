// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createElement,
  useId,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { Avatar } from "antd";
import { Clock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import {
  getAgentIcon,
  getAgentUploadedIconRevision,
} from "@/lib/chat/agentIconUtils";
import type { TagAssignmentValue } from "@/types/tagManagement";
import { API_ENDPOINTS } from "@/services/api";
import { formatDate } from "@/lib/date";
import type { Agent } from "@/types/agentConfig";
import type { AgentCardItem } from "./types";
import { CheckMark } from "./ResourceDrawer";
import { ResourceAssignedTags } from "./ResourceAssignedTags";
import styles from "./ResourcePickerDrawer.module.css";

export function toLocalCard(agent: Agent): AgentCardItem {
  const updatedAt =
    agent.update_time || agent.create_time
      ? formatDate(agent.update_time ?? agent.create_time)
      : undefined;
  return {
    id: String(agent.id),
    agentId: Number(agent.id),
    tagResourceId: String(agent.id),
    iconUrl:
      agent.icon_url?.trim() && Number(agent.id) > 0
        ? API_ENDPOINTS.agent.icon(
            Number(agent.id),
            getAgentUploadedIconRevision(agent.icon_url)
          )
        : undefined,
    name: agent.display_name || agent.name,
    description: agent.description ?? "",
    updatedAt,
    version:
      agent.version_name?.trim() ||
      agent.version_label?.trim() ||
      (agent.current_version_no != null
        ? String(agent.current_version_no)
        : undefined),
    tags: agent.tags ?? [],
  };
}

export function AgentSelectionCard({
  item,
  selected,
  onToggle,
  icon,
  disabled = false,
  refreshKey,
  assignments,
  disabledReason,
  actions,
}: {
  item: AgentCardItem;
  selected: boolean;
  onToggle: () => void;
  icon: ReactNode;
  disabled?: boolean;
  refreshKey?: number;
  assignments?: TagAssignmentValue[];
  disabledReason?: string;
  actions?: ReactNode;
}) {
  const { t } = useTranslation("common");
  const reasonId = useId();
  const [failedIconSource, setFailedIconSource] = useState<string>();
  const iconSource =
    failedIconSource === item.iconUrl ? undefined : item.iconUrl;
  const agentId = item.agentId ?? Number(item.id);
  const fallbackIcon =
    Number.isInteger(agentId) && agentId >= 0
      ? createElement(getAgentIcon({ agent_id: agentId }), {
          size: 20,
          "aria-hidden": true,
        })
      : icon;
  return (
    <div
      data-resource-agent-card
      role="option"
      aria-label={item.name}
      aria-selected={selected}
      aria-disabled={disabled}
      aria-describedby={disabledReason ? reasonId : undefined}
      tabIndex={disabled ? -1 : 0}
      onClick={() => {
        if (!disabled) onToggle();
      }}
      onKeyDown={(event) => {
        if (
          !disabled &&
          event.target === event.currentTarget &&
          (event.key === "Enter" || event.key === " ")
        ) {
          event.preventDefault();
          onToggle();
        }
      }}
      className={cn(
        styles.agentCard,
        !disabled &&
          "cursor-pointer hover:!shadow-[inset_0_0_0_1px_#0067d1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        selected ? styles.agentCardSelected : "bg-white",
        disabled && "cursor-not-allowed opacity-50"
      )}
    >
      <div
        className="absolute right-6 top-7"
        onClick={(event) => event.stopPropagation()}
      >
        <CheckMark
          checked={selected}
          disabled={disabled}
          onToggle={onToggle}
          ariaLabel={item.name}
        />
      </div>
      <div className="flex min-h-10 shrink-0 items-start gap-3 pr-6">
        <Avatar
          shape="square"
          size={40}
          src={iconSource}
          onError={() => {
            setFailedIconSource(item.iconUrl);
            return false;
          }}
          icon={fallbackIcon}
          className={cn(
            "shrink-0 !rounded-[8px]",
            iconSource ? "!bg-white" : "!bg-primary/10 !text-primary"
          )}
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="min-w-0 truncate text-[16px] font-medium leading-[24px] text-[#191919]">
            {item.name}
          </span>
          {item.version && (
            <span
              className={styles.agentVersion}
              title={`${t("agent.version")}: ${item.version}`}
            >
              {t("agent.version")}: {item.version}
            </span>
          )}
        </div>
      </div>
      <p className="line-clamp-2 h-[42px] shrink-0 text-[12px] font-normal leading-[20px] text-[#777777]">
        {item.description}
      </p>
      <div className="flex flex-wrap items-center gap-1">
        {item.tagResourceId ? (
          <ResourceAssignedTags
            resourceType="agent"
            resourceId={item.tagResourceId}
            tags={item.tags}
            refreshKey={refreshKey}
            assignments={assignments}
          />
        ) : (
          <div className="flex flex-wrap gap-1">
            {item.tags?.map((tag) => (
              <span
                key={tag}
                className="rounded bg-muted px-1.5 text-xs text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
      {disabledReason && (
        <p id={reasonId} className="text-xs text-destructive">
          {disabledReason}
        </p>
      )}
      <div className={styles.agentMetadata}>
        {item.updatedAt && (
          <span className={styles.agentUpdatedAt}>
            <Clock size={14} className="shrink-0" />
            {t("agentConfig.list.updatedAt", { date: item.updatedAt })}
          </span>
        )}
        {actions && (
          <div className="ml-auto" onClick={(event) => event.stopPropagation()}>
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}

export function AgentSelectionGrid({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="listbox"
      aria-multiselectable="true"
      {...props}
      className={cn(styles.agentGrid, className)}
    />
  );
}
