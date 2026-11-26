// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert, Empty, Segmented, Spin, Tooltip } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { getAgentMonitoringRankings } from "@/services/agentMonitoringService";
import type { AgentMonitoringMetric } from "@/types/agentMonitoring";
import { PublicationStatus, TokenCoverage } from "./AgentMonitoringStatus";
import {
  agentMetricLabels,
  formatAgentMetric,
  getAgentRankingValue,
} from "./agentMonitoringValues";
import type { useAgentMonitoring } from "./useAgentMonitoring";
import { resourceKey } from "./useMonitoringDirectories";
import styles from "./agentMonitoring.module.css";

export function AgentRankings({
  queryKey,
  scopeLoading,
  hasRange,
  tenantLabel,
}: {
  queryKey: ReturnType<typeof useAgentMonitoring>["queryKey"];
  scopeLoading: boolean;
  hasRange: boolean;
  tenantLabel: (id: string) => string;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const [metric, setMetric] =
    useState<AgentMonitoringMetric>("execution_count");
  const selection = queryKey[3];
  const rankings = useQuery({
    queryKey: [...queryKey, "rankings", metric],
    queryFn: ({ signal }) =>
      getAgentMonitoringRankings(selection!, metric, signal),
    enabled: selection?.agentId === null,
  });
  const response = rankings.data;
  const loading = scopeLoading || (selection !== null && rankings.isPending);
  const isToken = metric === "total_tokens";
  const isRate = metric === "success_rate";
  const rows =
    response?.data.map((row) => ({
      row,
      value: getAgentRankingValue(row, metric),
    })) ?? [];
  // Convert only the bar widths to numbers. The server's order and the Token labels stay exact.
  const max = isRate
    ? 1
    : Math.max(0, ...rows.map(({ value }) => Number(value)));
  const publication = isToken ? response?.token_status : response;
  const title = t("ops.monitoring.agent.ranking.title");
  const format = (value: number | string | null, kind = metric) =>
    formatAgentMetric(value, kind, i18n.language);

  return (
    <section
      aria-labelledby={titleId}
      aria-busy={loading || rankings.isFetching}
      className={styles.trend}
      data-chart-palette="default"
    >
      <header className={styles.trendHeader}>
        <div>
          <h3 id={titleId}>{title}</h3>
          <span>{t("ops.monitoring.agent.ranking.top")}</span>
        </div>
        <Segmented<AgentMonitoringMetric>
          className={styles.trendMetric}
          aria-label={t("ops.monitoring.agent.ranking.metric")}
          value={metric}
          options={(
            Object.keys(agentMetricLabels) as AgentMonitoringMetric[]
          ).map((value) => ({
            value,
            label: t(`ops.monitoring.agent.${agentMetricLabels[value]}`),
          }))}
          onChange={setMetric}
        />
      </header>
      {rankings.isError && (
        <Alert
          type="error"
          showIcon
          title={t("ops.monitoring.agent.ranking.failed")}
        />
      )}
      {loading && !response ? (
        <div className={styles.chartState}>
          <Spin aria-label={t("common.loading")} />
        </div>
      ) : rows.length ? (
        <>
          <ol className={styles.rankRows} role="list">
            {rows.map(({ row, value }) => {
              const name =
                row.display_name ||
                row.name ||
                t("ops.monitoring.agent.details.agentId", { id: row.agent_id });
              const samples = row.metrics?.success_sample_count;
              const usage = row.tokens?.total_tokens ?? null;
              const width = max ? (100 * Number(value)) / max : 0;
              const valueLabel = format(value);
              return (
                <li
                  key={resourceKey(row.tenant_id, row.agent_id)}
                  className={styles.rankRow}
                >
                  <span className={styles.rankName}>
                    {name}
                    {selection?.tenantId === null && (
                      <small className={styles.rowTenant}>
                        {tenantLabel(row.tenant_id)}
                      </small>
                    )}
                  </span>
                  <span className={styles.rankBar} aria-hidden>
                    <span style={{ width: `${width}%` }} />
                  </span>
                  <span className={styles.rankValue}>
                    {isToken ? (
                      <Tooltip title={<TokenCoverage usage={usage} />}>
                        <strong tabIndex={0}>{valueLabel}</strong>
                      </Tooltip>
                    ) : (
                      <strong>{valueLabel}</strong>
                    )}
                    {isRate && samples !== undefined && (
                      <small>
                        {t("ops.monitoring.agent.successSamples", {
                          samples: format(samples, "execution_count"),
                        })}
                      </small>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
          {isRate && (
            <div className={styles.rankScale} aria-hidden>
              <div>
                {[0, 0.25, 0.5, 0.75, 1].map((value) => (
                  <span key={value}>{format(value)}</span>
                ))}
              </div>
            </div>
          )}
        </>
      ) : !rankings.isError ? (
        <Empty
          className={styles.chartState}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t(
            selection
              ? "ops.empty"
              : hasRange
                ? "ops.loadError"
                : "ops.monitoring.chooseRange"
          )}
        />
      ) : null}
      {publication && (
        <PublicationStatus
          label={t(
            isToken
              ? "ops.monitoring.agent.tokens"
              : "ops.monitoring.agent.executionStatus"
          )}
          publication={publication}
        />
      )}
    </section>
  );
}
