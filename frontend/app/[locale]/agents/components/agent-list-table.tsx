// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState, type Key } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/common/Button";
import { Modal } from "@/components/common/Modal";
import { useAgentBulkDelete } from "@/hooks/agent/useAgentBulkDelete";
import { showInfoNotice } from "@/lib/uiNotices";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/common/Badge";
import { Table, type TableColumn } from "@/components/common/Table";
import { UserIdentity } from "@/components/auth/UserIdentity";
import { normalizeTags } from "@/services/agentConfigService";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import type { Agent } from "@/types/agentConfig";
import AgentConfigActions from "./agent-config-actions";
import AgentListIndicators from "./agent-list-indicators";

export interface AgentListTableProps {
  agents: Agent[];
  columnWidths?: Readonly<Record<string, number>>;
  onColumnWidthsChange?: (widths: Record<string, number>) => void;
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
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [deleteTargets, setDeleteTargets] = useState<readonly Agent[]>([]);
  const bulkDelete = useAgentBulkDelete();
  const confirmDelete = async () => {
    if (!deleteTargets.length || bulkDelete.isPending) return;
    const result = await bulkDelete.mutateAsync(deleteTargets);
    const deletedKeys = new Set(
      result.deleted.map((agent) => String(agent.id))
    );
    setSelectedKeys((keys) =>
      keys.filter((key) => !deletedKeys.has(String(key)))
    );
    setDeleteTargets([]);
    const failedNames = result.failed
      .map((agent) => agent.display_name || agent.name)
      .join(", ");
    showInfoNotice({
      title: t("agentConfig.list.bulkDeleteResult"),
      content: (
        <div className="space-y-2">
          <p>
            {t("agentConfig.list.bulkDeleteSummary", {
              succeeded: result.deleted.length,
              failed: result.failed.length,
            })}
          </p>
          {failedNames && (
            <p>
              {t("agentConfig.list.bulkDeleteFailedNames", {
                names: failedNames,
              })}
            </p>
          )}
        </div>
      ),
      confirmLabel: t("common.confirm"),
    });
  };
  const columns: TableColumn<Agent>[] = [
    {
      key: "name",
      header: t("agentConfig.list.column.name"),
      minWidth: 200,
      maxWidth: 300,
      grow: 0,
      cell: (agent) => (
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={() => onOpen(agent)}
            title={agent.display_name || agent.name}
            className="min-w-0 truncate font-medium hover:text-primary"
          >
            {agent.display_name || agent.name}
          </button>
          <AgentListIndicators agent={agent} />
        </div>
      ),
    },
    {
      key: "type",
      header: t("agentConfig.list.column.type"),
      minWidth: 104,
      maxWidth: 180,
      grow: 0,
      cell: (agent) => {
        const category = normalizeTags(agent.tags)[0];
        return category ? (
          <Badge variant="info" size="sm">
            {getAgentRepositoryTagLabel(category, t)}
          </Badge>
        ) : (
          "-"
        );
      },
    },
    {
      key: "description",
      header: t("agentConfig.list.column.description"),
      minWidth: 240,
      grow: 1,
      cell: (agent) => (
        <span title={agent.description || undefined}>
          {agent.description || "-"}
        </span>
      ),
    },
    {
      key: "status",
      header: t("agentConfig.list.column.status"),
      minWidth: 104,
      grow: 0,
      cell: (agent) => (
        <Badge variant={agent.current_version_no ? "info" : "muted"} size="sm">
          {t(
            agent.current_version_no
              ? "agentConfig.list.online"
              : "agentConfig.list.offline"
          )}
        </Badge>
      ),
    },
    {
      key: "creator",
      header: t("agentConfig.list.column.creator"),
      minWidth: 136,
      maxWidth: 240,
      grow: 0,
      cell: (agent) => (
        <UserIdentity
          casUsername={agent.author_cas_username}
          fallback={agent.author?.trim() || "-"}
        />
      ),
    },
    {
      key: "updatedAt",
      header: t("agentConfig.list.column.updatedAt"),
      minWidth: 128,
      grow: 0,
      cell: (agent) => formatAgentUpdateTime(agent.update_time) || "-",
    },
    {
      key: "actions",
      header: t("agentConfig.list.column.actions"),
      width: 232,
      resizable: false,
      cell: (agent) => {
        const agentId = Number(agent.id);
        return (
          <div className="flex items-center gap-3 text-primary">
            <button
              type="button"
              onClick={() => onConfigure(agentId)}
              className="hover:text-primary-hover"
            >
              {t("agentConfig.list.configure")}
            </button>
            {!agent.current_version_no && (
              <button
                type="button"
                onClick={() => onPublish(agentId)}
                className="hover:text-primary-hover"
              >
                {t("agentConfig.list.publish")}
              </button>
            )}
            <AgentConfigActions
              agentId={agentId}
              agentName={agent.display_name || agent.name}
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
    <>
      <Table
        data-testid="agent-list-table-scroll"
        className="flex-1"
        columns={columns}
        columnWidths={columnWidths}
        onColumnWidthsChange={onColumnWidthsChange}
        data={agents}
        rowKey={(agent) => agent.id}
        selection={{
          selectedKeys,
          onChange: setSelectedKeys,
          disabled: bulkDelete.isPending,
          isRowSelectable: (agent) =>
            agent.permission !== "READ_ONLY" &&
            Number.isInteger(Number(agent.id)) &&
            Number(agent.id) > 0,
          getRowLabel: (agent) => agent.display_name || agent.name,
          actions: [
            {
              key: "delete",
              label: t("agentConfig.list.bulkDelete"),
              icon: <Trash2 className="size-4" />,
              variant: "destructive",
              loading: bulkDelete.isPending,
              onClick: (rows) => setDeleteTargets([...rows]),
            },
          ],
        }}
      />
      <Modal
        open={deleteTargets.length > 0}
        title={t("businessLogic.config.modal.deleteTitle")}
        closeLabel={t("common.close")}
        onClose={() => {
          if (!bulkDelete.isPending) setDeleteTargets([]);
        }}
        closeOnEscape={!bulkDelete.isPending}
        footer={
          <>
            <Button
              variant="outline"
              disabled={bulkDelete.isPending}
              onClick={() => setDeleteTargets([])}
            >
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              loading={bulkDelete.isPending}
              onClick={() => void confirmDelete()}
            >
              {t("common.confirm")}
            </Button>
          </>
        }
      >
        <p>
          {t("agentConfig.list.bulkDeleteConfirm", {
            count: deleteTargets.length,
          })}
        </p>
        <ul className="mt-3 max-h-48 list-disc overflow-auto pl-5 text-sm text-muted-foreground">
          {deleteTargets.map((agent) => (
            <li key={agent.id}>{agent.display_name || agent.name}</li>
          ))}
        </ul>
      </Modal>
    </>
  );
}
