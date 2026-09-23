"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import { Loader2, ChevronDown, ChevronRight, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { MODEL_TYPES } from "@/const/modelConfig";
import { modelService, ModelError } from "@/services/modelService";
import { ModelOption, ModelType } from "@/types/modelConfig";
import log from "@/lib/logger";

import {
  ModelAdvancedSettingsValue,
  buildInferenceParamsPayload,
  formatCustomValueForEditing,
} from "./ModelAdvancedSettings";
import { ModelAdvancedConfig } from "./ModelAdvancedConfig";

/**
 * v2.6.1 redesign (v0 design): the per-model edit dialog.
 *
 * Replaces the old tab-based ModelAddDialogV2 edit flow with a single-page
 * form: basic info + connection at top, expandable advanced config (capacity
 * + inference params) below. Built on the project's shadcn/ui primitives.
 *
 * The connectivity check from the old dialog is intentionally dropped here —
 * models are checked from the library list (per-row button / one-click
 * verify). Edit is for configuration, not testing.
 */

const TYPE_LABEL_KEY_MAP: Record<string, string> = {
  llm: "llm",
  embedding: "embedding",
  multi_embedding: "multiEmbedding",
  vlm: "imageUnderstanding",
  vlm2: "imageGeneration",
  vlm3: "videoUnderstanding",
  vlm4: "audioUnderstanding",
  rerank: "rerank",
  stt: "stt",
  tts: "tts",
};

const TYPE_BADGE_CLASS: Record<string, string> = {
  [MODEL_TYPES.LLM]: "bg-blue-100 text-blue-700",
  [MODEL_TYPES.EMBEDDING]: "bg-indigo-100 text-indigo-700",
  [MODEL_TYPES.MULTI_EMBEDDING]: "bg-cyan-100 text-cyan-700",
  [MODEL_TYPES.RERANK]: "bg-purple-100 text-purple-700",
  [MODEL_TYPES.STT]: "bg-orange-100 text-orange-700",
  [MODEL_TYPES.TTS]: "bg-pink-100 text-pink-700",
  [MODEL_TYPES.VLM]: "bg-emerald-100 text-emerald-700",
  [MODEL_TYPES.VLM2]: "bg-emerald-100 text-emerald-700",
  [MODEL_TYPES.VLM3]: "bg-emerald-100 text-emerald-700",
  [MODEL_TYPES.VLM4]: "bg-emerald-100 text-emerald-700",
};

export interface ModelEditDialogProps {
  model: ModelOption | null;
  onClose: () => void;
  onSuccess: () => void;
}

