// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

export function ConversationRunIndicator({
  running,
  completed,
}: {
  running: boolean;
  completed: boolean;
}) {
  const { t } = useTranslation();
  const visibility =
    "shrink-0 group-hover/item:invisible group-focus-within/item:invisible";
  if (running)
    return (
      <LoaderCircle
        role="status"
        aria-label={t("chat.threadList.running")}
        className={`size-3 animate-spin text-muted-foreground ${visibility}`}
      />
    );
  if (completed)
    return (
      <span
        title={t("chat.threadList.completed")}
        role="status"
        aria-label={t("chat.threadList.completed")}
        className={`size-2 rounded-full bg-primary ${visibility}`}
      />
    );
  return null;
}
