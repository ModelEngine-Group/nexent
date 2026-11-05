// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { Spinner } from "@/components/ui/spinner";

export interface LoadingIndicatorProps {
  className?: string;
}

/** Shared localized status behavior around the presentation-only spinner. */
export function LoadingIndicator({ className }: LoadingIndicatorProps) {
  const { t } = useTranslation("common");
  return (
    <span
      role="status"
      aria-label={t("common.loading")}
      className="inline-flex items-center"
    >
      <Spinner
        role="presentation"
        aria-hidden="true"
        aria-label={undefined}
        className={className}
      />
      <span className="sr-only">{t("common.loading")}</span>
    </span>
  );
}
