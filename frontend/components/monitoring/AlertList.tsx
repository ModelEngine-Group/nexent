"use client";

import React from "react";
import { Table, Tag, Button, Modal, Space, Empty, Spin } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { AlertRecord } from "@/types/monitoring";

interface AlertListProps {
  alerts: AlertRecord[];
  total: number;
  loading: boolean;
  onAcknowledge: (id: string) => Promise<boolean>;
  onResolve: (id: string) => Promise<boolean>;
}

export default function AlertList({
  alerts,
  total,
  loading,
  onAcknowledge,
  onResolve,
}: AlertListProps) {
  const { t } = useTranslation("common");

  const severityColor = (s: string) => {
    switch (s) {
      case "critical": return "red";
      case "warning": return "orange";
      case "info": return "blue";
      default: return "default";
    }
  };

  const statusColor = (s: string) => {
    switch (s) {
      case "active": return "red";
      case "acknowledged": return "orange";
      case "resolved": return "green";
      default: return "default";
    }
  };

  const handleAcknowledge = (alert: AlertRecord) => {
    Modal.confirm({
      title: t("monitoring.alerts.acknowledge"),
      icon: <ExclamationCircleOutlined />,
      content: alert.message,
      onOk: () => onAcknowledge(alert.id),
    });
  };

  const handleResolve = (alert: AlertRecord) => {
    Modal.confirm({
      title: t("monitoring.alerts.resolve"),
      icon: <ExclamationCircleOutlined />,
      content: alert.message,
      onOk: () => onResolve(alert.id),
    });
  };

  const columns = [
    {
      title: t("monitoring.table.severity"),
      dataIndex: "severity",
      key: "severity",
      width: 100,
      render: (v: string) => (
        <Tag color={severityColor(v)}>{t(`monitoring.alerts.${v}`)}</Tag>
      ),
    },
    {
      title: t("monitoring.table.type"),
      dataIndex: "type",
      key: "type",
      width: 180,
      ellipsis: true,
      render: (v: string) => v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    },
    {
      title: t("monitoring.table.modelName"),
      dataIndex: "model_name",
      key: "model_name",
      width: 150,
    },
    {
      title: t("monitoring.table.message"),
      dataIndex: "message",
      key: "message",
      ellipsis: true,
    },
    {
      title: t("monitoring.table.status"),
      dataIndex: "status",
      key: "status",
      width: 120,
      render: (v: string) => (
        <Tag color={statusColor(v)}>{t(`monitoring.alerts.filter${v.charAt(0).toUpperCase() + v.slice(1)}`)}</Tag>
      ),
    },
    {
      title: t("monitoring.table.createdAt"),
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: "Actions",
      key: "actions",
      width: 180,
      render: (_: unknown, record: AlertRecord) => (
        <Space size="small">
          {record.status === "active" && (
            <Button size="small" onClick={() => handleAcknowledge(record)}>
              {t("monitoring.alerts.acknowledge")}
            </Button>
          )}
          {record.status !== "resolved" && (
            <Button size="small" type="primary" onClick={() => handleResolve(record)}>
              {t("monitoring.alerts.resolve")}
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Spin spinning={loading}>
      {alerts.length === 0 && !loading ? (
        <Empty description={t("monitoring.alerts.noAlerts")} />
      ) : (
        <Table
          dataSource={alerts}
          columns={columns}
          rowKey="id"
          size="middle"
          pagination={{
            total,
            pageSize: 20,
            showSizeChanger: false,
            showTotal: (t) => `${t} alerts`,
          }}
        />
      )}
    </Spin>
  );
}
