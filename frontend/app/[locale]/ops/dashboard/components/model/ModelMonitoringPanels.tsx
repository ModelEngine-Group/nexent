// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert, Segmented } from "antd";
import { Activity, Box, ChartNoAxesColumnIncreasing } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getModelMonitoringSummary,
  getModelMonitoringTrends,
} from "@/services/modelMonitoringService";
import type { ModelMonitoringSelection } from "@/types/modelMonitoring";
import { PublicationStatus, TokenCoverage } from "../../AgentMonitoringStatus";
import { formatAgentMetric } from "../../agentMonitoringValues";
import { ModelMetricChart } from "./ModelMetricChart";
import { getModelMetric, type ModelTrendMetric } from "./modelMonitoringValues";
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
  const renderValue = (value: number | string | null, token = false) =>
    summaryLoading && !metrics
      ? t("common.loading")
      : formatAgentMetric(
          value,
          token ? "total_tokens" : "execution_count",
          i18n.language
        );
  const cards = [
    ...(!singleModel
      ? [
          {
            id: "inventory",
            title: label("current"),
            Icon: Box,
            value: inventory.loading
              ? t("common.loading")
              : number(inventory.count),
            note: inventory.failed
              ? label("inventoryFailed")
              : label("currentHint"),
          },
        ]
      : []),
    {
      id: "requests",
      title: label("requests"),
      Icon: Activity,
      value: renderValue(metrics?.request_count ?? null),
      unit: metrics?.request_count != null ? label("requestUnit") : undefined,
    },
    {
      id: "tokens",
      title: t("ops.monitoring.agent.tokenCard"),
      Icon: ChartNoAxesColumnIncreasing,
      value: renderValue(usage?.value ?? null, true),
      unit: usage?.value != null ? "tokens" : undefined,
      note: metrics && <TokenCoverage usage={usage} />,
    },
  ];
  const trendProps = {
    trend: trends.data,
    loading: trendLoading,
    failed: trends.isError,
    hasRange,
  };
  const rate = metrics ? getModelMetric(metrics, "errorRate") : null;
  const hasSamples =
    metrics?.error_count != null && Boolean(metrics.error_eligible_count);

  return (
    <section className={styles.panels} aria-labelledby={titleId}>
      {summary.isError && (
        <Alert type="error" showIcon title={label("summaryFailed")} />
      )}
      <dl
        className={styles.cards}
        aria-label={label("summary")}
        aria-busy={summaryLoading || summary.isFetching}
      >
        {cards.map(({ id, title, Icon, value, unit, note }) => (
          <div className={styles.card} key={id}>
            <Icon className={styles.icon} size={24} aria-hidden />
            <div>
              <dt>{title}</dt>
              <dd>
                <strong>{value}</strong>
                {unit && <span>{unit}</span>}
                {note && <small>{note}</small>}
              </dd>
            </div>
          </div>
        ))}
      </dl>
      {summary.data && (
        <PublicationStatus
          label={t("ops.monitoring.model.details.statusLabel")}
          publication={summary.data}
        />
      )}
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
          headerAction={
            <span>
              {formatAgentMetric(rate, "success_rate", i18n.language)}{" "}
              {label("rangeErrorRate")}
            </span>
          }
          description={
            hasSamples
              ? t("ops.monitoring.model.metrics.errorSamples", {
                  errors: number(metrics.error_count),
                  samples: number(metrics.error_eligible_count),
                })
              : t("ops.monitoring.agent.daily")
          }
        />
      </div>
    </section>
  );
}
