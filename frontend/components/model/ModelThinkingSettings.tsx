// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Form, Input, InputNumber, Select, Switch } from "antd";
import { useTranslation } from "react-i18next";
import type {
  ModelParameterRule,
  ThinkingDegreeMode,
} from "@/types/modelProfile";

export const thinkingDegreeKeys = [
  "reasoning_effort",
  "reasoning_budget_tokens",
];
export function detectThinkingMode(
  rules: ModelParameterRule[],
  values: Record<string, unknown>
): ThinkingDegreeMode {
  if (values.reasoning_budget_tokens !== undefined) return "budget_tokens";
  if (values.reasoning_effort !== undefined) return "effort";
  if (rules.some((rule) => rule.key === "reasoning_budget_tokens"))
    return "budget_tokens";
  if (rules.some((rule) => rule.key === "reasoning_effort")) return "effort";
  return "default";
}

/** Product controls; provider request-field bindings stay behind the profile API. */
export function ModelThinkingSettings({
  rules,
  values,
  defaults = {},
  mode,
  pending = false,
  onToggle,
  onModeChange,
  onValueChange,
}: {
  rules: ModelParameterRule[];
  values: Record<string, unknown>;
  defaults?: Record<string, unknown>;
  mode?: ThinkingDegreeMode;
  pending?: boolean;
  onToggle: (enabled: boolean) => void;
  onModeChange: (mode: ThinkingDegreeMode) => void;
  onValueChange: (key: string, value: unknown) => void;
}) {
  const { t } = useTranslation();
  const effective = { ...defaults, ...values };
  const toggle = rules.find((rule) => rule.key === "enable_thinking");
  const enabled = effective.enable_thinking === true;
  const selectedMode = mode ?? detectThinkingMode(rules, effective);
  const key =
    selectedMode === "effort" ? "reasoning_effort" : "reasoning_budget_tokens";
  const rule = rules.find((item) => item.key === key);
  const choices: unknown[] = Array.isArray(rule?.schema.enum)
    ? rule.schema.enum
    : ["low", "medium", "high"];
  const fixed = rule?.editable === false;
  return (
    <div className="grid grid-cols-1 items-start gap-x-4 sm:grid-cols-3">
      <Form.Item label={t("modelProfile.thinkingToggle")}>
        <div className="flex h-7 items-center">
          <Switch
            aria-label={t("modelProfile.thinkingToggle")}
            checked={enabled}
            disabled={pending || toggle?.editable === false}
            onChange={(enabled) => onToggle(enabled)}
          />
        </div>
      </Form.Item>
      {enabled && (
        <>
          <Form.Item label={t("modelProfile.thinkingMode")}>
            <Select
              aria-label={t("modelProfile.thinkingMode")}
              value={selectedMode}
              disabled={pending || fixed}
              getPopupContainer={(trigger) => trigger.parentElement!}
              options={(["default", "effort", "budget_tokens"] as const).map(
                (value) => ({
                  value,
                  label: t(`modelProfile.thinkingModeOption.${value}`),
                })
              )}
              onChange={onModeChange}
            />
          </Form.Item>
          <Form.Item label={t("modelProfile.thinkingDegree")}>
            {selectedMode === "default" ? (
              <Input
                disabled
                placeholder={t("modelProfile.thinkingServiceDefault")}
              />
            ) : selectedMode === "effort" ? (
              <Select
                aria-label={t("modelProfile.thinkingDegree")}
                value={
                  effective[key] === undefined
                    ? undefined
                    : JSON.stringify(effective[key])
                }
                placeholder={t("modelProfile.thinkingServiceDefault")}
                disabled={pending || fixed}
                getPopupContainer={(trigger) => trigger.parentElement!}
                options={choices.map((value) => ({
                  value: JSON.stringify(value),
                  label: String(value),
                }))}
                onChange={(value) => onValueChange(key, JSON.parse(value))}
              />
            ) : (
              <InputNumber
                aria-label={t("modelProfile.thinkingDegree")}
                className="!w-full"
                precision={0}
                value={
                  typeof effective[key] === "number"
                    ? (effective[key] as number)
                    : null
                }
                placeholder={t("modelProfile.thinkingServiceDefault")}
                min={
                  typeof rule?.schema.minimum === "number"
                    ? rule.schema.minimum
                    : rule
                      ? undefined
                      : 1
                }
                max={
                  typeof rule?.schema.maximum === "number"
                    ? rule.schema.maximum
                    : undefined
                }
                disabled={pending || fixed}
                onChange={(value) => onValueChange(key, value ?? undefined)}
              />
            )}
          </Form.Item>
        </>
      )}
    </div>
  );
}
