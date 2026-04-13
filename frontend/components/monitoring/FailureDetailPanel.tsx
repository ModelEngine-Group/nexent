"use client";

import React from "react";
import { Table, Tag, Card, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import type { FailureDetail, PaginatedData } from "@/types/monitoring";

interface FailureDetailPanelProps {
  failures: PaginatedData<FailureDetail>;
  loading: boolean;
}

export default function FailureDetailPanel({ failures, loading }: FailureDetailPanelProps) {
  const { t } = useTranslation("common");

  const columns = [
    {
      title: t("monitoring.failures.timestamp"),
      dataIndex: "timestamp",
      key: "timestamp",
      width: 180,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: t("monitoring.failures.type"),
      dataIndex: "failure_type",
      key: "failure_type",
      width: 180,
      render: (v: string) => <Tag color="red">{v}</Tag>,
    },
    {
      title: t("monitoring.failures.errorMessage"),
      dataIndex: "error_message",
      key: "error_message",
      ellipsis: true,
    },
    {
      title: t("monitoring.failures.duration"),
      dataIndex: "request_duration",
      key: "request_duration",
      width: 120,
      render: (v: number) => `${v.toFixed(0)} ${t("monitoring.time.ms")}`,
    },
    {
      title: t("monitoring.failures.statusCode"),
      dataIndex: "status_code",
      key: "status_code",
      width: 100,
      render: (v: number) => {
        const color = v >= 500 ? "red" : v >= 400 ? "orange" : "blue";
        return <Tag color={color}>{v}</Tag>;
      },
    },
  ];

  return (
    <Spin spinning={loading}>
      {failures.items.length === 0 && !loading ? (
        <Empty description={t("monitoring.alerts.noAlerts")} />
      ) : (
        <Table
          dataSource={failures.items}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={{
            total: failures.total,
            pageSize: failures.page_size,
            current: failures.page,
            showSizeChanger: false,
            showTotal: (total) => `${total} records`,
          }}
        />
      )}
    </Spin>
  );
}
