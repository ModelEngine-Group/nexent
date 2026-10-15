// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState } from "react";
import { ConfigProvider, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";

import AgentConfigActions from "./agent-config-actions";
import AgentTableHeader, {
  type AgentTableHeaderProps,
} from "./agent-list-table-header";
import AgentListIndicators from "./agent-list-indicators";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import type { Agent } from "@/types/agentConfig";

import {
  DEFAULT_AGENT_COLUMN_WIDTHS,
  MIN_COLUMN_WIDTHS,
  resizeAgentColumns,
  type AgentColumnWidths,
  type AgentColumnKey,
} from "./agent-table-column-widths";
export { DEFAULT_AGENT_COLUMN_WIDTHS } from "./agent-table-column-widths";

export interface AgentListTableProps {
  agents: Agent[];
  columnWidths?: AgentColumnWidths;
  onColumnWidthsChange?: (widths: AgentColumnWidths) => void;
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
  columnWidths,
  onColumnWidthsChange,
  onOpen,
  onConfigure,
  onPublish,
  onManageVersions,
}: AgentListTableProps) {
  const { t } = useTranslation("common");
  const containerRef = useRef<HTMLDivElement>(null);
  const [bodyHeight, setBodyHeight] = useState<number>();
  const [containerWidth, setContainerWidth] = useState(0);
  const [localWidths, setLocalWidths] = useState(DEFAULT_AGENT_COLUMN_WIDTHS);
  const baseWidths = columnWidths ?? localWidths;
  const baseTotal = Object.values(baseWidths).reduce(
    (sum, width) => sum + width,
    0
  );
  const widths = {
    ...baseWidths,
    description:
      baseWidths.description + Math.max(0, containerWidth - baseTotal),
  };
  const resizeColumn = (key: AgentColumnKey, width: number) => {
    const next = resizeAgentColumns(widths, key, width);
    setLocalWidths(next);
    onColumnWidthsChange?.(next);
  };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateHeight = () => {
      const headerHeight =
        container.querySelector(".ant-table-header")?.getBoundingClientRect()
          .height ?? 44;
      setBodyHeight(Math.max(1, container.clientHeight - headerHeight - 2));
      setContainerWidth(Math.max(0, container.clientWidth - 17));
    };
    const observer = new ResizeObserver(updateHeight);
    observer.observe(container);
    updateHeight();
    return () => observer.disconnect();
  }, []);

  const columns: ColumnsType<Agent> = [
    {
      title: t("agentConfig.list.column.name"),
      key: "name",
      ellipsis: true,
      render: (_, agent) => {
        const title = agent.display_name || agent.name;
        return (
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={() => onOpen(agent)}
              className="min-w-0 truncate text-left font-medium text-[#1f2937] hover:text-[#0067d1]"
              title={title}
            >
              {title}
            </button>
            <AgentListIndicators agent={agent} />
          </div>
        );
      },
    },
    {
      title: t("agentConfig.list.column.type"),
      key: "type",
      ellipsis: true,
      render: (_, agent) => {
        const rawCategory = agent.tags?.[0];
        const category = rawCategory
          ? getAgentRepositoryTagLabel(rawCategory, t)
          : undefined;
        return category ? (
          <Tag className="agent-table-category" title={category}>
            {category}
          </Tag>
        ) : (
          <span className="text-slate-400">-</span>
        );
      },
    },
    {
      title: t("agentConfig.list.column.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (description: string | undefined) => (
        <span
          className="block truncate text-[#64748b]"
          title={description || undefined}
        >
          {description || "-"}
        </span>
      ),
    },
    {
      title: t("agentConfig.list.column.status"),
      key: "status",
      render: (_, agent) => {
        const isOnline = Boolean(agent.current_version_no);
        return (
          <span
            className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-[12px] leading-4 ${isOnline ? "bg-[#edf5ff] text-[#0067d1]" : "bg-[#f1f3f5] text-[#6b7280]"}`}
          >
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
      ellipsis: true,
      render: (author: string | undefined) => (
        <span className="text-[#64748b]">{author?.trim() || "-"}</span>
      ),
    },
    {
      title: t("agentConfig.list.column.updatedAt"),
      key: "updatedAt",
      ellipsis: true,
      render: (_, agent) => (
        <span className="tabular-nums text-[#64748b]">
          {formatAgentUpdateTime(agent.update_time) || "-"}
        </span>
      ),
    },
    {
      title: t("agentConfig.list.column.actions"),
      key: "actions",
      fixed: "end",
      render: (_, agent) => {
        const agentId = Number(agent.id);
        const isOnline = Boolean(agent.current_version_no);
        const agentName = agent.display_name || agent.name;
        return (
          <div className="flex min-w-0 items-center agent-table-actions gap-3 whitespace-nowrap text-[13px] leading-5">
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
              agentName={agentName}
              readOnly={agent.permission === "READ_ONLY"}
              variant="table"
              onManageVersions={onManageVersions}
            />
          </div>
        );
      },
    },
  ];

  const resizableColumns = columns.map((column) => {
    const key = column.key as AgentColumnKey;
    return {
      ...column,
      width: widths[key],
      onHeaderCell: () =>
        ({
          "aria-label":
            typeof column.title === "string" ? column.title : undefined,
          className:
            key === "updatedAt" ? "agent-table-date-header" : undefined,
          resizeWidth: widths[key],
          minWidth: MIN_COLUMN_WIDTHS[key],
          resizeLabel: t("agentConfig.list.resizeColumn", {
            column: column.title,
          }),
          resizeFromStart: key === "actions",
          onResizeWidth: (width: number) => resizeColumn(key, width),
        }) as AgentTableHeaderProps,
    };
  });

  return (
    <div
      ref={containerRef}
      data-testid="agent-list-table-scroll"
      className="agent-table-container min-h-0 w-full min-w-0 flex-1 overflow-hidden rounded-xl border border-[#e8edf3] bg-white"
    >
      <ConfigProvider
        theme={{
          components: {
            Table: {
              colorText: "#191919",
              headerBg: "#f7f9fc",
              headerColor: "#475569",
              headerSplitColor: "transparent",
              borderColor: "#eef1f5",
              cellFontSizeSM: 14,
              cellPaddingBlockSM: 12,
              cellPaddingInlineSM: 16,
              rowHoverBg: "#f0f7ff",
            },
          },
        }}
      >
        <Table<Agent>
          className="agent-list-table"
          styles={{
            header: {
              cell: { height: 44, paddingBlock: 0, fontWeight: 500 },
            },
            body: { cell: { height: 52 } },
          }}
          components={{ header: { cell: AgentTableHeader } }}
          columns={resizableColumns}
          dataSource={agents}
          pagination={false}
          rowKey="id"
          size="small"
          tableLayout="fixed"
          scroll={{
            x: Object.values(widths).reduce((sum, width) => sum + width, 0),
            y: bodyHeight,
            scrollToFirstRowOnChange: true,
          }}
        />
      </ConfigProvider>
    </div>
  );
}
