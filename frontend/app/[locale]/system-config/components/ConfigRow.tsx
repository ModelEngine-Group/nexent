// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { InputNumber, Switch, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { AlertTriangle, RotateCcw } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ConfigItem, ConfigValue } from "../systemConfigData";
import { formatConfigValue } from "../systemConfigFormat";

interface ConfigRowProps {
  item: ConfigItem;
  value: ConfigValue | null;
  modified: boolean;
  errorKey: string | null;
  onValueChange: (value: ConfigValue | null) => void;
  onReset: () => void;
}

export function ConfigRow({
  item,
  value,
  modified,
  errorKey,
  onValueChange,
  onReset,
}: ConfigRowProps) {
  const { t } = useTranslation("common");
  const label = t(item.label_key);

  return (
    <div
      data-testid={`config-row-${item.key}`}
      className="grid grid-cols-[minmax(280px,1.7fr)_190px_160px_32px] items-center gap-4 px-5 py-4"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-[14px] font-medium text-[var(--color-text-primary)]">
            {label}
          </span>
          {modified ? (
            <span className="shrink-0 rounded-xs bg-[var(--color-select)] px-1.5 py-0.5 text-[11px] text-[var(--color-brand)]">
              {t("systemConfig.modifiedTag")}
            </span>
          ) : null}
        </div>
        <code className="mt-1 block truncate font-mono text-[11px] text-[var(--color-text-secondary)]">
          {item.key}
        </code>
        <p className="mt-1 text-[12px] leading-5 text-[var(--color-text-secondary)]">
          {t(item.description_key)}
        </p>
        <p className="mt-0.5 text-[11px] text-[var(--color-icon-tertiary)]">
          {t(item.effect_key)}
        </p>
      </div>
      <div>
        {item.kind === "boolean" ? (
          <div className="flex items-center gap-2">
            <Switch
              size="small"
              checked={value === true}
              onChange={onValueChange}
              aria-label={label}
            />
            <span className="text-[12px] text-[var(--color-text-secondary)]">
              {formatConfigValue(item, value, t)}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <InputNumber
              size="small"
              value={typeof value === "number" ? value : null}
              min={item.kind === "integer" ? 1 : undefined}
              step={item.kind === "integer" ? 1 : 0.1}
              precision={item.kind === "integer" ? 0 : undefined}
              controls={false}
              status={errorKey ? "error" : undefined}
              onChange={onValueChange}
              aria-label={label}
              className={cn(
                "!w-[126px]",
                modified && !errorKey && "!border-[var(--color-brand)]"
              )}
            />
            {item.unit_key ? (
              <span className="text-[11px] text-[var(--color-text-secondary)]">
                {t(item.unit_key)}
              </span>
            ) : null}
          </div>
        )}
        <div className="mt-1.5 min-h-[18px] text-[11px]">
          {errorKey ? (
            <span className="inline-flex items-center gap-1 text-[var(--color-error)]">
              <AlertTriangle className="h-3 w-3" />
              {t(errorKey)}
            </span>
          ) : modified ? (
            <span className="text-[var(--color-text-secondary)]">
              {t("systemConfig.originalValue")}{" "}
              {formatConfigValue(item, item.value, t)}
            </span>
          ) : null}
        </div>
      </div>
      <div className="text-[12px] leading-5 text-[var(--color-text-secondary)]">
        {item.kind === "boolean"
          ? t("systemConfig.booleanRange")
          : item.kind === "integer"
            ? t("systemConfig.integerRange")
            : t("systemConfig.numberRange")}
        <div className="text-[11px] text-[var(--color-icon-tertiary)]">
          {item.kind === "boolean"
            ? t("systemConfig.booleanType")
            : item.kind === "integer"
              ? t("systemConfig.integerType")
              : t("systemConfig.decimalType")}
        </div>
      </div>
      <Tooltip title={t("systemConfig.resetDefault")}>
        <button
          type="button"
          onClick={onReset}
          aria-label={t("systemConfig.resetDefaultFor", { name: label })}
          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-xs border-0 bg-transparent text-[var(--color-icon-tertiary)] hover:bg-[var(--color-hover)] hover:text-[var(--color-icon-hover)]"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      </Tooltip>
    </div>
  );
}