export const ModelEditDialog = ({
  model,
  onClose,
  onSuccess,
}: ModelEditDialogProps) => {
  const { t } = useTranslation();
  const { message } = App.useApp();

  const [displayName, setDisplayName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [type, setType] = useState<ModelType>(MODEL_TYPES.LLM as ModelType);
  const [advanced, setAdvanced] = useState<ModelAdvancedSettingsValue>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  // In-dialog connectivity probe. "available" is only meaningful for the
  // current form values — any type/URL/key change resets it to "idle".
  const [probe, setProbe] = useState<
    "idle" | "checking" | "available" | "unavailable"
  >("idle");

  // Re-initialize whenever a different model opens (key in the parent forces
  // remount, but this effect also handles the initial open).
  useEffect(() => {
    if (!model) return;
    setDisplayName(model.displayName || model.name);
    setApiKey(model.apiKey || "");
    setBaseUrl(model.apiUrl || "");
    setType(model.type);
    setProbe("idle");
    const extra = (model.extraParams ?? {}) as Record<string, unknown>;
    const next: ModelAdvancedSettingsValue = {};
    if (model.temperature != null) next.temperature = model.temperature;
    if (model.topP != null) next.top_p = model.topP;
    if (model.contextWindowTokens != null)
      next.context_window_tokens = model.contextWindowTokens;
    if (model.maxInputTokens != null)
      next.max_input_tokens = model.maxInputTokens;
    if (model.maxOutputTokens != null)
      next.max_output_tokens = model.maxOutputTokens;
    if (model.defaultOutputReserveTokens != null)
      next.default_output_reserve_tokens = model.defaultOutputReserveTokens;
    if (extra.enable_thinking !== undefined)
      next.enable_thinking = extra.enable_thinking === true;
    // Reasoning effort / budget (develop's #3953) are managed by the spec-
    // driven dialog; carry them through so saving the v0 form does not
    // silently drop stored values from extra_params.
    if (typeof extra.reasoning_effort === "string")
      next.reasoning_effort = extra.reasoning_effort;
    if (
      typeof extra.reasoning_budget_tokens === "number" &&
      Number.isFinite(extra.reasoning_budget_tokens)
    )
      next.reasoning_budget_tokens = extra.reasoning_budget_tokens;
    const customRaw = extra.__custom__;
    if (
      customRaw &&
      typeof customRaw === "object" &&
      !Array.isArray(customRaw)
    ) {
      next.__custom__ = Object.entries(
        customRaw as Record<string, unknown>
      ).map(
        ([k, v]) => [k, formatCustomValueForEditing(v)] as [string, string]
      );
    }
    setAdvanced(next);
  }, [model]);

  const typeOptions = useMemo(
    () =>
      (Object.keys(TYPE_LABEL_KEY_MAP) as ModelType[]).map((v) => ({
        value: v,
        label: t(`model.type.${TYPE_LABEL_KEY_MAP[v]}`, {
          defaultValue: v,
        }),
      })),
    [t]
  );

  if (!model) return null;

  // Embedding / multi_embedding records share one display name and are
  // updated as a pair; the backend update path deliberately ignores
  // model_type there, so the field is not editable for those types.
  const typeLocked =
    model.type === MODEL_TYPES.EMBEDDING ||
    model.type === MODEL_TYPES.MULTI_EMBEDDING;

  const canSubmit = displayName.trim().length > 0 && baseUrl.trim().length > 0;

  async function handleCheck() {
    if (!model || probe === "checking") return;
    setProbe("checking");
    try {
      // Empty apiKey falls back to the stored key via probe_model_id. The
      // inference params (temperature / top_p / extra_params incl.
      // __custom__) ride along so an invalid custom param fails the probe
      // here instead of at runtime — same contract as the backend probe.
      const result = await modelService.verifyModelConfigConnectivity({
        modelName: model.name,
        modelType: type,
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim() || undefined,
        modelId: model.id,
        modelFactory: model.source || "OpenAI-API-Compatible",
        ...buildInferenceParamsPayload(advanced),
      });
      setProbe(result.connectivity ? "available" : "unavailable");
    } catch {
      setProbe("unavailable");
    }
  }

  async function handleSave() {
    if (!canSubmit || saving || !model) return;
    setSaving(true);
    try {
      const typeChanged = type !== model.type;
      const params: Record<string, any> = {
        currentDisplayName: model.displayName,
        displayName: displayName.trim(),
        url: baseUrl.trim(),
        modelFactory: model.source || "OpenAI-API-Compatible",
        ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
        ...buildInferenceParamsPayload(advanced),
      };
      if (typeChanged) {
        params.type = type;
      }
      if (probe === "available") {
        // The in-dialog probe passed with the exact values being saved.
        params.connectStatus = "available";
      } else if (typeChanged) {
        // No passing probe for the new type; reset so the row must be
        // re-checked before it counts as available.
        params.connectStatus = "not_detected";
      }
      // Capacity fields: only re-send what the advanced section carries
      // (pre-filled from the record, so unchanged values round-trip). The
      // camelCase mapping is required because buildCapacityRequestBody in
      // modelService only reads camelCase keys.
      if (advanced.context_window_tokens != null)
        params.contextWindowTokens = advanced.context_window_tokens;
      if (advanced.max_input_tokens != null)
        params.maxInputTokens = advanced.max_input_tokens;
      if (advanced.max_output_tokens != null) {
        params.maxOutputTokens = advanced.max_output_tokens;
        // Mirror into the deprecated max_tokens column so legacy readers
        // stay consistent (same mirroring as buildCapacityPayload).
        params.maxTokens = advanced.max_output_tokens;
      }
      if (advanced.default_output_reserve_tokens != null)
        params.defaultOutputReserveTokens =
          advanced.default_output_reserve_tokens;
      if (
        advanced.context_window_tokens != null ||
        advanced.max_input_tokens != null ||
        advanced.max_output_tokens != null ||
        advanced.default_output_reserve_tokens != null
      ) {
        params.capacitySource = "operator";
      }

      await modelService.updateSingleModel(params as any);
      onSuccess();
      onClose();
    } catch (error: any) {
      log.error("update model failed", error);
      message.error(
        error instanceof ModelError
          ? error.message
          : t("modelConfig.editDialog.updateFailed", {
              defaultValue: "更新模型失败",
            })
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[85vh] w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="text-base">
            {t("modelConfig.editDialog.title", { defaultValue: "编辑模型" })}
          </DialogTitle>
          <DialogDescription>
            {t("modelConfig.editDialog.description", {
              defaultValue:
                "修改模型基本信息与连接凭证，或展开高级配置调整推理参数。",
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="grid grid-cols-2 gap-x-4 gap-y-5">
            <div className="space-y-2">
              <Label>
                {t("modelConfig.editDialog.displayName", {
                  defaultValue: "展示名称",
                })}
              </Label>
              <Input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>
                {t("modelConfig.editDialog.modelName", {
                  defaultValue: "模型名称",
                })}
              </Label>
              <Input value={model.name} disabled className="font-mono" />
            </div>
            <div className="flex items-center gap-2">
              <Select
                value={type}
                onValueChange={(v) => {
                  setType(v as ModelType);
                  setProbe("idle");
                }}
                disabled={typeLocked}
              >
                <SelectTrigger
                  className={cn(
                    "h-6 w-fit gap-1 border-0 px-2 text-xs font-normal shadow-none focus:ring-0",
                    TYPE_BADGE_CLASS[type]
                  )}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {typeOptions.map((opt) => (
                    <SelectItem
                      key={opt.value}
                      value={opt.value}
                      className="text-xs"
                    >
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Badge variant="secondary" className="border-0 text-xs">
                {model.source}
              </Badge>
            </div>
            <div />
            <div className="space-y-2">
              <Label>
                {t("modelConfig.editDialog.apiKey", {
                  defaultValue: "API Key",
                })}
              </Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setProbe("idle");
                }}
                placeholder={t("modelConfig.editDialog.apiKeyKeepHint", {
                  defaultValue: "留空保持原有 Key",
                })}
              />
            </div>
            <div className="space-y-2">
              <Label>
                {t("modelConfig.editDialog.baseUrl", {
                  defaultValue: "Base URL",
                })}
              </Label>
              <Input
                value={baseUrl}
                onChange={(e) => {
                  setBaseUrl(e.target.value);
                  setProbe("idle");
                }}
              />
            </div>
          </div>

          {/* Advanced config (expandable) */}
          <div className="mt-5">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex w-full items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              {showAdvanced ? (
                <ChevronDown className="size-4" />
              ) : (
                <ChevronRight className="size-4" />
              )}
              {t("modelConfig.editDialog.advancedConfig", {
                defaultValue: "高级配置",
              })}
            </button>
            {showAdvanced && (
              <div className="mt-4 border-t pt-4">
                <ModelAdvancedConfig
                  value={advanced}
                  onChange={(next) => {
                    setAdvanced(next);
                    // Inference params ride along in the probe, so changing
                    // them invalidates a previous probe result.
                    setProbe("idle");
                  }}
                />
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between border-t px-6 py-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <Button
              variant="outline"
              onClick={handleCheck}
              disabled={probe === "checking" || saving}
            >
              {probe === "checking" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ShieldCheck className="size-4" />
              )}
              {t("modelConfig.editDialog.checkConnectivity", {
                defaultValue: "检测连通性",
              })}
            </Button>
            {probe === "available" && (
              <span className="flex items-center gap-1.5 text-xs text-emerald-600">
                <span className="size-2 rounded-full bg-emerald-500" />
                {t("model.status.available", { defaultValue: "可用" })}
              </span>
            )}
            {probe === "unavailable" && (
              <span className="flex items-center gap-1.5 text-xs text-red-500">
                <span className="size-2 rounded-full bg-red-500" />
                {t("model.status.unavailable", { defaultValue: "不可用" })}
              </span>
            )}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" onClick={onClose}>
              {t("common.cancel", { defaultValue: "取消" })}
            </Button>
            <Button disabled={!canSubmit || saving} onClick={handleSave}>
              {saving && <Loader2 className="size-4 animate-spin" />}
              {t("common.save", { defaultValue: "保存" })}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
