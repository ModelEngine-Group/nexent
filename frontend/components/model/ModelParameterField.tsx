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
  label?: string;
  hideReset?: boolean;
  scope?: "outlet" | "conversation";
  inModelSelector?: boolean;
  onChange: (key: string, value: unknown) => void;
  onReset: (key: string) => void;
}

export function ModelParameterField({
  rule,
  values,
  fallbackValues = {},
  pending = false,
  resetLabel,
  label,
  hideReset = false,
  scope = "outlet",
  inModelSelector = false,
  onChange,
  onReset,
}: ModelParameterFieldProps) {
  const { t } = useTranslation();
  const value = Object.hasOwn(values, rule.key)
    ? values[rule.key]
    : fallbackValues[rule.key];
  const disabled =
    !rule.editable || !rule.allowed_scopes.includes(scope) || pending;
  const options = rule.schema.enum;
  const types = [rule.schema.type].flat();
  let control;
  if (Array.isArray(options))
    control = (
      <Select
        className={
          inModelSelector
            ? "!w-auto min-w-0 [&.ant-select-disabled]:!bg-transparent"
            : undefined
        }
        variant={inModelSelector ? "borderless" : "outlined"}
        styles={
          inModelSelector ? { popup: { root: { zIndex: 1200 } } } : undefined
        }
        getPopupContainer={(trigger) =>
          inModelSelector ? document.body : trigger.parentElement!
        }
        popupRender={
          inModelSelector
            ? (menu) => <div data-model-effort-popup>{menu}</div>
            : undefined
        }
        aria-label={label ?? rule.key}
        value={value === undefined ? undefined : JSON.stringify(value)}
        disabled={disabled}
        options={options.map((option) => ({
          value: JSON.stringify(option),
          label:
            rule.key === "reasoning_effort"
              ? t(`modelProfile.thinkingLevel.${String(option)}`, {
                  defaultValue: String(option),
                })
              : String(option),
        }))}
        onChange={(selected) => onChange(rule.key, JSON.parse(selected))}
      />
    );
  else if (types.includes("boolean"))
    control = (
      <Switch
        aria-label={label ?? rule.key}
        checked={value === true}
        disabled={disabled}
        onChange={(checked) => onChange(rule.key, checked)}
      />
    );
  else if (types.some((type) => type === "number" || type === "integer"))
    control = (
      <InputNumber
        className="!w-full"
        aria-label={label ?? rule.key}
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
          types.includes("integer") && !types.includes("number") ? 0 : undefined
        }
        onChange={(next) => {
          if (next !== null || types.includes("null")) onChange(rule.key, next);
          else onReset(rule.key);
        }}
      />
    );
  else if (rule.schema.type === "object" || rule.schema.type === "array")
    control = (
      <Input.TextArea
        aria-label={label ?? rule.key}
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
            onChange(rule.key, JSON.parse(event.target.value));
          } catch {
            onChange(rule.key, event.target.value);
          }
        }}
      />
    );
  else
    control = (
      <StandardInput
        aria-label={label ?? rule.key}
        value={
          typeof value === "string"
            ? value
            : value === undefined
              ? ""
              : JSON.stringify(value)
        }
        disabled={disabled}
        onChange={(event) => onChange(rule.key, event.target.value)}
      />
    );
  return (
    <Form.Item
      required={scope === "outlet" && rule.required}
      label={
        label ??
        t(`modelProfile.parameterLabel.${rule.key}`, {
          defaultValue: rule.key,
        })
      }
    >
      <div
        className={
          inModelSelector
            ? "flex min-h-8 items-center justify-end gap-2 [&>.ant-switch]:shrink-0"
            : "flex min-h-8 items-center gap-2 [&>.ant-select]:w-full [&>.ant-switch]:shrink-0"
        }
      >
        {control}
        {!hideReset &&
          Object.hasOwn(values, rule.key) &&
          !disabled &&
          !(scope === "outlet" && rule.required) && (
            <StandardButton
              className="!w-8 !shrink-0 !px-0"
              aria-label={resetLabel ?? t("modelProfile.reset")}
              title={resetLabel ?? t("modelProfile.reset")}
              icon={<RotateCcw size={14} />}
              onClick={() => onReset(rule.key)}
            />
          )}
      </div>
    </Form.Item>
  );
}
