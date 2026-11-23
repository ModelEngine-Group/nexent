// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Alert, Empty, Segmented, Spin } from "antd";
import dayjs from "dayjs";
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
  AgentMonitoringTrends,
  AgentPublication,
  AgentTokenUsage,
} from "@/types/agentMonitoring";
import {
  formatAgentMetric,
  getAgentSuccessRate,
  getAgentTrendValue,
  successSampleCount,
  type AgentTrendMetric,
} from "./agentMonitoringValues";
import type { useAgentMonitoring } from "./useAgentMonitoring";
import styles from "./agentMonitoring.module.css";

const metricLabels: Record<AgentTrendMetric, string> = {
  execution_count: "execution",
  success_rate: "success",
  total_tokens: "tokens",
};

export function PublicationStatus({
  label,
  publication,
}: {
  label: string;
  publication: AgentPublication;
}) {
  const { t } = useTranslation("common");
  return (
    <p className={styles.publication}>
      <strong>{label}</strong>
      <span>
        {t(`ops.monitoring.agent.coverage.${publication.coverage_state}`)}
      </span>
      {publication.is_stale && (
        <span className={styles.stale}>{t("ops.monitoring.agent.stale")}</span>
      )}
      <span>
        {t("ops.monitoring.agent.publishedAt", {
          date: publication.data_as_of
            ? dayjs
                .utc(publication.data_as_of)
                .format("YYYY-MM-DD HH:mm:ss [UTC]")
            : "—",
        })}
      </span>
    </p>
  );
}

export function TokenCoverage({ usage }: { usage: AgentTokenUsage | null }) {
  const { t, i18n } = useTranslation("common");
  if (usage === null)
    return <span>{t("ops.monitoring.agent.coverageMissing")}</span>;
  const number = new Intl.NumberFormat(i18n.language);
  return (
    <span>
      {t("ops.monitoring.agent.requestCoverage", {
        known: number.format(usage.known_count),
        eligible: number.format(usage.eligible_count),
        rate: formatAgentMetric(
          usage.coverage_rate,
          "success_rate",
          i18n.language
        ),
      })}
    </span>
  );
}

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
  const [metric, setMetric] = useState<AgentTrendMetric>("total_tokens");
  const titleId = useId();
  const gradientId = useId();
  const response: AgentMonitoringTrends | undefined = trends.data;
  const isToken = metric === "total_tokens";
  const metricLabel = t(`ops.monitoring.agent.${metricLabels[metric]}`);
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
        <Segmented<AgentTrendMetric>
          className={styles.trendMetric}
          aria-label={t("ops.monitoring.agent.trendMetric")}
          value={metric}
          options={(Object.keys(metricLabels) as AgentTrendMetric[]).map(
            (value) => ({
              value,
              label: t(`ops.monitoring.agent.${metricLabels[value]}`),
            })
          )}
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
                      {isToken ? (
                        <>
                          <TokenCoverage usage={day.tokens.total_tokens} />
                          <PublicationStatus
                            label={t("ops.monitoring.agent.tokens")}
                            publication={day.token_status}
                          />
                        </>
                      ) : (
                        <p>
                          {t(
                            `ops.monitoring.agent.coverage.${day.coverage_state}`
                          )}
                        </p>
                      )}
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
      {response && (
        <PublicationStatus
          label={
            isToken
              ? t("ops.monitoring.agent.tokens")
              : t("ops.monitoring.agent.executionStatus")
          }
          publication={isToken ? response.token_status : response}
        />
      )}
    </section>
  );
}

export function AgentMonitoringPanels({
  data,
  inventory,
  singleAgent,
  scopeLoading,
  hasSelection,
  hasRange,
}: {
  data: ReturnType<typeof useAgentMonitoring>;
  inventory: { count: number | null; loading: boolean; failed: boolean };
  singleAgent: boolean;
  scopeLoading: boolean;
  hasSelection: boolean;
  hasRange: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const summary = data.summary.data;
  const metrics = summary?.data;
  const usage = summary?.tokens.total_tokens ?? null;
  const samples = metrics ? successSampleCount(metrics) : null;
  const summaryLoading =
    scopeLoading || (hasSelection && data.summary.isPending);
  const trendLoading = scopeLoading || (hasSelection && data.trends.isPending);
  const renderValue = (
    value: number | string | null,
    metric: AgentTrendMetric
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
      value: renderValue(usage?.value ?? null, "total_tokens"),
      unit: usage?.value != null ? "tokens" : undefined,
      note: summary && <TokenCoverage usage={usage} />,
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
                <strong>{value}</strong>
                {unit && <span>{unit}</span>}
                {note && <small>{note}</small>}
              </dd>
            </div>
          </div>
        ))}
      </dl>
      {summary && (
        <div className={styles.statusList}>
          <PublicationStatus
            label={t("ops.monitoring.agent.executionStatus")}
            publication={summary}
          />
          <PublicationStatus
            label={t("ops.monitoring.agent.tokens")}
            publication={summary.token_status}
          />
        </div>
      )}
      <h2 className={styles.metricsTitle} id={titleId}>
        {t("ops.monitoring.agent.metrics")}
      </h2>
      <AgentTrend
        trends={data.trends}
        loading={trendLoading}
        hasRange={hasRange}
      />
    </section>
  );
}
