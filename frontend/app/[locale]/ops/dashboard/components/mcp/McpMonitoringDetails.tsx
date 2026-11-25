// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Pagination, Table } from "antd";
import type { TableProps } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { getMcpMonitoringList } from "@/services/mcpMonitoringService";
import type {
  McpMonitoringDimension,
  McpMonitoringListOptions,
  McpMonitoringQueryKey,
  McpMonitoringRow,
  McpMonitoringSort,
} from "@/types/mcpMonitoring";
import styles from "../../agentMonitoring.module.css";
import { MonitoringColumnSearch } from "../shared/MonitoringColumnSearch";
import {
  getMcpDrilldownService,
  mcpRowKey,
  mcpRowName,
} from "./mcpMonitoringValues";

const initialList: McpMonitoringListOptions = {
  page: 1,
  pageSize: 10,
  search: "",
  sortBy: "request_count",
  descending: true,
};

export function McpMonitoringDetails({
  queryKey,
  dimension,
  singleTool,
  scopeLoading,
  hasRange,
  onViewStatistics,
}: {
  queryKey: McpMonitoringQueryKey;
  dimension: McpMonitoringDimension;
  singleTool: boolean;
  scopeLoading: boolean;
  hasRange: boolean;
  onViewStatistics: (row: McpMonitoringRow) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const selection = queryKey[3];
  const scope = JSON.stringify(selection);
  const [list, setList] = useState(initialList);
  const [listScope, setListScope] = useState(scope);
  if (listScope !== scope) {
    setListScope(scope);
    if (list.page !== 1) setList({ ...list, page: 1 });
  }
  const request = listScope === scope ? list : { ...list, page: 1 };
  const details = useQuery({
    queryKey: [...queryKey, "list", dimension, request],
    queryFn: ({ signal }) =>
      getMcpMonitoringList(selection!, dimension, request, signal),
    enabled: selection !== null,
  });
  const response = details.isError ? undefined : details.data;
  const total = response?.data.total;
  const lastPage = Math.max(1, Math.ceil((total ?? 0) / list.pageSize));
  if (listScope === scope && response && list.page > lastPage) {
    setList({ ...list, page: lastPage });
  }
  const loading =
    scopeLoading ||
    (selection !== null && (details.isPending || details.isFetching));
  const services = dimension === "services";
  const label = (key: string) => t(`ops.monitoring.mcp.${key}`);
  const number = new Intl.NumberFormat(i18n.language);
  const duration = new Intl.NumberFormat(i18n.language, {
    maximumFractionDigits: 2,
  });
  const format = (value: number | null | undefined) =>
    value == null ? "—" : number.format(value);
  const sortableMetric = (
    key: McpMonitoringSort,
    title: string
  ): NonNullable<TableProps<McpMonitoringRow>["columns"]>[number] => ({
    title,
    key,
    sorter: true,
    sortDirections: ["descend", "ascend", "descend"],
    sortOrder:
      list.sortBy === key ? (list.descending ? "descend" : "ascend") : null,
    render: (_, row) => {
      const value = row.metrics[key];
      return value == null
        ? "—"
        : (key === "avg_duration_ms" ? duration : number).format(value);
    },
  });
  const columns: NonNullable<TableProps<McpMonitoringRow>["columns"]> = [
    {
      title: (
        <span className={styles.displayNameHeader}>
          {label(services ? "serviceName" : "toolName")}
          <MonitoringColumnSearch
            search={list.search}
            placeholder={label(services ? "searchServices" : "searchTools")}
            disabled={!selection}
            onSubmit={(search) =>
              setList((current) => ({ ...current, page: 1, search }))
            }
          />
        </span>
      ),
      key: "name",
      render: (_, row) => {
        const name = mcpRowName(row);
        return (
          <span className={styles.displayName} title={name}>
            {name}
          </span>
        );
      },
    },
  ];
  if (services)
    columns.push(
      {
        title: t("common.source"),
        key: "source",
        render: (_, row) =>
          row.mcp_server_type && row.mcp_server_type !== "unknown"
            ? label(`source.${row.mcp_server_type}`)
            : "—",
      },
      {
        title: label("activeTools"),
        key: "active_tools",
        render: (_, row) => format(row.active_tools),
      }
    );
  columns.push(
    sortableMetric("request_count", label("calls")),
    sortableMetric("avg_duration_ms", label("latency"))
  );
  if (!singleTool)
    columns.push({
      title: t("common.actions"),
      key: "actions",
      render: (_, row) =>
        getMcpDrilldownService(row) ? (
          <Button
            type="link"
            size="small"
            onClick={() => onViewStatistics(row)}
          >
            {label("view")}
          </Button>
        ) : (
          "—"
        ),
    });

  const onTableChange: NonNullable<TableProps<McpMonitoringRow>["onChange"]> = (
    _,
    _filters,
    sorter,
    extra
  ) => {
    if (extra.action !== "sort" || Array.isArray(sorter)) return;
    const sortBy = sorter.columnKey;
    if (sortBy === "request_count" || sortBy === "avg_duration_ms") {
      setList((current) => ({
        ...current,
        page: 1,
        sortBy,
        descending: sorter.order !== "ascend",
      }));
    }
  };
  const emptyLabel = !hasRange
    ? t("ops.monitoring.chooseRange")
    : response?.coverage_state === "uncovered"
      ? "—"
      : t("ops.empty");

  return (
    <section
      aria-labelledby={titleId}
      aria-busy={loading}
      className={styles.details}
    >
      <h2 id={titleId} className={styles.detailsHeading}>
        {label(services ? "serviceDetails" : "toolDetails")}
      </h2>
      {details.isError && (
        <Alert type="error" title={t("ops.loadError")} showIcon />
      )}
      <Table<McpMonitoringRow>
        columns={columns}
        dataSource={response?.data.items ?? []}
        rowKey={mcpRowKey}
        loading={loading}
        pagination={false}
        onChange={onTableChange}
        locale={{
          emptyText:
            loading || details.isError ? null : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={emptyLabel}
              />
            ),
        }}
        size="small"
      />
      {!singleTool && total !== undefined && (
        <Pagination
          className={styles.detailsPagination}
          current={Math.min(list.page, lastPage)}
          pageSize={list.pageSize}
          total={total}
          showSizeChanger
          pageSizeOptions={[10, 20, 50, 100]}
          showQuickJumper
          showTotal={(count) =>
            t(
              services
                ? "ops.monitoring.mcp.totalServices"
                : "ops.monitoring.mcp.totalTools",
              { total: number.format(count) }
            )
          }
          onChange={(page, pageSize) =>
            setList((current) => ({
              ...current,
              page: current.pageSize === pageSize ? page : 1,
              pageSize,
            }))
          }
        />
      )}
    </section>
  );
}
