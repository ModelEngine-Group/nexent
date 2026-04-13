"use client";

import React from "react";
import { Card, Statistic, Row, Col, Spin, Empty } from "antd";
import { DollarOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ModelSummaryResponse } from "@/types/monitoring";

interface CostAnalysisChartsProps {
  summary: ModelSummaryResponse | null;
  loading: boolean;
}

export default function CostAnalysisCharts({ summary, loading }: CostAnalysisChartsProps) {
  const { t } = useTranslation("common");

  if (!summary && !loading) {
    return <Empty description="No data available" />;
  }

  const perf = summary?.performance;

  return (
    <Spin spinning={loading}>
      <div className="space-y-4">
        <Row gutter={[16, 16]}>
          <Col span={8}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.totalCost")}
                value={perf?.total_cost ?? 0}
                prefix="$"
                precision={2}
                valueStyle={{ color: "#13c2c2", fontSize: "1.2rem" }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.todayCost")}
                value={perf?.today_cost ?? 0}
                prefix="$"
                precision={4}
                valueStyle={{ color: "#1890ff", fontSize: "1.2rem" }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.totalTokens")}
                value={perf?.total_tokens ?? 0}
                valueStyle={{ fontSize: "1.2rem" }}
              />
            </Card>
          </Col>
        </Row>
        <Row gutter={[16, 16]}>
          <Col span={8}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.inputTokens")}
                value={perf?.input_tokens ?? 0}
                valueStyle={{ fontSize: "1rem" }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.outputTokens")}
                value={perf?.output_tokens ?? 0}
                valueStyle={{ fontSize: "1rem" }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" bordered={false} className="shadow-sm">
              <Statistic
                title={t("monitoring.detail.qualityScore")}
                value={perf?.quality_avg_score ?? 0}
                suffix="/100"
                precision={1}
                valueStyle={{
                  color: (perf?.quality_avg_score ?? 0) >= 90 ? "#52c41a" : "#faad14",
                  fontSize: "1rem",
                }}
              />
            </Card>
          </Col>
        </Row>
      </div>
    </Spin>
  );
}
