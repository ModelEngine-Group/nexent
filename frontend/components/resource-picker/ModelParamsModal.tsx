// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { Select, Tooltip } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import { Plus, Trash2 } from "lucide-react";

import { SliderStepper } from "@/components/common/SliderStepper";

import type { ReasoningCapability, ReasoningEffort } from "@/types/modelConfig";
import {
  type ModelAdvancedSettingsValue,
  clampReasoningBudget,
  resolveReasoningControls,
  resolveReasoningDefault,
  useReasoningFormEffects,
} from "../../app/[locale]/models/components/model/ModelAdvancedSettings";

import {
  ParamDialog,
  ParamField,
  ParamInput,
  ParamSwitch,
} from "./ParamDialog";

// =============================================================================
// ModelParamsModal — design-spec modal for per-agent model parameter overrides.
// Reuses the ParamDialog design primitives (deep-thinking toggle and
// temperature / top-p sliders with steppers)
// while preserving the custom key/value params functionality.
// =============================================================================

interface ModelParamsModalProps {
  open: boolean;
  title?: string;
  onClose: () => void;
  onConfirm: () => void;
  /** Bound model options to switch between. */
  modelOptions: { value: number; label: string }[];
  selectedModelId: number | null;
  onSelectModel: (id: number) => void;
  /** Current form value (snake_case keys). */
  value: ModelAdvancedSettingsValue;
  onChange: (next: ModelAdvancedSettingsValue) => void;
  modelType?: string;
  reasoningCapability?: ReasoningCapability;
  inheritedDefaults?: Record<string, unknown>;
  disabled?: boolean;
}

