"use client";

import { Filter } from "lucide-react";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";

import { StandardTable } from "@/components/common/StandardTable";
import AgentConfigActions from "./agent-config-actions";
import type { Agent } from "@/types/agentConfig";

export interface AgentListTableProps {
  agents: Agent[];
  onOpen: (agent: Agent) => void;
  onConfigure: (agentId: number) => void;
  onPublish: (agentId: number) => void;
  onManageVersions: (agentId: number) => void;
}

export function formatAgentUpdateTime(updateTime?: string): string | null {
  if (!updateTime) return null;

  const isoDate = /^\d{4}-\d{2}-\d{2}/.exec(updateTime)?.[0];
  if (isoDate) {
    const parsedDate = new Date(`${isoDate}T00:00:00.000Z`);
    return !Number.isNaN(parsedDate.getTime()) &&
      parsedDate.toISOString().startsWith(isoDate)
      ? isoDate
      : null;
  }

  const parsed = new Date(updateTime);
  if (Number.isNaN(parsed.getTime())) return null;
  return [parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate()]
    .map((part, index) =>
      index === 0 ? String(part) : String(part).padStart(2, "0")
    )
    .join("-");
}

export default function AgentListTable({
  agents,
  onOpen,
  onConfigure,
  onPublish,
  onManageVersions,
}: AgentListTableProps) {
  const { t } = useTranslation("common");

  const columns: ColumnsType<Agent> = [
    {
      title: t("agentConfig.list.column.name"),
      key: "name",
      width: "42.7%",
      ellipsis: true,
      render: (_, agent) => {
        const title = agent.display_name || agent.name;
        return (
          <button
            type="button"
            className="block max-w-full truncate text-left text-[#191919] hover:text-[#0067d1]"
            title={title}
            onClick={() => onOpen(agent)}
          >
            {title}
          </button>
        );
      },
    },
    {
      title: (
        <span className="inline-flex items-center gap-1">
          {t("agentConfig.list.column.type")}
          <Filter
            className="size-3 shrink-0 text-[#777777]"
            aria-hidden="true"
          />
        </span>
      ),
      key: "type",
      width: "3.9%",
      ellipsis: true,
      render: (_, agent) => {
        const category = agent.tags?.[0];
        return (
          <span className="block truncate" title={category || undefined}>
            {category || "-"}
          </span>
        );
      },
    },
    {
      title: t("agentConfig.list.column.description"),
      dataIndex: "description",
      key: "description",
      width: "23.3%",
      ellipsis: true,
      render: (description: string | undefined) => (
        <span className="block truncate" title={description || undefined}>
          {description || "-"}
        </span>
      ),
    },
    {
      title: t("agentConfig.list.column.status"),
      key: "status",
      width: "9.9%",
      render: (_, agent) => {
        const isOnline = Boolean(agent.current_version_no);
        return (
          <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
            <span
              className={`size-1.5 rounded-full ${isOnline ? "bg-[#2070f3]" : "bg-[#aeaeae]"}`}
              aria-hidden="true"
            />
            {t(
              isOnline ? "agentConfig.list.online" : "agentConfig.list.offline"
            )}
          </span>
        );
      },
    },
    {
      title: t("agentConfig.list.column.creator"),
      dataIndex: "author",
      key: "creator",
      width: "4.4%",
      ellipsis: true,
      render: (author: string | undefined) => author?.trim() || "-",
    },
    {
      title: (
        <span className="inline-flex items-center gap-1">
          {t("agentConfig.list.column.updatedAt")}
          <Filter
            className="size-3 shrink-0 text-[#777777]"
            aria-hidden="true"
          />
        </span>
      ),
      key: "updatedAt",
      width: "5.6%",
      ellipsis: true,
      render: (_, agent) => formatAgentUpdateTime(agent.update_time) || "-",
    },
    {
      title: t("agentConfig.list.column.actions"),
      key: "actions",
      width: "10.2%",
      render: (_, agent) => {
        const agentId = Number(agent.id);
        const isOnline = Boolean(agent.current_version_no);
        return (
          <div className="flex min-w-0 items-center gap-2 whitespace-nowrap text-[12px] leading-[18px]">
            <button
              type="button"
              className="text-[#0067d1] hover:text-[#0052a8]"
              onClick={() => onConfigure(agentId)}
            >
              {t("agentConfig.list.configure")}
            </button>
            {!isOnline ? (
              <button
                type="button"
                className="text-[#0067d1] hover:text-[#0052a8]"
                onClick={() => onPublish(agentId)}
              >
                {t("agentConfig.list.publish")}
              </button>
            ) : null}
            <AgentConfigActions
              agentId={agentId}
              readOnly={agent.permission === "READ_ONLY"}
              variant="table"
              onManageVersions={onManageVersions}
            />
          </div>
        );
      },
    },
  ];

  return (
    <div
      data-testid="agent-list-table-scroll"
      className="h-auto max-h-[500px] min-h-0 w-full min-w-0 overflow-auto"
    >
      <StandardTable<Agent>
        className="min-w-[1120px] [&_.ant-table-thead>tr>th]:sticky [&_.ant-table-thead>tr>th]:top-0 [&_.ant-table-thead>tr>th]:z-10 [&_.ant-table-thead>tr>th:nth-child(2)]:!px-2 [&_.ant-table-thead>tr>th:nth-child(6)]:!px-2"
        columns={columns}
        dataSource={agents}
        pagination={false}
        rowKey="id"
        tableLayout="fixed"
      />
    </div>
  );
}
