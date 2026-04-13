"use client";

import React from "react";
import { Card, Statistic, Spin } from "antd";
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  ThunderboltOutlined,
  WarningOutlined,
  ClockCircleOutlined,
  DollarOutlined,
  BarChartOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ModelMonitoringItem } from "@/types/monitoring";

interface OverviewCardsProps {
  models: ModelMonitoringItem[];
  loading: boolean;
}

export default function OverviewCards({ models, loading }: OverviewCardsProps) {
  const { t } = useTranslation("common");

  const totalRequests = models.reduce((sum, m) => sum + m.request_count, 0);
  const avgErrorRate = models.length
    ? models.reduce((sum, m) => sum + m.error_rate, 0) / models.length
    : 0;
  const avgFailureRate = models.length
    ? models.reduce((sum, m) => sum + m.failure_rate, 0) / models.length
    : 0;
  const avgDuration = models.length
    ? models.reduce((sum, m) => sum + m.avg_duration, 0) / models.length
    : 0;
  const totalCost = models.reduce((sum, m) => sum + m.total_cost, 0);

  const cards = [
    {
      title: t("monitoring.dashboard.totalRequests"),
      value: totalRequests,
      icon: <BarChartOutlined />,
      color: "#1890ff",
      format: (v: number) => v.toLocaleString(),
    },
    {
      title: t("monitoring.dashboard.errorRate"),
      value: avgErrorRate,
      icon: <WarningOutlined />,
      color: avgErrorRate > 2 ? "#ff4d4f" : "#faad14",
      suffix: "%",
      precision: 2,
    },
    {
      title: t("monitoring.dashboard.failureRate"),
      value: avgFailureRate,
      icon: <ThunderboltOutlined />,
      color: avgFailureRate > 1 ? "#ff4d4f" : "#52c41a",
      suffix: "%",
      precision: 2,
    },
    {
      title: t("monitoring.dashboard.avgDuration"),
      value: avgDuration,
      icon: <ClockCircleOutlined />,
      color: "#722ed1",
      suffix: ` ${t("monitoring.time.ms")}`,
      precision: 0,
    },
    {
      title: t("monitoring.dashboard.todayCost"),
      value: totalCost,
      icon: <DollarOutlined />,
      color: "#13c2c2",
      prefix: "$",
      precision: 2,
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
      {cards.map((card, idx) => (
        <Card key={idx} bordered={false} className="shadow-sm">
          <Spin spinning={loading} size="small">
            <Statistic
              title={
                <span className="flex items-center gap-1.5 text-sm">
                  <span style={{ color: card.color }}>{card.icon}</span>
                  {card.title}
                </span>
              }
              value={card.value}
              precision={card.precision}
              suffix={card.suffix}
              prefix={card.prefix as React.ReactNode}
              formatter={(v) =>
                card.format ? card.format(Number(v)) : Number(v).toLocaleString()
              }
              valueStyle={{ color: card.color, fontSize: "1.25rem" }}
            />
          </Spin>
        </Card>
      ))}
    </div>
  );
}
