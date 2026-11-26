// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Spin } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { getMcpMonitoringRankings } from "@/services/mcpMonitoringService";
import type {
  McpMonitoringDimension,
  McpMonitoringQueryKey,
  McpMonitoringRow,
} from "@/types/mcpMonitoring";
import styles from "../../agentMonitoring.module.css";
import {
  getMcpDrilldownService,
  mcpRowKey,
  mcpRowName,
} from "./mcpMonitoringValues";

export function McpMonitoringRankings({
  title,
  queryKey,
  dimension,
  scopeLoading,
  hasRange,
  onViewStatistics,
}: {
  title: string;
  queryKey: McpMonitoringQueryKey;
  dimension: McpMonitoringDimension;
  scopeLoading: boolean;
  hasRange: boolean;
  onViewStatistics: (row: McpMonitoringRow) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const selection = queryKey[3];
  const rankings = useQuery({
    queryKey: [...queryKey, "rankings", dimension],
    queryFn: ({ signal }) =>
      getMcpMonitoringRankings(selection!, dimension, signal),
    enabled: selection !== null,
  });
  const rows = rankings.data?.data ?? [];
  const maxCalls = Math.max(
    0,
    ...rows.map((row) => row.metrics.request_count ?? 0)
  );
  const number = new Intl.NumberFormat(i18n.language);
  const loading = scopeLoading || (selection !== null && rankings.isPending);
  const emptyLabel = !hasRange
    ? t("ops.monitoring.chooseRange")
    : rankings.data?.coverage_state === "uncovered"
      ? "—"
      : t("ops.empty");

  return (
    <section
      className={styles.trend}
      aria-labelledby={titleId}
      aria-busy={loading || rankings.isFetching}
    >
      <div className={styles.trendHeader}>
        <h3 id={titleId}>{title}</h3>
      </div>
      {rankings.isError ? (
        <Alert type="error" title={t("ops.loadError")} showIcon />
      ) : loading ? (
        <div className={styles.chartState}>
          <Spin aria-label={t("common.loading")} />
        </div>
      ) : rows.length ? (
        <ol className={styles.rankRows}>
          {rows.map((row) => {
            const name = mcpRowName(row);
            const calls = row.metrics.request_count;
            return (
              <li key={mcpRowKey(row)} className={styles.rankRow}>
                {getMcpDrilldownService(row) ? (
                  <Button
                    type="link"
                    className={styles.rankName}
                    title={name}
                    onClick={() => onViewStatistics(row)}
                  >
                    {name}
                  </Button>
                ) : (
                  <span className={styles.rankName} title={name}>
                    {name}
                  </span>
                )}
                <span className={styles.rankBar} aria-hidden>
                  <span
                    style={{
                      width: `${maxCalls ? (100 * (calls ?? 0)) / maxCalls : 0}%`,
                    }}
                  />
                </span>
                <strong className={styles.rankValue}>
                  {calls === null ? "—" : number.format(calls)}
                </strong>
              </li>
            );
          })}
        </ol>
      ) : (
        <Empty
          className={styles.chartState}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={emptyLabel}
        />
      )}
    </section>
  );
}
