// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Card } from "antd";
import { Database, Layers3, PencilLine, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";

interface ConfigSummaryProps {
  itemCount: number;
  groupCount: number;
  modifiedCount: number;
}

export function ConfigSummary({
  itemCount,
  groupCount,
  modifiedCount,
}: ConfigSummaryProps) {
  const { t } = useTranslation("common");
  const cards = [
    {
      id: "managed",
      icon: SlidersHorizontal,
      label: t("systemConfig.metric.managed"),
      value: t("systemConfig.metric.managedValue", { count: itemCount }),
      hint: t("systemConfig.metric.managedHint"),
    },
    {
      id: "groups",
      icon: Layers3,
      label: t("systemConfig.metric.groups"),
      value: t("systemConfig.metric.groupsValue", { count: groupCount }),
      hint: t("systemConfig.metric.groupsHint"),
    },
    {
      id: "modified",
      icon: PencilLine,
      label: t("systemConfig.metric.modified"),
      value: t("systemConfig.metric.modifiedValue", {
        count: modifiedCount,
      }),
      hint: modifiedCount
        ? t("systemConfig.metric.modifiedHint")
        : t("systemConfig.metric.modifiedNone"),
    },
    {
      id: "source",
      icon: Database,
      label: t("systemConfig.metric.source"),
      value: "PostgreSQL",
      hint: t("systemConfig.metric.sourceHint"),
    },
  ];

  return (
    <div
      data-testid="config-summary"
      className="grid grid-cols-2 gap-3 xl:grid-cols-4"
    >
      {cards.map(({ id, icon: Icon, label, value, hint }) => (
        <Card
          key={id}
          size="small"
          data-testid={`config-summary-${id}`}
          className="rounded-lg border border-[var(--color-border-separator-subtle)] bg-[var(--color-bg-5)] shadow-sm transition-shadow duration-150 hover:shadow-md"
        >
          <div className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-secondary)]">
            <Icon className="h-3.5 w-3.5 text-[var(--color-brand)]" />
            <span>{label}</span>
          </div>
          <div className="mt-1 truncate text-[20px] font-semibold leading-6 text-[var(--color-text-primary)]">
            {value}
          </div>
          <div className="mt-0.5 truncate text-[12px] text-[var(--color-text-secondary)]">
            {hint}
          </div>
        </Card>
      ))}
    </div>
  );
}
