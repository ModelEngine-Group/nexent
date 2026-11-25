// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Alert, Empty, Spin } from "antd";
import { useId } from "react";
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
  MonitoringCoverage,
  MonitoringPublication,
} from "@/types/operations";
import { PublicationStatus } from "../../AgentMonitoringStatus";
import styles from "./overview.module.css";

interface OverviewPoint {
  date: string;
  value: number | null;
  coverage?: MonitoringCoverage;
}

export function OverviewTrend({
  title,
  description,
  emptyDescription,
  trend,
}: {
  title: string;
  description?: string;
  emptyDescription?: string;
  trend?: {
    points?: OverviewPoint[];
    publication?: MonitoringPublication;
    loading: boolean;
    failed: boolean;
    hasRange: boolean;
  };
}) {
  const { t, i18n } = useTranslation("common");
  const titleId = useId();
  const gradient = useId();
  const points = trend?.points;
  const hasData = points?.some(({ value }) => value !== null);
  const number = new Intl.NumberFormat(i18n.language);
  const tick = new Intl.NumberFormat(i18n.language, {
    notation: "compact",
    maximumFractionDigits: 1,
  });

  let content;
  if (!trend) {
    content = (
      <span className={styles.unavailable}>
        {t("ops.monitoring.notConnected")}
      </span>
    );
  } else if (trend.failed) {
    content = <Alert type="error" showIcon title={t("ops.loadError")} />;
  } else if (trend.loading && !points) {
    content = <Spin aria-label={t("common.loading")} />;
  } else if (!hasData) {
    content = (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          trend.hasRange
            ? (emptyDescription ?? t("ops.empty"))
            : t("ops.monitoring.chooseRange")
        }
      />
    );
  }

  return (
    <section
      className={styles.panel}
      aria-labelledby={titleId}
      aria-busy={trend?.loading}
      data-chart-palette="default"
    >
      <h3 id={titleId}>{title}</h3>
      {description && (
        <small className={styles.description}>{description}</small>
      )}
      {content ? (
        <div className={styles.chartState}>{content}</div>
      ) : (
        <div className={styles.chart}>
          <ResponsiveContainer width="100%" height={192}>
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
                allowDecimals={false}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--color-text-secondary)" }}
                tickFormatter={(value: number) => tick.format(value)}
              />
              <Tooltip
                filterNull={false}
                content={({ active, label }) => {
                  const point = points?.find(({ date }) => date === label);
                  if (!active || !point) return null;
                  return (
                    <div className={styles.tooltip}>
                      <strong>{point.date}</strong>
                      <span>
                        {title} ·{" "}
                        {point.value === null
                          ? "—"
                          : number.format(point.value)}
                      </span>
                      {point.coverage && (
                        <span>
                          {t(`ops.monitoring.agent.coverage.${point.coverage}`)}
                        </span>
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
      )}
      {trend?.publication && !trend.failed && (
        <PublicationStatus
          label={t("ops.monitoring.overview.trendStatus")}
          publication={trend.publication}
        />
      )}
    </section>
  );
}
