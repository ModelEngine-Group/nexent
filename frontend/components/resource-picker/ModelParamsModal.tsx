"use client";

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Select, Tooltip } from "antd";
import {
  InfoCircleOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import { Minus, Plus, Trash2 } from "lucide-react";

import type {
  ReasoningCapability,
  ReasoningEffort,
} from "@/types/modelConfig";
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
// Reuses the ParamDialog design primitives (deep-thinking toggle, capacity
// token grid with info/suggestion, temperature / top-p sliders with steppers)
// while preserving the custom key/value params functionality.
// =============================================================================

const numberText = (value: unknown): string =>
  typeof value === "number" && Number.isFinite(value) ? String(value) : "";

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

const roundStep = (value: number, step: number): number => {
  const decimals = (String(step).split(".")[1] ?? "").length;
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
};

interface SliderStepperProps {
  value: number | undefined;
  fallback: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  onChange: (next: number | undefined) => void;
}

// Five segments -> only the four interior dividers (no ticks at either end).
const TICK_POSITIONS = [20, 40, 60, 80];

function SliderStepper({
  value,
  fallback,
  min,
  max,
  step,
  disabled = false,
  onChange,
}: SliderStepperProps) {
  const display = value ?? fallback;
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const range = max - min || 1;
  const pct = ((display - min) / range) * 100;

  const set = (next: number) =>
    onChange(roundStep(clamp(next, min, max), step));

  const valueFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return display;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0) return display;
    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1);
    return roundStep(min + ratio * range, step);
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    set(valueFromClientX(e.clientX));
  };
  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    set(valueFromClientX(e.clientX));
  };
  const handlePointerUp = () => setDragging(false);

  return (
    <div className="flex items-center gap-3">
      {/* Segmented slider */}
      <div className="flex-1 select-none">
        <div className="relative pt-2">
          {/* Four interior tick marks above the track */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[6px]">
            {TICK_POSITIONS.map((pos) => (
              <span
                key={pos}
                className="absolute top-0 h-[6px] w-[2px] -translate-x-1/2 rounded-full bg-[#2196F3] opacity-60"
                style={{ left: `${pos}%` }}
              />
            ))}
          </div>
          {/* Track */}
          <div
            ref={trackRef}
            className="relative h-1 cursor-pointer touch-none rounded-full bg-[#E0E0E0]"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
          >
            <div
              className="absolute left-0 top-0 h-full rounded-full bg-[#2196F3]"
              style={{ width: `${pct}%` }}
            />
            <div
              className="absolute top-1/2 h-[10px] w-[10px] -translate-x-1/2 -translate-y-1/2 rounded-full border border-[#E0E0E0] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.15)]"
              style={{ left: `${pct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Spinner (value + - / + inside a single frame, 112x32, padding 5px 8px) */}
      <div
        className={`flex h-8 w-[112px] shrink-0 items-center justify-between rounded border border-[#E6E6E6] bg-white px-2 py-[5px] ${
          disabled ? "opacity-50" : ""
        }`}
      >
        <input
          type="number"
          value={display}
          disabled={disabled}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(undefined);
            } else {
              set(Number(raw));
            }
          }}
          className="h-full min-w-0 flex-1 border-0 bg-transparent text-left text-[14px] leading-[22px] text-[#808080] outline-none"
        />
        <button
          type="button"
          onClick={() => set(display - step)}
          disabled={disabled}
          className="flex h-5 w-5 shrink-0 items-center justify-center text-[#BDBDBD] disabled:cursor-not-allowed"
        >
          <Minus size={12} />
        </button>
        <span className="mx-[3px] h-[14px] w-px shrink-0 bg-[#E6E6E6]" />
        <button
          type="button"
          onClick={() => set(display + step)}
          disabled={disabled}
          className="flex h-5 w-5 shrink-0 items-center justify-center text-[#424242] disabled:cursor-not-allowed"
        >
          <Plus size={12} />
        </button>
      </div>
    </div>
  );
}

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

  const tokenFields = [
    {
      key: "context_window_tokens",
      label: t("modelParams.token.contextWindow", {
        defaultValue: "上下文总Token数",
      }),
      hint: t("modelParams.token.contextWindowHint", {
        defaultValue: "建议：500000-2000000",
      }),
      info: t("modelParams.token.contextWindowInfo", {
        defaultValue: "模型一次处理的最大上下文长度",
      }),
    },
    {
      key: "max_input_tokens",
      label: t("modelParams.token.maxInput", {
        defaultValue: "最大输入Token数",
      }),
      hint: t("modelParams.token.maxInputHint", {
        defaultValue: "建议预留输出Token空间",
      }),
      info: t("modelParams.token.maxInputInfo", {
        defaultValue: "单次请求允许的最大输入长度",
      }),
    },
    {
      key: "max_output_tokens",
      label: t("modelParams.token.maxOutput", {
        defaultValue: "最大输出Token数",
      }),
      hint: t("modelParams.token.maxOutputHint", {
        defaultValue: "建议控制输出以减少预算",
      }),
      info: t("modelParams.token.maxOutputInfo", {
        defaultValue: "单次请求允许的最大输出长度",
      }),
    },
    {
      key: "default_output_reserve_tokens",
      label: t("modelParams.token.outputReserve", {
        defaultValue: "输出预留Token数",
      }),
      hint: t("modelParams.token.outputReserveHint", {
        defaultValue: "建议：2000-10000",
      }),
      info: t("modelParams.token.outputReserveInfo", {
        defaultValue: "从上下文窗口中预留的输出空间",
      }),
    },
  ];

  const inheritedNumber = (key: string): number => {
    const raw = inheritedDefaults[key];
    return typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
  };

  return (
    <ParamDialog
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
        <ParamField label={t("modelParams.thinking", { defaultValue: "深度思考" })} info size="md">
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

      {/* Token capacity grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {tokenFields.map((field) => (
          <ParamField
            key={field.key}
            label={field.label}
            icon={
              <Tooltip title={field.info}>
                <QuestionCircleOutlined
                  style={{ color: "#8C8C8C", fontSize: 12 }}
                />
              </Tooltip>
            }
          >
            <ParamInput
              type="number"
              inputSize="sm"
              value={numberText(value[field.key])}
              placeholder={
                inheritedNumber(field.key)
                  ? String(inheritedNumber(field.key))
                  : undefined
              }
              onChange={(e) => {
                const raw = e.target.value;
                setNumberField(
                  field.key,
                  raw === "" ? undefined : Number(raw)
                );
              }}
            />
            <span className="flex items-center gap-1 text-[11px] leading-4 text-[#8C8C8C]">
              <InfoCircleOutlined style={{ color: "#1677FF" }} />
              {field.hint}
            </span>
          </ParamField>
        ))}
      </div>

      {/* Temperature slider */}
      <ParamField
        label={t("modelParams.temperature", { defaultValue: "输出内容温度" })}
        icon={
          <QuestionCircleOutlined style={{ color: "#8C8C8C", fontSize: 12 }} />
        }
      >
        <SliderStepper
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
          <QuestionCircleOutlined style={{ color: "#8C8C8C", fontSize: 12 }} />
        }
      >
        <SliderStepper
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
            <span className="text-[11px] leading-4 text-[#999]">
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
                k !== "" &&
                customEntries.filter(([ek]) => ek === k).length > 1;
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
                          (i === idx
                            ? [e.target.value, entry[1]]
                            : entry) as [string, string]
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
                          (i === idx
                            ? [entry[0], e.target.value]
                            : entry) as [string, string]
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