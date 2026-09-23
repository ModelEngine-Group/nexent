"use client";

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

import {
  ModelAdvancedSettingsValue,
  clampReasoningBudget,
  resolveReasoningDefault,
  resolveReasoningControls,
} from "./ModelAdvancedSettings";
import type { ReasoningCapability, ReasoningEffort } from "@/types/modelConfig";

/**
 * v2.6.1 redesign (v0 design): the shared advanced-config section — capacity
 * fields, numeric inference params (temperature / top_p), the deep-thinking
 * toggle with reasoning effort / budget controls, and custom key/value
 * params, rendered as the fixed v0-style grid.
 *
 * Used by the model edit dialog (高级配置) and the add-dialog advanced
 * settings (RowSettingsDialog) so the two stay visually identical. The value
 * is the same ModelAdvancedSettingsValue (snake_case spec keys) both dialogs
 * exchange with buildInferenceParamsPayload.
 */

/** v0-style advanced field: label + number input. */
function AdvField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-sm">{label}</Label>
      <Input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
    </div>
  );
}

export function ModelAdvancedConfig({
  value,
  onChange,
  modelType,
  reasoningCapability,
}: {
  value: ModelAdvancedSettingsValue;
  onChange: (next: ModelAdvancedSettingsValue) => void;
  /** Current model type — reasoning controls are LLM-only (develop parity). */
  modelType?: string;
  /** Catalog-driven capability metadata; without it only the toggle shows. */
  reasoningCapability?: ReasoningCapability;
}) {
  const { t } = useTranslation();

  // LLMs expose the thinking switch regardless of whether the catalog has
  // declared a provider-specific reasoning control. Materialize the default
  // (true) into the value — the payload builder treats an undefined
  // enable_thinking as "thinking off" and would silently drop any stored
  // reasoning_effort / budget (same seed ModelAdvancedSettings applies).
  useEffect(() => {
    if (modelType === "llm" && value.enable_thinking === undefined) {
      onChange({ ...value, enable_thinking: true });
    }
  }, [modelType, value, onChange]);

  const setNumberField = (key: string, raw: string) =>
    onChange({ ...value, [key]: raw === "" ? undefined : Number(raw) });

  const customs: [string, string][] = Array.isArray(value.__custom__)
    ? (value.__custom__ as [string, string][])
    : [];
  const setCustoms = (next: [string, string][]) =>
    onChange({ ...value, __custom__: next });

  // ---- Reasoning controls (shared resolution, see ModelAdvancedSettings) ----
  const reasoningControlVisible = modelType === "llm";
  const thinkingEnabled = value.enable_thinking !== false;
  const { budgetControl, effectiveEffortControl, reasoningLevels } =
    resolveReasoningControls(reasoningCapability);
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

  return (
    <>
      {/* Capacity + numeric inference params */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-4">
        <AdvField
          label={t("model.dialog.capacity.contextWindowTokens")}
          value={value.context_window_tokens?.toString() ?? ""}
          onChange={(v) => setNumberField("context_window_tokens", v)}
        />
        <AdvField
          label={t("model.dialog.capacity.maxInputTokens")}
          value={value.max_input_tokens?.toString() ?? ""}
          onChange={(v) => setNumberField("max_input_tokens", v)}
        />
        <AdvField
          label={t("model.dialog.capacity.maxOutputTokens")}
          value={value.max_output_tokens?.toString() ?? ""}
          onChange={(v) => setNumberField("max_output_tokens", v)}
        />
        <AdvField
          label={t("model.dialog.capacity.defaultOutputReserveTokens")}
          value={value.default_output_reserve_tokens?.toString() ?? ""}
          onChange={(v) => setNumberField("default_output_reserve_tokens", v)}
        />
        <AdvField
          label={t("modelConfig.advancedConfig.temperature", {
            defaultValue: "温度",
          })}
          value={value.temperature?.toString() ?? ""}
          onChange={(v) => setNumberField("temperature", v)}
        />
        <AdvField
          label={t("modelConfig.advancedConfig.topP", {
            defaultValue: "Top P",
          })}
          value={value.top_p?.toString() ?? ""}
          onChange={(v) => setNumberField("top_p", v)}
        />
      </div>

      {/* Deep thinking toggle + reasoning controls */}
      <div className="mt-4 rounded-lg border px-4 py-3">
        <div className="flex items-center justify-between">
          <div>
            <Label className="text-sm">
              {t("modelConfig.advancedConfig.enableThinking", {
                defaultValue: "深度思考",
              })}
            </Label>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("modelConfig.advancedConfig.enableThinkingHint", {
                defaultValue: "允许模型在回答前进行显式推理",
              })}
            </p>
          </div>
          <Switch
            checked={value.enable_thinking !== false}
            onCheckedChange={(checked) =>
              onChange({
                ...value,
                enable_thinking: checked,
                // Same semantics as ModelAdvancedSettings: toggling on seeds
                // the resolved default effort (preserves a valid stored one);
                // toggling off clears both so the payload builder drops them.
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
        </div>
        {reasoningControlVisible &&
          thinkingEnabled &&
          effectiveEffortControl?.type === "effort" && (
            <div className="mt-3 space-y-1.5">
              <Label className="text-sm">
                {t("model.advanced.reasoningEffort", {
                  defaultValue: "思考挡位",
                })}
              </Label>
              <Select
                value={
                  reasoningEffort && reasoningLevels.includes(reasoningEffort)
                    ? reasoningEffort
                    : (reasoningDefault ?? "auto")
                }
                onValueChange={(next) =>
                  onChange({
                    ...value,
                    reasoning_effort: next as ReasoningEffort,
                  })
                }
              >
                <SelectTrigger className="h-8 w-full bg-card text-sm font-normal">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {reasoningLevels.map((level) => (
                    <SelectItem key={level} value={level} className="text-xs">
                      {level}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        {reasoningControlVisible &&
          thinkingEnabled &&
          budgetControl?.type === "budget_tokens" && (
            <div className="mt-3 space-y-1.5">
              <Label className="text-sm">
                {t("model.advanced.reasoningBudget", {
                  defaultValue: "预算 tokens",
                })}
              </Label>
              <Input
                type="number"
                value={reasoningBudget?.toString() ?? ""}
                onChange={(e) => {
                  const raw = e.target.value;
                  if (raw === "") {
                    onChange({ ...value, reasoning_budget_tokens: undefined });
                    return;
                  }
                  onChange({
                    ...value,
                    reasoning_budget_tokens: clampReasoningBudget(
                      budgetControl,
                      Number(raw)
                    ),
                  });
                }}
                placeholder="auto"
                className="[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              <p className="text-xs text-muted-foreground">
                {`${budgetControl.min} ~ ${budgetControl.max}`}
              </p>
            </div>
          )}
      </div>

      {/* Custom params */}
      <div className="mt-4">
        <div className="flex items-center justify-between">
          <div>
            <Label className="text-sm">
              {t("model.advanced.customParams", {
                defaultValue: "自定义参数",
              })}
            </Label>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t("modelConfig.advancedConfig.customParamsHint", {
                defaultValue: "附加到请求体的额外参数",
              })}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setCustoms([...customs, ["", ""]])}
          >
            <Plus className="size-4" />
            {t("model.advanced.addCustomParam", {
              defaultValue: "添加参数",
            })}
          </Button>
        </div>
        <div className="mt-2 space-y-2">
          {customs.map(([k, v], idx) => (
            <div
              key={`custom-param-${idx}`}
              className="flex items-center gap-2"
            >
              <Input
                className="flex-1"
                placeholder={t("model.advanced.customKeyPlaceholder", {
                  defaultValue: "参数名",
                })}
                value={k}
                onChange={(e) => {
                  const next = [...customs];
                  next[idx] = [e.target.value, v];
                  setCustoms(next);
                }}
              />
              <Input
                className="flex-1"
                placeholder={t("model.advanced.customValuePlaceholder", {
                  defaultValue: "JSON 或字符串",
                })}
                value={v}
                onChange={(e) => {
                  const next = [...customs];
                  next[idx] = [k, e.target.value];
                  setCustoms(next);
                }}
              />
              <Button
                size="icon"
                variant="ghost"
                className="size-8 shrink-0 text-destructive hover:text-destructive"
                onClick={() => setCustoms(customs.filter((_, i) => i !== idx))}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
