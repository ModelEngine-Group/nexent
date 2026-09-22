"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import { Loader2, ChevronDown, ChevronRight, Eye } from "lucide-react";

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
import { cn } from "@/lib/utils";

import { MODEL_TYPES } from "@/const/modelConfig";
import { modelService, ModelError } from "@/services/modelService";
import {
  ModelOption,
  ModelType,
  InferenceFieldSpecsByType,
} from "@/types/modelConfig";
import log from "@/lib/logger";

import {
  ModelAdvancedSettings,
  ModelAdvancedSettingsValue,
  buildInferenceParamsPayload,
  advancedSettingsValueFromRecord,
} from "./ModelAdvancedSettings";
import { useInferenceFieldSpecs } from "@/hooks/model/useInferenceFieldSpecs";

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
  const { specs: inferenceSpecs } = useInferenceFieldSpecs({ enabled: true });

  const [displayName, setDisplayName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [advanced, setAdvanced] = useState<ModelAdvancedSettingsValue>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);

  // Re-initialize whenever a different model opens (key in the parent forces
  // remount, but this effect also handles the initial open).
  useEffect(() => {
    if (!model) return;
    setDisplayName(model.displayName || model.name);
    setApiKey(model.apiKey || "");
    setBaseUrl(model.apiUrl || "");
    setAdvanced(
      advancedSettingsValueFromRecord(
        {
          temperature: model.temperature,
          top_p: model.topP,
          extra_params: model.extraParams,
        },
        { [model.type]: [] },
        model.type
      )
    );
  }, [model]);

  if (!model) return null;

  const canSubmit = displayName.trim().length > 0 && baseUrl.trim().length > 0;

  async function handleSave() {
    if (!canSubmit || saving || !model) return;
    setSaving(true);
    try {
      const params: Record<string, any> = {
        currentDisplayName: model.displayName,
        displayName: displayName.trim(),
        url: baseUrl.trim(),
        modelFactory: model.source || "OpenAI-API-Compatible",
        ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
        ...buildInferenceParamsPayload(advanced),
      };
      // Capacity fields from the model record (only re-send if the user
      // changed them via advanced settings).
      if (advanced.context_window_tokens != null)
        params.contextWindowTokens = advanced.context_window_tokens;
      if (advanced.max_input_tokens != null)
        params.maxInputTokens = advanced.max_input_tokens;
      if (advanced.max_output_tokens != null)
        params.maxOutputTokens = advanced.max_output_tokens;
      if (advanced.default_output_reserve_tokens != null)
        params.defaultOutputReserveTokens =
          advanced.default_output_reserve_tokens;

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
              <Badge
                variant="secondary"
                className={cn("border-0 text-xs", TYPE_BADGE_CLASS[model.type])}
              >
                {t(
                  `model.type.${TYPE_LABEL_KEY_MAP[model.type] ?? model.type}`,
                  { defaultValue: model.type }
                )}
              </Badge>
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
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="留空保持原有 Key"
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
                onChange={(e) => setBaseUrl(e.target.value)}
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
                <ModelAdvancedSettings
                  modelType={model.type}
                  specs={inferenceSpecs}
                  value={advanced}
                  onChange={setAdvanced}
                  mode="override"
                />
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t px-6 py-4">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel", { defaultValue: "取消" })}
          </Button>
          <Button disabled={!canSubmit || saving} onClick={handleSave}>
            {saving && <Loader2 className="size-4 animate-spin" />}
            {t("common.save", { defaultValue: "保存" })}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
