// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Alert, Empty, Segmented, Spin } from "antd";
import {
  Activity,
  Bot,
  ChartNoAxesColumnIncreasing,
  CircleCheck,
} from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  AgentMonitoringMetric,
  AgentMonitoringTrends,
} from "@/types/agentMonitoring";
import { AgentOutcomeDistribution } from "./AgentOutcomeDistribution";
import { AgentRankings } from "./AgentRankings";
import { MonitoringTokenCardValue } from "./AgentMonitoringStatus";
import {
  agentMetricLabels,
  formatAgentMetric,
  getAgentSuccessRate,
  getAgentTrendValue,
  successSampleCount,
} from "./agentMonitoringValues";
import type { useAgentMonitoring } from "./useAgentMonitoring";
import styles from "./agentMonitoring.module.css";

function AgentTrend({
  trends,
  loading,
  hasRange,
}: {
  trends: ReturnType<typeof useAgentMonitoring>["trends"];
  loading: boolean;
  hasRange: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  const [metric, setMetric] = useState<AgentMonitoringMetric>("total_tokens");
  const titleId = useId();
  const gradientId = useId();
  const response: AgentMonitoringTrends | undefined = trends.data;
  const isToken = metric === "total_tokens";
  const metricLabel = t(`ops.monitoring.agent.${agentMetricLabels[metric]}`);
  const chartData = response?.data.map((day) => {
    const exact = getAgentTrendValue(day, metric);
    // Recharts requires coordinates as numbers. Keep the original value for text and tooltips.
    return {
      date: day.statistic_date,
      value: exact === null ? null : Number(exact),
    };
  });
  const hasData = chartData?.some((day) => day.value !== null) ?? false;
  const compact = new Intl.NumberFormat(i18n.language, {
    notation: "compact",
    maximumFractionDigits: 1,
  });

  return (
    <section
      aria-labelledby={titleId}
      aria-busy={loading || trends.isFetching}
      className={styles.trend}
    >
      <header className={styles.trendHeader}>
        <div>
          <h3 id={titleId}>{t("ops.monitoring.agent.trend")}</h3>
          <span>{t("ops.monitoring.agent.daily")}</span>
        </div>
        <Segmented<AgentMonitoringMetric>
          className={styles.trendMetric}
          aria-label={t("ops.monitoring.agent.trendMetric")}
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
      {trends.isError && (
        <Alert
          type="error"
          showIcon
          title={t("ops.monitoring.agent.trendFailed")}
        />
      )}
      {loading && !response ? (
        <div className={styles.chartState}>
          <Spin aria-label={t("common.loading")} />
        </div>
      ) : hasData ? (
        <div
          className={styles.chart}
          data-chart-palette="default"
          role="group"
          aria-label={metricLabel}
        >
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart
              data={chartData}
              margin={{ top: 12, right: 18, left: 2, bottom: 4 }}
              accessibilityLayer
            >
              <defs>
                <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor="var(--color-chart-1)"
                    stopOpacity={0.18}
                  />
                  <stop
                    offset="100%"
                    stopColor="var(--color-chart-1)"
                    stopOpacity={0.015}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                vertical={false}
                stroke="var(--color-border-separator-subtle)"
              />
              <XAxis
                dataKey="date"
                tickFormatter={(date: string) => date.slice(5)}
                minTickGap={20}
                tickLine={false}
                stroke="var(--color-text-secondary)"
              />
              <YAxis
                domain={metric === "success_rate" ? [0, 1] : [0, "auto"]}
                allowDecimals={metric === "success_rate"}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--color-text-secondary)" }}
                tickFormatter={(value: number) =>
                  metric === "success_rate"
                    ? formatAgentMetric(value, metric, i18n.language)
                    : compact.format(value)
                }
              />
              <Tooltip
                filterNull={false}
                content={({ active, label }) => {
                  const day = response?.data.find(
                    (item) => item.statistic_date === label
                  );
                  if (!active || !day) return null;
                  const exact = getAgentTrendValue(day, metric);
                  return (
                    <div className={styles.tooltip}>
                      <strong>{day.statistic_date}</strong>
                      <p>
                        {metricLabel} ·{" "}
                        {formatAgentMetric(exact, metric, i18n.language)}
                        {isToken && exact !== null ? " tokens" : ""}
                      </p>
                    </div>
                  );
                }}
              />
              <Area
                type="linear"
                dataKey="value"
                stroke="var(--color-chart-1)"
                fill={`url(#${gradientId})`}
                strokeWidth={2}
                dot={{ r: 3, fill: "var(--color-chart-1)", strokeWidth: 0 }}
                isAnimationActive={false}
                connectNulls={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : !trends.isError ? (
        <Empty
          className={styles.chartState}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            !hasRange
              ? t("ops.monitoring.chooseRange")
              : response?.data.length
                ? t("ops.monitoring.agent.noValues")
                : t("ops.empty")
          }
        />
      ) : null}
    </section>
  );
}

export function AgentMonitoringPanels({
  data,
  tenantLabel,
  inventory,
  singleAgent,
  scopeLoading,
  hasRange,
}: {
  data: ReturnType<typeof useAgentMonitoring>;
  tenantLabel: (id: string) => string;
  inventory: { count: number | null; loading: boolean; failed: boolean };
  singleAgent: boolean;
  scopeLoading: boolean;
  hasRange: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const summary = data.summary.data;
  const metrics = summary?.data;
  const usage = summary?.tokens.total_tokens ?? null;
  const samples = metrics ? successSampleCount(metrics) : null;
  const hasSelection = data.queryKey[3] !== null;
  const summaryLoading =
    scopeLoading || (hasSelection && data.summary.isPending);
  const trendLoading = scopeLoading || (hasSelection && data.trends.isPending);
  const renderValue = (
    value: number | string | null,
    metric: AgentMonitoringMetric
  ) =>
    summaryLoading && !summary
      ? t("common.loading")
      : formatAgentMetric(value, metric, i18n.language);
  const cards = [
    ...(!singleAgent
      ? [
          {
            id: "inventory",
            title: t("ops.monitoring.agent.current"),
            Icon: Bot,
            value: inventory.loading
              ? t("common.loading")
              : formatAgentMetric(
                  inventory.count,
                  "execution_count",
                  i18n.language
                ),
            note: inventory.failed
              ? t("ops.monitoring.agent.inventoryFailed")
              : t("ops.monitoring.agent.currentHint"),
          },
        ]
      : []),
    {
      id: "execution",
      title: t("ops.monitoring.agent.execution"),
      Icon: Activity,
      value: renderValue(metrics?.execution_count ?? null, "execution_count"),
      unit:
        metrics?.execution_count != null
          ? t("ops.monitoring.agent.executionUnit")
          : undefined,
    },
    {
      id: "success",
      title: t("ops.monitoring.agent.successCard"),
      Icon: CircleCheck,
      value: renderValue(
        metrics ? getAgentSuccessRate(metrics) : null,
        "success_rate"
      ),
      note:
        samples !== null
          ? t("ops.monitoring.agent.successSamples", {
              samples: formatAgentMetric(
                samples,
                "execution_count",
                i18n.language
              ),
            })
          : undefined,
    },
    {
      id: "tokens",
      title: t("ops.monitoring.agent.tokenCard"),
      Icon: ChartNoAxesColumnIncreasing,
    },
  ];
  return (
    <section className={styles.panels} aria-labelledby={titleId}>
      {data.summary.isError && (
        <Alert
          type="error"
          showIcon
          title={t("ops.monitoring.agent.summaryFailed")}
        />
      )}
      <dl
        className={styles.cards}
        aria-label={t("ops.monitoring.agent.summary")}
        aria-busy={summaryLoading || data.summary.isFetching}
      >
        {cards.map(({ id, title, Icon, value, unit, note }) => (
          <div className={styles.card} key={id}>
            <Icon className={styles.icon} size={24} aria-hidden />
            <div>
              <dt>{title}</dt>
              <dd>
                {id === "tokens" ? (
                  <MonitoringTokenCardValue
                    usage={usage}
                    loading={summaryLoading && !summary}
                  />
                ) : (
                  <strong>{value}</strong>
                )}
                {unit && <span>{unit}</span>}
                {note && <small>{note}</small>}
              </dd>
            </div>
          </div>
        ))}
      </dl>
      <h2 className={styles.metricsTitle} id={titleId}>
        {t("ops.monitoring.agent.metrics")}
      </h2>
      <div className={styles.charts}>
        <AgentTrend
          trends={data.trends}
          loading={trendLoading}
          hasRange={hasRange}
        />
        {singleAgent ? (
          <AgentOutcomeDistribution
            summary={data.summary}
            loading={summaryLoading}
            hasRange={hasRange}
          />
        ) : (
          <AgentRankings
            queryKey={data.queryKey}
            scopeLoading={scopeLoading}
            hasRange={hasRange}
            tenantLabel={tenantLabel}
          />
        )}
      </div>
    </section>
  );
}
