// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { Button, InputNumber, Switch, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { AlertTriangle, ChevronDown, RefreshCw, RotateCcw } from "lucide-react";

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
  const [expanded, setExpanded] = useState(false);
  const kindLabel =
    item.kind === "boolean"
      ? t("systemConfig.booleanType")
      : item.kind === "integer"
        ? t("systemConfig.integerType")
        : t("systemConfig.decimalType");

  return (
    <div
      data-testid={`config-row-${item.key}`}
      className="transition-colors hover:bg-[var(--color-hover)]"
    >
      <div className="grid grid-cols-[minmax(280px,1.7fr)_190px_160px_180px_32px] items-center gap-4 px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <label
              htmlFor={`config-input-${item.key}`}
              className="truncate text-[13px] font-medium text-[var(--color-text-primary)]"
            >
              {label}
            </label>
            {modified ? (
              <span className="shrink-0 rounded-xs bg-[var(--color-select)] px-1.5 py-0.5 text-[10px] text-[var(--color-brand)]">
                {t("systemConfig.modifiedTag")}
              </span>
            ) : null}
          </div>
          <code className="mt-0.5 block truncate font-mono text-[12px] text-[var(--color-text-secondary)]">
            {item.key}
          </code>
          <p className="mt-1 text-[12px] leading-5 text-[var(--color-text-secondary)]">
            {t(item.description_key)}
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
                ref={(input) => {
                  const element = input?.nativeElement?.querySelector("input");
                  if (element) element.id = `config-input-${item.key}`;
                }}
                className={cn(
                  "!w-[112px]",
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
          <div className="mt-1 min-h-[16px] text-[12px]">
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
          <div className="text-[12px] text-[var(--color-icon-tertiary)]">
            {kindLabel}
          </div>
        </div>
        <div>
          <Tag
            color="success"
            icon={<RefreshCw className="h-3 w-3" />}
            className="m-0 inline-flex items-center gap-1 !text-[var(--color-success-active)]"
          >
            {t("systemConfig.hotUpdateTag")}
          </Tag>
          <div className="mt-1 text-[12px] leading-5 text-[var(--color-text-secondary)]">
            {t(item.effect_key)}
          </div>
        </div>
        <Tooltip
          title={
            expanded ? t("systemConfig.collapse") : t("systemConfig.expand")
          }
        >
          <Button
            type="text"
            size="small"
            aria-label={t(
              expanded
                ? "systemConfig.detail.closeFor"
                : "systemConfig.detail.openFor",
              { name: label }
            )}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
            icon={
              <ChevronDown
                className={`h-4 w-4 transition-transform duration-150 ${expanded ? "rotate-180" : ""}`}
              />
            }
          />
        </Tooltip>
      </div>
      {expanded ? (
        <div
          data-testid={`config-detail-${item.key}`}
          className="border-t border-[var(--color-border-separator-subtle)] bg-[var(--color-fill)] px-5 py-3"
        >
          <div className="mb-3 flex justify-end">
            <Button
              type="text"
              size="small"
              onClick={onReset}
              aria-label={t("systemConfig.resetDefaultFor", { name: label })}
              icon={<RotateCcw className="h-3.5 w-3.5" />}
            >
              {t("systemConfig.resetDefault")}
            </Button>
          </div>
          <dl className="grid grid-cols-1 gap-x-8 gap-y-2.5 md:grid-cols-2 xl:grid-cols-3">
            {[
              [
                t("systemConfig.detail.savedValue"),
                formatConfigValue(item, item.value, t),
              ],
              [
                t("systemConfig.detail.defaultValue"),
                formatConfigValue(item, item.default_value, t),
              ],
              [
                t("systemConfig.detail.group"),
                t(`systemConfig.group.${item.group}`),
              ],
              [t("systemConfig.detail.kind"), kindLabel],
              [t("systemConfig.detail.effect"), t(item.effect_key)],
              [t("systemConfig.detail.source"), "PostgreSQL"],
            ].map(([term, description]) => (
              <div
                key={term}
                className="grid grid-cols-[110px_minmax(0,1fr)] gap-3"
              >
                <dt className="text-[12px] text-[var(--color-text-secondary)]">
                  {term}
                </dt>
                <dd className="break-words text-[12px] font-medium text-[var(--color-text-primary)]">
                  {description}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </div>
  );
}
