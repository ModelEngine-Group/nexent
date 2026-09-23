"use client";

import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import { ModelAdvancedSettingsValue } from "./ModelAdvancedSettings";

/**
 * v2.6.1 redesign (v0 design): the shared advanced-config section — capacity
 * fields, numeric inference params (temperature / top_p), the deep-thinking
 * toggle and custom key/value params, rendered as the fixed v0-style grid.
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
}: {
  value: ModelAdvancedSettingsValue;
  onChange: (next: ModelAdvancedSettingsValue) => void;
}) {
  const { t } = useTranslation();

  const setNumberField = (key: string, raw: string) =>
    onChange({ ...value, [key]: raw === "" ? undefined : Number(raw) });

  const customs: [string, string][] = Array.isArray(value.__custom__)
    ? (value.__custom__ as [string, string][])
    : [];
  const setCustoms = (next: [string, string][]) =>
    onChange({ ...value, __custom__: next });

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

      {/* Deep thinking toggle */}
      <div className="mt-4 flex items-center justify-between rounded-lg border px-4 py-3">
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
            onChange({ ...value, enable_thinking: checked })
          }
        />
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
