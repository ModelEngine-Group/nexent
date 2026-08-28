"use client";

import React, { useMemo, useState } from "react";
import { App, Button, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { RefreshCw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useApiKeyList } from "@/hooks/user/useApiKeyList";
import {
  refreshTenantApiKey,
  revokeTenantApiKeys,
  type TenantApiKey,
} from "@/services/apiKeyService";

const PAGE_SIZE = 10;

function formatTime(value?: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

export default function ApiKeyList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const [page, setPage] = useState(1);
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);
  const { data, isLoading, refetch } = useApiKeyList(tenantId, page, PAGE_SIZE);

  const refreshKey = async (record: TenantApiKey) => {
    setPendingUserId(record.user_id);
    try {
      const result = await refreshTenantApiKey(record.user_id);
      await refetch();
      modal.success({
        title: t("tenantResources.apiKeys.refreshSuccess"),
        content: (
          <code className="block break-all mt-3">{result.api_key}</code>
        ),
      });
    } catch (error: any) {
      message.error(
        error?.message || t("tenantResources.apiKeys.refreshFailed")
      );
    } finally {
      setPendingUserId(null);
    }
  };

  const revokeKey = async (record: TenantApiKey) => {
    setPendingUserId(record.user_id);
    try {
      await revokeTenantApiKeys(record.user_id);
      message.success(t("tenantResources.apiKeys.revokeSuccess"));
      await refetch();
    } catch (error: any) {
      message.error(
        error?.message || t("tenantResources.apiKeys.revokeFailed")
      );
    } finally {
      setPendingUserId(null);
    }
  };

  const columns: ColumnsType<TenantApiKey> = useMemo(
    () => [
      {
        title: t("tenantResources.apiKeys.key"),
        dataIndex: "access_key",
        key: "access_key",
        width: 320,
        render: (key: string) => <code className="whitespace-nowrap">{key}</code>,
      },
      {
        title: t("tenantResources.apiKeys.ownerEmail"),
        dataIndex: "owner_email",
        key: "owner_email",
        render: (value?: string | null) =>
          value || (
            <span className="text-gray-400">
              {t("tenantResources.apiKeys.virtualApiAccount")}
            </span>
          ),
      },
      {
        title: t("tenantResources.apiKeys.ownerRole"),
        dataIndex: "owner_role",
        key: "owner_role",
        width: 120,
        render: (role?: string | null) => {
          if (!role) return "-";
          const normalizedRole = role === "SU" ? "SUPER_ADMIN" : role;
          const roleLabels: Record<string, string> = {
            SUPER_ADMIN: t("user.role.superAdmin"),
            ADMIN: t("user.role.admin"),
            DEV: t("user.role.dev"),
            USER: t("user.role.user"),
            ASSET_OWNER: t("user.role.assetOwner"),
          };
          const color =
            normalizedRole === "SUPER_ADMIN"
              ? "magenta"
              : normalizedRole === "ADMIN"
                ? "purple"
                : normalizedRole === "DEV"
                  ? "cyan"
                  : normalizedRole === "USER"
                    ? "blue"
                    : normalizedRole === "ASSET_OWNER"
                      ? "gold"
                      : "gray";
          return <Tag color={color}>{roleLabels[normalizedRole] || role}</Tag>;
        },
      },
      {
        title: t("tenantResources.apiKeys.creatorEmail"),
        dataIndex: "creator_email",
        key: "creator_email",
        render: (value?: string | null) => value || "-",
      },
      {
        title: t("tenantResources.apiKeys.createdAt"),
        dataIndex: "create_time",
        key: "create_time",
        width: 160,
        render: formatTime,
      },
      {
        title: t("tenantResources.apiKeys.lastUsedAt"),
        dataIndex: "last_used_time",
        key: "last_used_time",
        width: 160,
        render: (value?: string | null) =>
          value ? (
            formatTime(value)
          ) : (
            <span className="text-gray-400">
              {t("tenantResources.apiKeys.neverUsed")}
            </span>
          ),
      },
      {
        title: (
          <span className="whitespace-nowrap">
            {t("tenantResources.apiKeys.usageCount")}
          </span>
        ),
        dataIndex: "total_usage_count",
        key: "total_usage_count",
        width: 130,
      },
      {
        title: t("common.actions"),
        key: "actions",
        width: 100,
        render: (_, record) => (
          <div className="flex items-center gap-1">
            <Button
              type="text"
              size="small"
              loading={pendingUserId === record.user_id}
              icon={<RefreshCw className="h-4 w-4" />}
              onClick={() => modal.confirm({
                title: t("tenantResources.apiKeys.confirmRefresh"),
                content: t("tenantResources.apiKeys.affectsAll"),
                centered: true,
                okText: t("common.confirm"),
                cancelText: t("common.cancel"),
                onOk: () => refreshKey(record),
              })}
            />
            <Button
              type="text"
              danger
              size="small"
              disabled={pendingUserId === record.user_id}
              icon={<Trash2 className="h-4 w-4" />}
              onClick={() => modal.confirm({
                title: t("tenantResources.apiKeys.confirmRevoke"),
                content: t("tenantResources.apiKeys.affectsAll"),
                centered: true,
                okText: t("common.confirm"),
                cancelText: t("common.cancel"),
                okButtonProps: { danger: true },
                onOk: () => revokeKey(record),
              })}
            />
          </div>
        ),
      },
    ],
    [pendingUserId, t]
  );

  return (
    <Table
      dataSource={data?.items ?? []}
      columns={columns}
      rowKey="token_id"
      loading={isLoading}
      pagination={{
        current: page,
        pageSize: PAGE_SIZE,
        total: data?.total ?? 0,
        onChange: setPage,
        showSizeChanger: false,
      }}
      scroll={{ x: 1450, y: "calc(100vh - 480px)" }}
    />
  );
}
