// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ModelOption } from "@/types/modelConfig";

export function ModelMigrationBadge({
  model,
}: {
  model: Pick<ModelOption, "migrationStatus" | "migrationReviewRequired">;
}) {
  const { t } = useTranslation();
  if (!model.migrationStatus) return null;
  const state =
    model.migrationStatus === "failed"
      ? "failed"
      : model.migrationReviewRequired
        ? "pending"
        : "reviewed";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className="shrink-0 text-[10px] font-normal">
          {t(`modelMigration.${state}`)}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{t(`modelMigration.${state}Hint`)}</TooltipContent>
    </Tooltip>
  );
}
