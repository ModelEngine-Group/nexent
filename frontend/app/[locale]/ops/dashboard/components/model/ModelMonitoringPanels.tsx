// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert, Segmented } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getModelMonitoringSummary,
  getModelMonitoringTrends,
} from "@/services/modelMonitoringService";
import type { ModelMonitoringSelection } from "@/types/modelMonitoring";
import { formatAgentMetric } from "../../agentMonitoringValues";
import { formatCompactMonitoringTokens } from "../shared/formatMonitoringTokens";
import { ModelMetricChart } from "./ModelMetricChart";
import type { ModelTrendMetric } from "./modelMonitoringValues";
import styles from "../../agentMonitoring.module.css";

export function ModelMonitoringPanels({
  queryKey,
  inventory,
  singleModel,
  scopeLoading,
  hasRange,
}: {
  queryKey: readonly [string, string, string, ModelMonitoringSelection | null];
  inventory: { count: number | null; loading: boolean; failed: boolean };
  singleModel: boolean;
  scopeLoading: boolean;
  hasRange: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const selection = queryKey[3];
  const [metric, setMetric] =
    useState<Exclude<ModelTrendMetric, "errorRate">>("requests");
  const summary = useQuery({
    queryKey: [...queryKey, "summary"],
    queryFn: ({ signal }) => getModelMonitoringSummary(selection!, signal),
    enabled: selection !== null,
  });
  const trends = useQuery({
    queryKey: [...queryKey, "trends"],
    queryFn: ({ signal }) => getModelMonitoringTrends(selection!, signal),
    enabled: selection !== null,
  });
  const summaryLoading =
    scopeLoading || (selection !== null && summary.isPending);
  const trendLoading =
    scopeLoading ||
    (selection !== null && (trends.isPending || trends.isFetching));
  const metrics = summary.data?.data;
  const usage = metrics?.total_tokens ?? null;
  const labels = {
    requests: t("ops.monitoring.model.details.requests"),
    tokens: t("ops.monitoring.agent.tokens"),
    errorRate: t("ops.monitoring.model.details.errorRate"),
  };
  const label = (key: string) => t(`ops.monitoring.model.metrics.${key}`);
  const number = (value: number | null) =>
    formatAgentMetric(value, "execution_count", i18n.language);
  const renderValue = (value: number | null) =>
    summaryLoading && !metrics ? t("common.loading") : number(value);
  const cards = [
    ...(!singleModel
      ? [
          {
            id: "inventory",
            title: label("current"),
            value: inventory.loading
              ? t("common.loading")
              : number(inventory.count),
          },
        ]
      : []),
    {
      id: "requests",
      title: label("requests"),
      value: renderValue(metrics?.request_count ?? null),
      unit: metrics?.request_count != null ? label("requestUnit") : undefined,
    },
    {
      id: "tokens",
      title: t("ops.monitoring.agent.tokenCard"),
      value:
        summaryLoading && !metrics
          ? t("common.loading")
          : formatCompactMonitoringTokens(usage?.value ?? null, i18n.language),
    },
  ];
  const trendProps = {
    trend: trends.data,
    loading: trendLoading,
    failed: trends.isError,
    hasRange,
  };

  return (
    <section className={styles.panels} aria-labelledby={titleId}>
      {!singleModel && inventory.failed && (
        <Alert type="error" showIcon title={label("inventoryFailed")} />
      )}
      {summary.isError && (
        <Alert type="error" showIcon title={label("summaryFailed")} />
      )}
      <dl
        className={styles.cards}
        aria-label={label("summary")}
        aria-busy={summaryLoading || summary.isFetching}
      >
        {cards.map(({ id, title, value, unit }) => (
          <div className={styles.card} key={id}>
            <div>
              <dt>{title}</dt>
              <dd>
                <strong>{value}</strong>
                {unit && <span>{unit}</span>}
              </dd>
            </div>
          </div>
        ))}
      </dl>
      <h2 id={titleId} className={styles.metricsTitle}>
        {t("ops.monitoring.agent.metrics")}
      </h2>
      <div className={styles.charts}>
        <ModelMetricChart
          {...trendProps}
          title={t("ops.monitoring.agent.trend")}
          metric={metric}
          metricLabel={labels[metric]}
          description={t("ops.monitoring.agent.daily")}
          headerAction={
            <Segmented
              className={styles.trendMetric}
              aria-label={label("trendMetric")}
              value={metric}
              onChange={setMetric}
              options={[
                { value: "requests", label: labels.requests },
                { value: "tokens", label: labels.tokens },
              ]}
            />
          }
        />
        <ModelMetricChart
          {...trendProps}
          title={label("errorTrend")}
          metric="errorRate"
          metricLabel={labels.errorRate}
        />
      </div>
    </section>
  );
}
