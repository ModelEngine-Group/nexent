// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";

export default function ResourcePublishedAt({
  value,
  className = "block text-xs text-muted-foreground",
}: {
  value?: string | null;
  className?: string;
}) {
  const presentation = useRepositoryPresentation();
  const { t } = useTranslation("common");
  if (!presentation) return null;
  return (
    <span className={className}>
      {t("resourceCenter.publishedAt")}:{" "}
      {value
        ? new Date(value).toLocaleString()
        : t("resourceCenter.notRecorded")}
    </span>
  );
}
