"use client";

import React from "react";
import { Card, Statistic, Row, Col, Spin, Empty, Tag } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
  DollarOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ModelSummaryResponse } from "@/types/monitoring";

interface PerformanceChartsProps {
  summary: ModelSummaryResponse | null;
  loading: boolean;
}

export default function PerformanceCharts({ summary, loading }: PerformanceChartsProps) {
  const { t } = useTranslation("common");

  if (!summary && !loading) {
    return <Empty description="No data available" />;
  }

  const perf = summary?.performance;

  return (
    <Spin spinning={loading}>
      <div className="space-y-4">
        <Row gutter={[16, 16]}>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.totalRequests")}
                value={perf?.total_requests ?? 0}
                valueStyle={{ color: "#1890ff", fontSize: "1.1rem" }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.errorRate")}
                value={perf?.error_rate ?? 0}
                suffix="%"
                precision={2}
                valueStyle={{
                  color: (perf?.error_rate ?? 0) > 3 ? "#ff4d4f" : "#52c41a",
                  fontSize: "1.1rem",
                }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.failureRate")}
                value={perf?.failure_rate ?? 0}
                suffix="%"
                precision={2}
                valueStyle={{
                  color: (perf?.failure_rate ?? 0) > 1 ? "#ff4d4f" : "#52c41a",
                  fontSize: "1.1rem",
                }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.avgDuration")}
                value={perf?.avg_duration ?? 0}
                suffix={` ${t("monitoring.time.ms")}`}
                precision={0}
                valueStyle={{ color: "#722ed1", fontSize: "1.1rem" }}
              />
            </Card>
          </Col>
        </Row>
        <Row gutter={[16, 16]}>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.p50Duration")}
                value={perf?.p50_duration ?? 0}
                suffix={` ${t("monitoring.time.ms")}`}
                precision={0}
                valueStyle={{ fontSize: "1rem" }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.p95Duration")}
                value={perf?.p95_duration ?? 0}
                suffix={` ${t("monitoring.time.ms")}`}
                precision={0}
                valueStyle={{ fontSize: "1rem" }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.p99Duration")}
                value={perf?.p99_duration ?? 0}
                suffix={` ${t("monitoring.time.ms")}`}
                precision={0}
                valueStyle={{ fontSize: "1rem" }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.avgTTFT")}
                value={perf?.avg_ttft ?? 0}
                suffix={` ${t("monitoring.time.ms")}`}
                precision={0}
                valueStyle={{ color: "#13c2c2", fontSize: "1rem" }}
              />
            </Card>
          </Col>
        </Row>

        {summary?.error_breakdown && summary.error_breakdown.length > 0 && (
          <Card size="small" title={t("monitoring.detail.errorBreakdown")} className="shadow-sm">
            <div className="space-y-2">
              {summary.error_breakdown.map((err, idx) => (
                <div key={idx} className="flex items-center justify-between">
                  <span className="text-sm">
                    <Tag color={err.is_recoverable ? "orange" : "red"}>
                      {err.is_recoverable ? "Recoverable" : "Unrecoverable"}
                    </Tag>
                    {err.error_type}
                  </span>
                  <span className="text-sm text-slate-500">
                    {err.count} ({err.percentage}%)
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </Spin>
  );
}
