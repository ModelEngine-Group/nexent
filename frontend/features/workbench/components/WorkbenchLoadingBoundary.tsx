// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";

interface WorkbenchLoadingBoundaryProps {
  conversationReady: boolean;
  modelsLoading: boolean;
  bootstrapLoading: boolean;
  resourcesResolving: boolean;
  children: ReactNode;
}

export function WorkbenchLoadingBoundary({
  conversationReady,
  modelsLoading,
  bootstrapLoading,
  resourcesResolving,
  children,
}: WorkbenchLoadingBoundaryProps) {
  const { t } = useTranslation();
  if (
    !conversationReady ||
    modelsLoading ||
    bootstrapLoading ||
    resourcesResolving
  ) {
    return (
      <div
        className="flex h-full items-center justify-center"
        role="status"
        aria-busy="true"
        aria-label={t("common.loading")}
      >
        <Spin />
        <span className="sr-only">{t("common.loading")}</span>
      </div>
    );
  }
  return children;
}
