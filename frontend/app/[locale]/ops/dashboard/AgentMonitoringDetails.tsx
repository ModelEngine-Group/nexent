// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Pagination, Table, Tooltip } from "antd";
import type { TableProps } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { getAgentMonitoringList } from "@/services/agentMonitoringService";
import type {
  AgentListRequest,
  AgentListSort,
  AgentMonitoringRow,
} from "@/types/agentMonitoring";
import type { OperationsResource } from "@/types/operations";
import {
  formatAgentMetric,
  getAgentSuccessRate,
} from "./agentMonitoringValues";
import type { useAgentMonitoring } from "./useAgentMonitoring";
import { resourceKey } from "./useMonitoringDirectories";
import { MonitoringColumnSearch } from "./components/shared/MonitoringColumnSearch";
import styles from "./agentMonitoring.module.css";

const defaultList: AgentListRequest = {
  page: 1,
  pageSize: 10,
  search: "",
  sortBy: "execution_count",
  descending: true,
};

export function AgentMonitoringDetails({
  queryKey,
  scopeLoading,
  hasRange,
  selectedResource,
  inventory,
  canViewStatistics,
  onViewStatistics,
}: {
  queryKey: ReturnType<typeof useAgentMonitoring>["queryKey"];
  scopeLoading: boolean;
  hasRange: boolean;
  selectedResource: string;
  inventory: OperationsResource[] | undefined;
  canViewStatistics: (key: string) => boolean;
  onViewStatistics: (key: string) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const [list, setList] = useState(defaultList);
  const selection = queryKey[3];
  const scope = JSON.stringify(selection);
  const [listScope, setListScope] = useState(scope);
  if (listScope !== scope) {
    setListScope(scope);
    if (list.page !== 1) setList({ ...list, page: 1 });
  }
  const request = listScope === scope ? list : { ...list, page: 1 };
  const details = useQuery({
    queryKey: [...queryKey, "list", request],
    queryFn: ({ signal }) =>
      getAgentMonitoringList(selection!, request, signal),
    enabled: selection !== null,
    placeholderData: keepPreviousData,
  });
  const response = details.isPlaceholderData ? undefined : details.data;
  const total = response?.data.total;
  const lastPage = Math.max(1, Math.ceil((total ?? 0) / list.pageSize));
  if (listScope === scope && response && list.page > lastPage) {
    setList({ ...list, page: lastPage });
  }

  const label = (key: string) => t(`ops.monitoring.agent.details.${key}`);
  const loading = scopeLoading || (selection !== null && details.isPending);
  const number = (value: number | null | undefined) =>
    formatAgentMetric(value ?? null, "execution_count", i18n.language);
  const modelNames = new Map(
    inventory
      ?.filter((item) => item.kind === "model")
      .map((item) => [resourceKey(item.tenant_id, item.id), item.name])
  );
  const sortColumn = (
    key: AgentListSort,
    title: string
  ): NonNullable<TableProps<AgentMonitoringRow>["columns"]>[number] => ({
    key,
    title,
    sorter: true,
    sortDirections: ["descend", "ascend", "descend"],
    sortOrder:
      list.sortBy === key ? (list.descending ? "descend" : "ascend") : null,
    align: "right" as const,
  });
  const columns: NonNullable<TableProps<AgentMonitoringRow>["columns"]> = [
    {
      title: (
        <span className={styles.displayNameHeader}>
          {label("displayName")}
          <MonitoringColumnSearch
            search={list.search}
            placeholder={label("search")}
            disabled={!selection}
            onSubmit={(search) =>
              setList((current) =>
                current.search === search && current.page === 1
                  ? current
                  : { ...current, page: 1, search }
              )
            }
          />
        </span>
      ),
      key: "display_name",
      render: (_, row) => {
        const name =
          row.display_name ||
          row.name ||
          t("ops.monitoring.agent.details.agentId", { id: row.agent_id });
        return (
          <span className={styles.displayName} title={name}>
            {name}
          </span>
        );
      },
    },
    {
      title: label("name"),
      dataIndex: "name",
      render: (name: AgentMonitoringRow["name"]) => name || "—",
    },
    {
      title: label("model"),
      key: "model",
      render: (_, row) => {
        const names = row.model_ids?.map((id) =>
          modelNames.get(resourceKey(row.tenant_id, id))
        );
        return names?.some(Boolean) ? (
          names
            .map((name) => name || "—")
            .join(t("ops.monitoring.agent.details.modelSeparator"))
        ) : (
          <span title={label("modelMissing")}>—</span>
        );
      },
    },
    {
      title: label("status"),
      key: "status",
      render: () => <span title={label("statusMissing")}>—</span>,
    },
    {
      ...sortColumn("execution_count", t("ops.monitoring.agent.execution")),
      render: (_, row) => number(row.metrics?.execution_count),
    },
    {
      ...sortColumn("total_tokens", t("ops.monitoring.agent.tokenCard")),
      render: (_, row) => (
        <span className={styles.tokenValue}>
          {formatAgentMetric(
            row.tokens.total_tokens?.value ?? null,
            "total_tokens",
            i18n.language
          )}
        </span>
      ),
    },
    {
      ...sortColumn("avg_duration_ms", label("duration")),
      render: (_, row) => number(row.metrics?.avg_duration_ms),
    },
    {
      ...sortColumn("avg_ttft_ms", label("firstToken")),
      render: (_, row) => number(row.metrics?.avg_ttft_ms),
    },
    {
      ...sortColumn("success_rate", t("ops.monitoring.agent.successCard")),
      render: (_, row) =>
        formatAgentMetric(
          row.metrics ? getAgentSuccessRate(row.metrics) : null,
          "success_rate",
          i18n.language
        ),
    },
    {
      title: label("action"),
      key: "action",
      render: (_, row) => {
        const key = resourceKey(row.tenant_id, row.agent_id);
        const available = canViewStatistics(key);
        return (
          <Tooltip title={available ? undefined : label("outsideDirectory")}>
            <span>
              <Button
                type="link"
                size="small"
                disabled={!available || key === selectedResource}
                onClick={() => onViewStatistics(key)}
              >
                {label("view")}
              </Button>
            </span>
          </Tooltip>
        );
      },
    },
  ];
  const onTableChange: NonNullable<
    TableProps<AgentMonitoringRow>["onChange"]
  > = (_pagination, _filters, sorter, extra) => {
    if (extra.action !== "sort" || Array.isArray(sorter) || !sorter.columnKey)
      return;
    setList((current) => ({
      ...current,
      page: 1,
      sortBy: sorter.columnKey as AgentListSort,
      descending: sorter.order !== "ascend",
    }));
  };

  return (
    <section
      aria-labelledby={titleId}
      aria-busy={loading || details.isFetching}
      className={styles.details}
    >
      <h2 id={titleId} className={styles.detailsHeading}>
        {label("title")}
      </h2>
      {details.isError && (
        <Alert type="error" showIcon title={label("failed")} />
      )}
      <Table<AgentMonitoringRow>
        columns={columns}
        dataSource={response?.data.items ?? []}
        rowKey={(row) => resourceKey(row.tenant_id, row.agent_id)}
        loading={loading || details.isFetching}
        pagination={false}
        locale={{
          emptyText:
            loading || details.isFetching || details.isError ? null : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  selection
                    ? label(list.search ? "noMatch" : "empty")
                    : t(
                        hasRange
                          ? "ops.loadError"
                          : "ops.monitoring.chooseRange"
                      )
                }
              />
            ),
        }}
        onChange={onTableChange}
        scroll={{ x: 1140 }}
        size="small"
      />
      {total !== undefined && (
        <Pagination
          className={styles.detailsPagination}
          current={Math.min(list.page, lastPage)}
          pageSize={list.pageSize}
          total={total}
          showSizeChanger
          pageSizeOptions={[10, 20, 50, 100]}
          showQuickJumper
          showTotal={(count) =>
            t("ops.monitoring.agent.details.total", { total: number(count) })
          }
          onChange={(page, pageSize) =>
            setList((current) => ({
              ...current,
              page: pageSize === current.pageSize ? page : 1,
              pageSize,
            }))
          }
        />
      )}
    </section>
  );
}
