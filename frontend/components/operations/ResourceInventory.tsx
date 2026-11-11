// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Table, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { getResourceInventory } from "@/services/operationsService";

const RESOURCE_LABEL_KEYS = new Map([
  ["model", "tenantResources.tabs.models"],
  ["mcp", "tenantResources.tabs.mcp"],
  ["agent", "tenantResources.tabs.agents"],
  ["knowledge", "tenantResources.tabs.knowledge"],
]);

export function ResourceInventory() {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const query = useQuery({
    queryKey: [
      "opsResourceInventory",
      user?.id,
      user?.tenantId,
      page,
      pageSize,
    ],
    queryFn: () => getResourceInventory(page, pageSize),
    enabled: !!user,
  });
  return (
    <div className="p-6">
      <Typography.Title level={3}>
        {t("sidebar.resourceManage")}
      </Typography.Title>
      <Alert type="info" title={t("ops.readOnly")} className="mb-4" />
      {query.isError && <Alert type="error" title={t("ops.loadError")} />}
      <Table
        rowKey={(row) => `${row.kind}:${row.tenant_id}:${row.id}`}
        loading={query.isFetching}
        dataSource={query.data?.items ?? []}
        columns={[
          {
            key: "kind",
            dataIndex: "kind",
            title: t("common.type"),
            render: (kind: string) =>
              t(RESOURCE_LABEL_KEYS.get(kind) ?? "common.unknown"),
          },
          { key: "name", dataIndex: "name", title: t("common.name") },
          { key: "id", dataIndex: "id", title: "ID" },
        ]}
        pagination={{
          current: page,
          pageSize,
          total: query.data?.total ?? 0,
          onChange: (next, size) => {
            setPage(next);
            setPageSize(size);
          },
        }}
      />
    </div>
  );
}