export function ModelParamsModal({
  open,
  title,
  onClose,
  onConfirm,
  modelOptions,
  selectedModelId,
  onSelectModel,
  value,
  onChange,
  modelType = "llm",
  reasoningCapability,
  inheritedDefaults = {},
  disabled = false,
}: ModelParamsModalProps) {
  const { t } = useTranslation();

  // ---- Reasoning controls (shared resolution, see ModelAdvancedSettings) ----
  const { budgetControl, effectiveEffortControl, reasoningLevels } =
    resolveReasoningControls(reasoningCapability);
  const reasoningControlVisible = useReasoningFormEffects(
    modelType,
    reasoningCapability,
    value,
    onChange
  );

  const setNumberField = (key: string, raw: unknown) => {
    onChange({
      ...value,
      [key]: typeof raw === "number" && Number.isFinite(raw) ? raw : undefined,
    });
  };

  // ---- Custom key/value params ----
  const customEntries: [string, string][] = Array.isArray(value.__custom__)
    ? (value.__custom__ as [string, string][])
    : [];
  const setCustoms = (next: [string, string][]) =>
    onChange({ ...value, __custom__: next });
  const hasDuplicateKey = customEntries.some(
    ([k], i) => k !== "" && customEntries.findIndex(([k2]) => k2 === k) !== i
  );

  const thinkingEnabled = value.enable_thinking !== false;
  const reasoningEffort = value.reasoning_effort as ReasoningEffort | undefined;
  const reasoningDefault = resolveReasoningDefault(
    reasoningEffort,
    reasoningCapability,
    reasoningLevels
  );
  const reasoningBudget = clampReasoningBudget(
    budgetControl,
    value.reasoning_budget_tokens
  );

  const inheritedNumber = (key: string): number => {
    const raw = inheritedDefaults[key];
    return typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
  };

  return (
    <ParamDialog
      variant="model"
      open={open}
      title={title || t("modelParams.title", { defaultValue: "模型配置参数" })}
      onClose={onClose}
      onConfirm={onConfirm}
    >
      {/* Model selector + inherit hint */}
      <Select
        className="w-full"
        value={selectedModelId ?? undefined}
        options={modelOptions}
        disabled={disabled || modelOptions.length <= 1}
        onChange={(next: number) => onSelectModel(next)}
      />
      <p className="text-[12px] leading-[18px] text-[#999]">
        {t("model.advanced.overrideHint", {
          defaultValue: "留空表示继承模型默认值。",
        })}
      </p>

      {/* Deep thinking toggle */}
      {reasoningControlVisible && (
        <ParamField
          label={t("modelParams.thinking", { defaultValue: "深度思考" })}
          info
          size="md"
        >
          <ParamSwitch
            checked={thinkingEnabled}
            onChange={(checked) =>
              onChange({
                ...value,
                enable_thinking: checked,
                reasoning_effort:
                  checked && effectiveEffortControl?.type === "effort"
                    ? reasoningDefault
                    : undefined,
                reasoning_budget_tokens: checked
                  ? value.reasoning_budget_tokens
                  : undefined,
              })
            }
          />
        </ParamField>
      )}

      {/* Temperature slider */}
      <ParamField
        label={t("modelParams.temperature", { defaultValue: "温度" })}
        icon={
          <Tooltip
            title={t("modelParams.temperatureInfo")}
            trigger={["hover", "focus"]}
          >
            <QuestionCircleOutlined
              tabIndex={0}
              style={{ color: "#8C8C8C", fontSize: 12 }}
            />
          </Tooltip>
        }
      >
        <SliderStepper
          label={t("modelParams.temperature", { defaultValue: "输出内容温度" })}
          value={
            typeof value.temperature === "number"
              ? value.temperature
              : undefined
          }
          fallback={inheritedNumber("temperature")}
          min={0}
          max={2}
          step={0.1}
          disabled={disabled}
          onChange={(next) => setNumberField("temperature", next)}
        />
      </ParamField>

      {/* Top P slider */}
      <ParamField
        label={t("modelParams.topP", { defaultValue: "Top P" })}
        icon={
          <Tooltip
            title={t("modelParams.topPInfo")}
            trigger={["hover", "focus"]}
          >
            <QuestionCircleOutlined
              tabIndex={0}
              style={{ color: "#8C8C8C", fontSize: 12 }}
            />
          </Tooltip>
        }
      >
        <SliderStepper
          label={t("modelParams.topP", { defaultValue: "Top P" })}
          value={typeof value.top_p === "number" ? value.top_p : undefined}
          fallback={inheritedNumber("top_p")}
          min={0}
          max={1}
          step={0.1}
          disabled={disabled}
          onChange={(next) => setNumberField("top_p", next)}
        />
      </ParamField>

      {/* Reasoning effort / budget (advanced, capability-gated) */}
      {reasoningControlVisible &&
        thinkingEnabled &&
        effectiveEffortControl?.type === "effort" && (
          <ParamField
            label={t("model.advanced.reasoningEffort", {
              defaultValue: "思考挡位",
            })}
          >
            <Select
              className="w-full"
              value={
                reasoningEffort && reasoningLevels.includes(reasoningEffort)
                  ? reasoningEffort
                  : reasoningDefault
              }
              options={reasoningLevels.map((level) => ({
                value: level,
                label: level,
              }))}
              disabled={disabled}
              onChange={(next: ReasoningEffort | undefined) =>
                onChange({ ...value, reasoning_effort: next })
              }
            />
          </ParamField>
        )}
      {reasoningControlVisible &&
        thinkingEnabled &&
        budgetControl?.type === "budget_tokens" && (
          <ParamField
            label={t("model.advanced.reasoningBudget", {
              defaultValue: "预算 tokens",
            })}
          >
            <ParamInput
              type="number"
              value={reasoningBudget?.toString() ?? ""}
              placeholder={String(budgetControl.min)}
              onChange={(e) => {
                const raw = e.target.value;
                if (raw === "") {
                  onChange({ ...value, reasoning_budget_tokens: undefined });
                } else {
                  onChange({
                    ...value,
                    reasoning_budget_tokens: clampReasoningBudget(
                      budgetControl,
                      Number(raw)
                    ),
                  });
                }
              }}
            />
            <span className="text-[12px] leading-[18px] text-[#999]">
              {`${budgetControl.min} ~ ${budgetControl.max}`}
            </span>
          </ParamField>
        )}

      {/* Custom params */}
      <div className="border-t border-[#EFEFEF] pt-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="flex items-center gap-1 text-[12px] leading-[18px] text-[#393939]">
            <Tooltip
              title={t("model.advanced.customParamsHint", {
                defaultValue:
                  "自定义参数将原样传给模型提供方，请自行确认参数名与取值是否正确。",
              })}
            >
              <span>
                {t("model.advanced.customParams", {
                  defaultValue: "自定义参数",
                })}
              </span>
            </Tooltip>
          </span>
          <button
            type="button"
            disabled={disabled}
            onClick={() => setCustoms([...customEntries, ["", ""]])}
            className="flex h-6 cursor-pointer items-center gap-1 rounded-[2px] border border-dashed border-[#B8B8B8] bg-transparent px-2 text-[12px] text-[#191919] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus size={12} />
            {t("model.advanced.addCustomParam", { defaultValue: "添加参数" })}
          </button>
        </div>

        {customEntries.length === 0 ? (
          <div className="text-[12px] text-[#999]">
            {t("model.advanced.noCustomParams", {
              defaultValue: "暂无自定义参数",
            })}
          </div>
        ) : (
          <div className="space-y-2">
            {customEntries.map(([k, v], idx) => {
              const isDuplicate =
                k !== "" && customEntries.filter(([ek]) => ek === k).length > 1;
              return (
                <div
                  key={`custom-param-${idx}`}
                  className="flex items-center gap-2"
                >
                  <ParamInput
                    className="flex-1"
                    inputSize="sm"
                    placeholder={t("model.advanced.customKeyPlaceholder", {
                      defaultValue: "参数名",
                    })}
                    value={k}
                    disabled={disabled}
                    onChange={(e) => {
                      const next = customEntries.map(
                        (entry, i) =>
                          (i === idx ? [e.target.value, entry[1]] : entry) as [
                            string,
                            string,
                          ]
                      );
                      setCustoms(next);
                    }}
                  />
                  <ParamInput
                    className="flex-1"
                    inputSize="sm"
                    placeholder={t("model.advanced.customValuePlaceholder", {
                      defaultValue: "JSON 或字符串",
                    })}
                    value={v}
                    disabled={disabled}
                    onChange={(e) => {
                      const next = customEntries.map(
                        (entry, i) =>
                          (i === idx ? [entry[0], e.target.value] : entry) as [
                            string,
                            string,
                          ]
                      );
                      setCustoms(next);
                    }}
                  />
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() =>
                      setCustoms(customEntries.filter((_, i) => i !== idx))
                    }
                    className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center border-0 bg-transparent p-0 text-[#E34D59] disabled:opacity-40"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              );
            })}
            {hasDuplicateKey && (
              <div className="text-[12px] text-[#E34D59]">
                {t("model.advanced.duplicateKeyWarning", {
                  defaultValue:
                    "存在重复的参数名，请检查（重复参数保存时仅保留最后一个）。",
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </ParamDialog>
  );
}

export default ModelParamsModal;
