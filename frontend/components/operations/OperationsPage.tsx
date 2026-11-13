// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Empty, Select, Space, Spin, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { hasRole } from "@/lib/roles";
import { checkOperationsScope } from "@/services/operationsService";
import { listTenants } from "@/services/tenantService";

export function OperationsPage({
  module,
}: {
  module: "dashboard" | "configuration";
}) {
  const { t } = useTranslation("common");
  const { user, hasPermission } = useAuthorizationContext();
  const [tenantId, setTenantId] = useState<string | undefined>();
  const allowed = hasPermission(`ops.${module}:read`);
  const tenants = useQuery({
    queryKey: ["opsTenantChoices", user?.id],
    queryFn: () => listTenants({ page: 1, page_size: 100 }),
    enabled: allowed && hasRole(user, "SU"),
  });
  const scope = useQuery({
    queryKey: ["opsScope", module, tenantId, user?.id],
    queryFn: () => checkOperationsScope(module, tenantId),
    enabled: allowed,
  });
  if (!allowed) return <Alert type="warning" title={t("ops.noPermission")} />;
  return (
    <div className="p-6">
      <Space orientation="vertical" className="w-full" size="large">
        <Typography.Title level={3}>{t(`ops.${module}`)}</Typography.Title>
        {hasRole(user, "SU") ? (
          <Select
            aria-label={t("ops.tenant")}
            className="min-w-60"
            loading={tenants.isFetching}
            value={tenantId ?? ""}
            onChange={(value) => setTenantId(value || undefined)}
            options={[
              { value: "", label: t("ops.allTenants") },
              ...(tenants.data?.data ?? []).map((tenant) => ({
                value: tenant.tenant_id,
                title: tenant.tenant_id,
                label: tenant.tenant_name || tenant.tenant_id,
              })),
            ]}
          />
        ) : (
          <Typography.Text>
            {t("ops.tenant")}: {user?.tenantId}
          </Typography.Text>
        )}
        {scope.isError && <Alert type="error" title={t("ops.loadError")} />}
        <Card>
          {scope.isFetching ? <Spin /> : <Empty description={t("ops.empty")} />}
        </Card>
      </Space>
    </div>
  );
}
