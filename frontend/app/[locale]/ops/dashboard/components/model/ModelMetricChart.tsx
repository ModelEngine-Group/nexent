// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Alert, Empty, Spin } from "antd";
import { useId, type ReactNode } from "react";
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
import type { ModelMonitoringTrends } from "@/types/modelMonitoring";
import { formatAgentMetric } from "../../agentMonitoringValues";
import { getModelMetric, type ModelTrendMetric } from "./modelMonitoringValues";
import styles from "../../agentMonitoring.module.css";

const chartHeight = 250;

export function ModelMetricChart({
  title,
  metric,
  metricLabel,
  trend,
  loading,
  failed,
  hasRange,
  headerAction,
  description,
}: {
  title: string;
  metric: ModelTrendMetric;
  metricLabel: string;
  trend: ModelMonitoringTrends | undefined;
  loading: boolean;
  failed: boolean;
  hasRange: boolean;
  headerAction?: ReactNode;
  description?: ReactNode;
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const gradient = useId();
  const percentage = metric === "errorRate";
  const token = metric === "tokens";
  const formattedMetric = percentage
    ? "success_rate"
    : token
      ? "total_tokens"
      : "execution_count";
  const compact = new Intl.NumberFormat(i18n.language, {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  const points = trend?.data.map((day) => {
    const value = getModelMetric(day, metric);
    // Use numeric coordinates only for plotting. Labels retain the response's integer string.
    return {
      date: day.statistic_date,
      value: value === null ? null : Number(value),
    };
  });
  const hasValues = points?.some((point) => point.value !== null);
  const emptyText = !hasRange
    ? t("ops.monitoring.chooseRange")
    : trend?.data.length
      ? t("ops.monitoring.agent.noValues")
      : t("ops.empty");

  return (
    <section
      className={styles.trend}
      aria-labelledby={titleId}
      aria-busy={loading}
      data-chart-palette="default"
    >
      <header className={`${styles.trendHeader} ${styles.modelTrendHeader}`}>
        <div>
          <h3 id={titleId}>{title}</h3>
          {description && <span>{description}</span>}
        </div>
        {headerAction}
      </header>
      {failed ? (
        <Alert
          type="error"
          showIcon
          title={t("ops.monitoring.model.metrics.trendsFailed")}
        />
      ) : loading && !trend ? (
        <div className={styles.chartState} style={{ minHeight: chartHeight }}>
          <Spin aria-label={t("common.loading")} />
        </div>
      ) : hasValues ? (
        <div className={styles.chart} role="group" aria-label={metricLabel}>
          <ResponsiveContainer width="100%" height={chartHeight}>
            <AreaChart
              data={points}
              margin={{ top: 12, right: 16, left: 0, bottom: 4 }}
              accessibilityLayer
            >
              <defs>
                <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
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
                domain={[0, "auto"]}
                allowDecimals={percentage}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--color-text-secondary)" }}
                tickFormatter={(value: number) =>
                  percentage
                    ? formatAgentMetric(value, "success_rate", i18n.language)
                    : compact.format(value)
                }
              />
              <Tooltip
                filterNull={false}
                content={({ active, label }) => {
                  const day = trend?.data.find(
                    (point) => point.statistic_date === label
                  );
                  if (!active || !day) return null;
                  const value = getModelMetric(day, metric);
                  return (
                    <div className={styles.tooltip}>
                      <strong>{day.statistic_date}</strong>
                      <p>
                        {metricLabel} ·{" "}
                        {formatAgentMetric(
                          value,
                          formattedMetric,
                          i18n.language
                        )}
                        {token && value !== null ? " tokens" : ""}
                      </p>
                      {percentage && (
                        <p>
                          {t("ops.monitoring.model.metrics.errorSamples", {
                            errors: formatAgentMetric(
                              day.error_count,
                              "execution_count",
                              i18n.language
                            ),
                            samples: formatAgentMetric(
                              day.error_eligible_count,
                              "execution_count",
                              i18n.language
                            ),
                          })}
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
                fill={`url(#${gradient})`}
                strokeWidth={2}
                dot={{ r: 3, fill: "var(--color-chart-1)", strokeWidth: 0 }}
                isAnimationActive={false}
                connectNulls={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <Empty
          className={styles.chartState}
          style={{ minHeight: chartHeight }}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={emptyText}
        />
      )}
    </section>
  );
}
