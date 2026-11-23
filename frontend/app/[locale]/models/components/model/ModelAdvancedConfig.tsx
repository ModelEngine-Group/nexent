// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";

import { SliderStepper } from "@/components/common/SliderStepper";
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
  useReasoningFormEffects,
} from "./ModelAdvancedSettings";
import type {
  ModelType,
  ReasoningCapability,
  ReasoningEffort,
} from "@/types/modelConfig";
import { MODEL_TYPES } from "@/const/modelConfig";
import {
  DEFAULT_CHUNKING_BATCH_SIZE,
  DEFAULT_EXPECTED_CHUNK_SIZE,
  DEFAULT_MAXIMUM_CHUNK_SIZE,
  ModelChunkSizeSlider,
} from "./ModelChunkSizeSlider";
import {
  isEmbeddingModelType,
  isVoiceModelType,
  supportsCapacityGrid,
} from "./modelTypeUi";

/**
 * v2.6.1 redesign (v0 design): the shared advanced-config section, type-aware
 * like the old dialog's spec-driven form:
 *  - LLM family (llm / vlm / vlm2 / vlm3): capacity fields + temperature /
 *    top_p + deep-thinking controls + custom params.
 *  - Embedding family: multimodal switch + chunk-size slider + chunk batch.
 *  - rerank: max-tokens field.
 *  - stt / tts: provider select + App ID + Access Token (tts adds max tokens).
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
  onModelTypeChange,
}: {
  value: ModelAdvancedSettingsValue;
  onChange: (next: ModelAdvancedSettingsValue) => void;
  /** Current model type — reasoning controls are LLM-only (develop parity). */
  modelType?: string;
  /** Catalog-driven capability metadata; without it only the toggle shows. */
  reasoningCapability?: ReasoningCapability;
  /** Live type updates for the multimodal switch (embedding ↔
   *  multi_embedding), mirroring the old dialog where the switch edits the
   *  row's type immediately. When absent (e.g. the edit dialog locks the
   *  embedding pair's type) the switch is hidden. */
  onModelTypeChange?: (next: ModelType) => void;
}) {
  const { t } = useTranslation();

  // ---- Reasoning controls (shared resolution, see ModelAdvancedSettings) ----
  // develop #4009: capability-gated visibility plus the shared strip/seed
  // effects live in useReasoningFormEffects.
  const { budgetControl, effectiveEffortControl, reasoningLevels } =
    resolveReasoningControls(reasoningCapability);
  const reasoningControlVisible = useReasoningFormEffects(
    modelType ?? "",
    reasoningCapability,
    value,
    onChange
  );

  const setNumberField = (key: string, raw: string) =>
    onChange({ ...value, [key]: raw === "" ? undefined : Number(raw) });
  const setStringField = (key: string, raw: string) =>
    onChange({ ...value, [key]: raw === "" ? undefined : raw });

  const customs: [string, string][] = Array.isArray(value.__custom__)
    ? (value.__custom__ as [string, string][])
    : [];
  const setCustoms = (next: [string, string][]) =>
    onChange({ ...value, __custom__: next });

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
  const showCapacityGrid = supportsCapacityGrid(modelType);
  const isEmbedding = isEmbeddingModelType(modelType);
  const isVoice = isVoiceModelType(modelType);
  const multimodalOn = modelType === MODEL_TYPES.MULTI_EMBEDDING;
  const chunkRange: [number, number] = [
    typeof value.expected_chunk_size === "number"
      ? value.expected_chunk_size
      : DEFAULT_EXPECTED_CHUNK_SIZE,
    typeof value.maximum_chunk_size === "number"
      ? value.maximum_chunk_size
      : DEFAULT_MAXIMUM_CHUNK_SIZE,
  ];

  return (
    <>
      {/* Capacity + numeric inference params (LLM-family only — the other
          types render their dedicated fields below instead) */}
      {showCapacityGrid && (
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
          {(["temperature", "top_p"] as const).map((key) => {
            const label =
              key === "temperature"
                ? t("modelConfig.advancedConfig.temperature", {
                    defaultValue: "温度",
                  })
                : t("modelConfig.advancedConfig.topP", {
                    defaultValue: "Top P",
                  });
            return (
              <div key={key} className="min-w-0 space-y-1.5">
                <Label className="text-sm">{label}</Label>
                <SliderStepper
                  compact
                  label={label}
                  value={
                    typeof value[key] === "number" ? value[key] : undefined
                  }
                  fallback={1}
                  showFallbackValue={false}
                  min={0}
                  max={key === "temperature" ? 2 : 1}
                  step={0.1}
                  onChange={(next) => onChange({ ...value, [key]: next })}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* Embedding-family: multimodal switch + chunk-size slider + chunk
          batch (old-dialog parameter set) */}
      {isEmbedding && (
        <div className="space-y-4 rounded-lg border px-4 py-4">
          {onModelTypeChange && (
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm">
                  {t("model.dialog.label.multimodal", {
                    defaultValue: "多模态",
                  })}
                </Label>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {multimodalOn
                    ? t("model.dialog.hint.multimodalEnabled", {
                        defaultValue:
                          "多模态向量模型可处理图片与文本，将使用 multi_embedding 类型",
                      })
                    : t("model.dialog.hint.multimodalDisabled", {
                        defaultValue: "文本向量模型仅处理文本",
                      })}
                </p>
              </div>
              <Switch
                checked={multimodalOn}
                onCheckedChange={(checked) =>
                  onModelTypeChange(
                    checked
                      ? (MODEL_TYPES.MULTI_EMBEDDING as ModelType)
                      : (MODEL_TYPES.EMBEDDING as ModelType)
                  )
                }
              />
            </div>
          )}
          <div>
            <Label className="mb-2 block text-sm">
              {t("modelConfig.slider.chunkingSize", {
                defaultValue: "文档切片大小",
              })}
            </Label>
            <ModelChunkSizeSlider
              value={chunkRange}
              onChange={(range) =>
                onChange({
                  ...value,
                  expected_chunk_size: range[0],
                  maximum_chunk_size: range[1],
                })
              }
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">
              {t("modelConfig.input.chunkingBatchSize", {
                defaultValue: "单次请求切片量",
              })}
            </Label>
            <Input
              type="number"
              min="1"
              placeholder={String(DEFAULT_CHUNKING_BATCH_SIZE)}
              value={
                typeof value.chunk_batch === "number" ? value.chunk_batch : ""
              }
              onChange={(e) => setNumberField("chunk_batch", e.target.value)}
              className="[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
          </div>
        </div>
      )}

      {/* rerank: max tokens only (old spec field set) */}
      {modelType === MODEL_TYPES.RERANK && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-4">
          <AdvField
            label={t("model.dialog.label.maxTokens", {
              defaultValue: "最大Token数",
            })}
            value={value.max_tokens?.toString() ?? ""}
            onChange={(v) => setNumberField("max_tokens", v)}
          />
        </div>
      )}

      {/* stt / tts: provider select + Volcano credentials (old spec field
          set; tts adds max tokens) */}
      {isVoice && (
        <div className="space-y-4 rounded-lg border px-4 py-4">
          <div className="space-y-1.5">
            <Label className="text-sm">
              {t(
                modelType === MODEL_TYPES.STT
                  ? "model.dialog.label.sttProvider"
                  : "model.dialog.label.ttsProvider",
                { defaultValue: "服务商" }
              )}
            </Label>
            <Select
              value={String(value.model_factory ?? "dashscope")}
              onValueChange={(next) =>
                onChange({ ...value, model_factory: next })
              }
            >
              <SelectTrigger className="h-8 w-full bg-card text-sm font-normal">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="dashscope" className="text-xs">
                  dashscope
                </SelectItem>
                <SelectItem value="volcengine" className="text-xs">
                  volcengine
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">
              {t("model.dialog.label.modelAppid", { defaultValue: "App ID" })}
            </Label>
            <Input
              value={String(value.model_appid ?? "")}
              onChange={(e) => setStringField("model_appid", e.target.value)}
              placeholder={t("model.dialog.placeholder.modelAppid", {
                defaultValue: "输入火山引擎 App ID",
              })}
              autoComplete="off"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm">
              {t("model.dialog.label.accessToken", {
                defaultValue: "Access Token",
              })}
            </Label>
            <Input
              type="password"
              value={String(value.access_token ?? "")}
              onChange={(e) => setStringField("access_token", e.target.value)}
              placeholder={t("model.dialog.placeholder.accessToken", {
                defaultValue: "输入火山引擎 Access Token",
              })}
              autoComplete="new-password"
            />
          </div>
          {modelType === MODEL_TYPES.TTS && (
            <AdvField
              label={t("model.dialog.label.maxTokens", {
                defaultValue: "最大Token数",
              })}
              value={value.max_tokens?.toString() ?? ""}
              onChange={(v) => setNumberField("max_tokens", v)}
            />
          )}
        </div>
      )}

      {/* Deep thinking toggle + reasoning controls (capability-gated, #4009) */}
      {reasoningControlVisible && (
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
                      onChange({
                        ...value,
                        reasoning_budget_tokens: undefined,
                      });
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
      )}

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
