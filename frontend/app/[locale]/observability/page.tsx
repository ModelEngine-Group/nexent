// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Alert, ConfigProvider, Spin } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { ObservabilityCenter } from "./components/ObservabilityCenter";
import "./trajectory.css";

export default function ObservabilityPage() {
  const { t, i18n } = useTranslation();
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
    <ConfigProvider
      locale={i18n?.language?.startsWith("en") ? enUS : zhCN}
      theme={{
        token: {
          colorPrimary: "#0067d1",
          colorText: "#191919",
          colorTextSecondary: "#777777",
          colorBorder: "#c9c9c9",
          colorBorderSecondary: "#f0f0f0",
          fontFamily:
            '"HarmonyOS Sans SC", "Huawei Sans", -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
          fontSize: 14,
          lineHeight: 22 / 14,
          controlHeight: 28,
          borderRadius: 4,
        },
        components: {
          Table: {
            headerBg: "#f3f3f3",
            headerColor: "#191919",
            headerSplitColor: "#c9c9c9",
            borderColor: "#f0f0f0",
            cellPaddingInlineMD: 12,
            rowHoverBg: "#f5f8fc",
          },
        },
      }}
    >
      <ObservabilityCenter
        key={JSON.stringify([user.id, user.tenantId, user.role])}
        user={user}
      />
    </ConfigProvider>
  );
}
