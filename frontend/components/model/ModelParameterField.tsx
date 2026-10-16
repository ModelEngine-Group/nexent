// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { RotateCcw } from "lucide-react";
import { Form, Input, InputNumber, Select, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardButton } from "@/components/common/StandardButton";
import type { ModelParameterRule } from "@/types/modelProfile";

interface ModelParameterFieldProps {
  rule: ModelParameterRule;
  values: Record<string, unknown>;
  fallbackValues?: Record<string, unknown>;
  pending?: boolean;
  resetLabel?: string;
  scope?: "outlet" | "conversation";
  onChange: (key: string, value: unknown) => void;
  onReset: (key: string) => void;
}

export function ModelParameterField({
  rule,
  values,
  fallbackValues = {},
  pending = false,
  resetLabel,
  scope = "outlet",
  onChange,
  onReset,
}: ModelParameterFieldProps) {
  const { t } = useTranslation();
  const changeValue = onChange;
  const resetValue = onReset;
  const value = Object.hasOwn(values, rule.key)
    ? values[rule.key]
    : fallbackValues[rule.key];
  const disabled =
    !rule.editable || !rule.allowed_scopes.includes(scope) || pending;
  const options = rule.schema.enum;
  let control;
  if (Array.isArray(options))
    control = (
      <Select
        getPopupContainer={(trigger) => trigger.parentElement!}
        aria-label={rule.key}
        value={value === undefined ? undefined : JSON.stringify(value)}
        disabled={disabled}
        options={options.map((option) => ({
          value: JSON.stringify(option),
          label: String(option),
        }))}
        onChange={(selected) => changeValue(rule.key, JSON.parse(selected))}
      />
    );
  else if ([rule.schema.type].flat().includes("boolean"))
    control = (
      <Switch
        aria-label={rule.key}
        checked={value === true}
        disabled={disabled}
        onChange={(checked) => changeValue(rule.key, checked)}
      />
    );
  else if (
    [rule.schema.type]
      .flat()
      .some((type) => type === "number" || type === "integer")
  )
    control = (
      <InputNumber
        className="!w-full"
        aria-label={rule.key}
        value={typeof value === "number" ? value : null}
        disabled={disabled}
        min={
          typeof rule.schema.minimum === "number"
            ? rule.schema.minimum
            : undefined
        }
        max={
          typeof rule.schema.maximum === "number"
            ? rule.schema.maximum
            : undefined
        }
        precision={
          [rule.schema.type].flat().includes("integer") &&
          ![rule.schema.type].flat().includes("number")
            ? 0
            : undefined
        }
        onChange={(next) => {
          if (next !== null || [rule.schema.type].flat().includes("null"))
            changeValue(rule.key, next);
          else resetValue(rule.key);
        }}
      />
    );
  else if (rule.schema.type === "object" || rule.schema.type === "array")
    control = (
      <Input.TextArea
        aria-label={rule.key}
        value={
          typeof value === "string"
            ? value
            : value === undefined
              ? ""
              : JSON.stringify(value)
        }
        disabled={disabled}
        rows={2}
        onChange={(event) => {
          try {
            changeValue(rule.key, JSON.parse(event.target.value));
          } catch {
            changeValue(rule.key, event.target.value);
          }
        }}
      />
    );
  else
    control = (
      <StandardInput
        aria-label={rule.key}
        value={
          typeof value === "string"
            ? value
            : value === undefined
              ? ""
              : JSON.stringify(value)
        }
        disabled={disabled}
        onChange={(event) => changeValue(rule.key, event.target.value)}
      />
    );
  return (
    <Form.Item
      key={rule.key}
      label={t(`modelProfile.parameterLabel.${rule.key}`, {
        defaultValue: rule.key,
      })}
    >
      <div className="flex min-h-8 items-center gap-2 [&>.ant-select]:w-full [&>.ant-switch]:shrink-0">
        {control}
        {Object.hasOwn(values, rule.key) && !disabled && (
          <StandardButton
            className="!w-8 !shrink-0 !px-0"
            aria-label={resetLabel ?? t("modelProfile.reset")}
            title={resetLabel ?? t("modelProfile.reset")}
            icon={<RotateCcw size={14} />}
            onClick={() => resetValue(rule.key)}
          />
        )}
      </div>
    </Form.Item>
  );
}
