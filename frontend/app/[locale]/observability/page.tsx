// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Alert, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { ObservabilityCenter } from "./components/ObservabilityCenter";
import "./trajectory.css";

export default function ObservabilityPage() {
  const { t } = useTranslation();
  const { user, isAuthzReady, accessibleRoutes } = useAuthorizationContext();
  if (!isAuthzReady)
    return (
      <div className="p-6">
        <Spin />
      </div>
    );
  if (
    !user ||
    !["ADMIN", "SU"].includes(user.role) ||
    !accessibleRoutes.includes("/observability")
  ) {
    return (
      <div className="p-6">
        <Alert type="error" title={t("trajectory.forbidden")} />
      </div>
    );
  }
  return (
    <ObservabilityCenter
      key={JSON.stringify([user.id, user.tenantId, user.role])}
      user={user}
    />
  );
}
