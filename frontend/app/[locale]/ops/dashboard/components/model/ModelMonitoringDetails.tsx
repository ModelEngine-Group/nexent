// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Pagination, Table } from "antd";
import type { TableProps } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { getModelMonitoringList } from "@/services/modelMonitoringService";
import type {
  ModelListRequest,
  ModelListSort,
  ModelMonitoringRow,
  ModelMonitoringSelection,
} from "@/types/modelMonitoring";
import { formatAgentMetric } from "../../agentMonitoringValues";
import { resourceKey } from "../../useMonitoringDirectories";
import { MonitoringColumnSearch } from "../shared/MonitoringColumnSearch";
import styles from "../../agentMonitoring.module.css";

const defaultList: ModelListRequest = {
  page: 1,
  pageSize: 10,
  search: "",
  sortBy: "name",
  descending: false,
};

export function ModelMonitoringDetails({
  queryKey,
  scopeLoading,
  hasRange,
  onViewStatistics,
}: {
  queryKey: readonly [string, string, string, ModelMonitoringSelection | null];
  scopeLoading: boolean;
  hasRange: boolean;
  onViewStatistics: (row: ModelMonitoringRow) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const selection = queryKey[3];
  const scope = JSON.stringify(selection);
  const [list, setList] = useState(defaultList);
  const [listScope, setListScope] = useState(scope);
  if (listScope !== scope) {
    setListScope(scope);
    if (list.page !== 1) setList({ ...list, page: 1 });
  }
  const request = listScope === scope ? list : { ...list, page: 1 };
  const details = useQuery({
    queryKey: [...queryKey, "list", request],
    queryFn: ({ signal }) =>
      getModelMonitoringList(selection!, request, signal),
    enabled: selection !== null,
    placeholderData: keepPreviousData,
  });
  const response = details.isPlaceholderData ? undefined : details.data;
  const total = response?.data.total;
  const lastPage = Math.max(1, Math.ceil((total ?? 0) / list.pageSize));
  if (listScope === scope && response && list.page > lastPage) {
    setList({ ...list, page: lastPage });
  }

  const label = (key: string) => t(`ops.monitoring.model.details.${key}`);
  const loading =
    scopeLoading ||
    (selection !== null && (details.isPending || details.isFetching));
  const number = (value: number | null | undefined) =>
    formatAgentMetric(value ?? null, "execution_count", i18n.language);
  const sortColumn = (
    key: ModelListSort,
    title: string
  ): NonNullable<TableProps<ModelMonitoringRow>["columns"]>[number] => ({
    key,
    title,
    sorter: true,
    sortDirections: ["ascend", "descend"],
    sortOrder:
      list.sortBy === key ? (list.descending ? "descend" : "ascend") : null,
    align: "right",
  });
  const numericColumns = {
    request_count: "requests",
    error_rate: "errorRate",
    avg_duration_ms: "duration",
    avg_ttft_ms: "firstToken",
    avg_generation_rate: "generationRate",
  } as const;
  const columns: NonNullable<TableProps<ModelMonitoringRow>["columns"]> = [
    {
      title: (
        <span className={styles.displayNameHeader}>
          {label("name")}
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
        const name = row.display_name || row.model_name || `#${row.model_id}`;
        return (
          <>
            <span className={styles.displayName} title={name}>
              {name}
            </span>
            {row.display_name && row.model_name && row.model_name !== name && (
              <small className={styles.rowTenant}>{row.model_name}</small>
            )}
          </>
        );
      },
    },
    {
      title: label("type"),
      key: "model_type",
      render: (_, row) =>
        row.model_type
          ? t(`tenantResources.models.type.${row.model_type}`, {
              defaultValue: row.model_type,
            })
          : "—",
    },
    {
      title: label("status"),
      key: "connect_status",
      render: (_, row) =>
        row.connect_status
          ? t(`model.status.${row.connect_status}`, {
              defaultValue: row.connect_status,
            })
          : "—",
    },
    {
      title: label("source"),
      dataIndex: "model_factory",
      render: (value: string | null) => value || "—",
    },
    ...(Object.keys(numericColumns) as (keyof typeof numericColumns)[]).map(
      (key) => ({
        ...sortColumn(key, label(numericColumns[key])),
        render: (_: unknown, row: ModelMonitoringRow) =>
          key === "error_rate"
            ? formatAgentMetric(
                row.metrics?.error_rate ?? null,
                "success_rate",
                i18n.language
              )
            : number(row.metrics?.[key]),
      })
    ),
    {
      ...sortColumn("total_tokens", label("tokens")),
      render: (_, row) => (
        <span className={styles.tokenValue}>
          {formatAgentMetric(
            row.metrics?.total_tokens?.value ?? null,
            "total_tokens",
            i18n.language
          )}
        </span>
      ),
    },
    {
      title: label("action"),
      key: "action",
      render: (_, row) => (
        <Button
          type="link"
          size="small"
          disabled={
            selection?.tenantId === row.tenant_id &&
            selection.modelId === row.model_id
          }
          onClick={() => onViewStatistics(row)}
        >
          {label("view")}
        </Button>
      ),
    },
  ];
  const onTableChange: NonNullable<
    TableProps<ModelMonitoringRow>["onChange"]
  > = (_pagination, _filters, sorter, extra) => {
    if (extra.action !== "sort" || Array.isArray(sorter)) return;
    setList((current) => ({
      ...current,
      page: 1,
      sortBy: sorter.order ? (sorter.columnKey as ModelListSort) : "name",
      descending: sorter.order === "descend",
    }));
  };
  return (
    <section
      aria-labelledby={titleId}
      aria-busy={loading}
      className={styles.details}
    >
      <h2 id={titleId} className={styles.detailsHeading}>
        {label("title")}
      </h2>
      {details.isError && (
        <Alert type="error" showIcon title={label("failed")} />
      )}
      <Table<ModelMonitoringRow>
        columns={columns}
        dataSource={response?.data.items ?? []}
        rowKey={(row) => resourceKey(row.tenant_id, row.model_id)}
        loading={loading}
        pagination={false}
        onChange={onTableChange}
        locale={{
          emptyText:
            loading || details.isError ? null : (
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
        scroll={{ x: 1180 }}
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
            t("ops.monitoring.model.details.total", { total: number(count) })
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
