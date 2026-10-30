// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ModelHttpConnectionSettings } from "@/components/model/ModelHttpConnectionSettings";
import { ModelOutletForm } from "@/components/model/ModelOutletForm";
import { App } from "antd";
import {
  Plus,
  Layers,
  Loader2,
  RefreshCw,
  Check,
  PackageOpen,
  Search,
  Settings2,
  ShieldCheck,
} from "lucide-react";

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
import { ApiError } from "@/services/api";
import { modelService, ModelError } from "@/services/modelService";
import { ModelType, ReasoningCapability } from "@/types/modelConfig";
import log from "@/lib/logger";

import {
  ModelAdvancedSettingsValue,
  buildInferenceParamsPayload,
  buildVoiceCredentialParams,
} from "./ModelAdvancedSettings";
import { ModelAdvancedConfig } from "./ModelAdvancedConfig";
import { ModelOutletAddForm } from "./ModelOutletAddForm";
import {
  createModelOutlet,
  previewModelProfile,
  validateModelOutlet,
  listModelProfiles,
} from "@/services/modelProfileService";
import { useQuery } from "@tanstack/react-query";
import { suggestModelProfile } from "./profileSuggestion";
import { outletSamplingValues } from "@/lib/modelSamplingParameters";
import {
  modelCheckFailure,
  type ModelCheckIssue,
} from "@/lib/modelCheckIssues";
import { ModelCheckSummary } from "@/components/model/ModelCheckSummary";
import type { ModelProfileDraftRequest } from "@/types/modelProfile";
import {
  DEFAULT_CHUNKING_BATCH_SIZE,
  DEFAULT_EXPECTED_CHUNK_SIZE,
  DEFAULT_MAXIMUM_CHUNK_SIZE,
} from "./ModelChunkSizeSlider";
import {
  isEmbeddingModelType,
  supportsMaxTokensField,
  TYPE_BADGE_CLASS,
  useTypeOptions,
} from "./modelTypeUi";

/** LLM outlets use profile-driven forms; other model types retain their existing setup. */

const CUSTOM_PROVIDER_KEY = "__custom__";

export interface ModelAddDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (newModel?: { name: string; type: ModelType }) => void;
  tenantId?: string;
  initialTab?: "single" | "batch";
}

export const ModelAddDialog = ({
  isOpen,
  onClose,
  onSuccess,
  tenantId,
  initialTab = "single",
}: ModelAddDialogProps) => {
  const { t } = useTranslation();
  const [wide, setWide] = useState(true);
  const [tab, setTab] = useState<"single" | "batch">(initialTab);

  // Reset the tab whenever the dialog reopens (the sync-ModelEngine button
  // opens it on the batch tab).
  useEffect(() => {
    if (isOpen) setTab(initialTab);
  }, [isOpen, initialTab]);

  return (
    <Dialog open={isOpen} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        className={cn(
          "flex max-h-[90vh] w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0",
          wide || tab === "batch" ? "sm:max-w-5xl" : "sm:max-w-xl"
        )}
      >
        <DialogHeader className="shrink-0 flex-row flex-wrap items-center justify-between gap-4 border-b px-6 py-4 pr-14">
          <div className="space-y-1 text-left">
            <DialogTitle className="text-base">
              {t("modelConfig.addDialog.title", { defaultValue: "添加模型" })}
            </DialogTitle>
            <DialogDescription className="text-xs">
              {t("modelConfig.addDialog.description", {
                defaultValue:
                  "手动添加单个模型，或从服务商一键批量导入可用模型。",
              })}
            </DialogDescription>
          </div>
          <div
            className="flex shrink-0 gap-1 rounded-md bg-muted p-1"
            role="group"
            aria-label={t("modelConfig.addDialog.title")}
          >
            <TabButton
              active={tab === "single"}
              onClick={() => setTab("single")}
              icon={<Plus className="size-4" />}
              title={t("modelConfig.addDialog.singleTab")}
            />
            <TabButton
              active={tab === "batch"}
              onClick={() => setTab("batch")}
              icon={<Layers className="size-4" />}
              title={t("modelConfig.addDialog.batchTab")}
            />
          </div>
        </DialogHeader>

        {tab === "single" ? (
          <SingleAddForm
            onLayoutChange={setWide}
            onDone={onClose}
            onSuccess={onSuccess}
            tenantId={tenantId}
          />
        ) : (
          <BatchAddForm
            onDone={onClose}
            onSuccess={onSuccess}
            tenantId={tenantId}
          />
        )}
      </DialogContent>
    </Dialog>
  );
};

function TabButton({
  active,
  onClick,
  icon,
  title,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded px-3 py-1.5 text-xs transition-colors",
        active
          ? "bg-background text-primary shadow-sm"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      {icon}
      {title}
    </button>
  );
}

/* ------------------------------ provider presets ------------------------------ */

interface ProviderPreset {
  key: string;
  label: string;
  baseUrl: string;
}

function useProviderPresets(open: boolean) {
  const [presets, setPresets] = useState<ProviderPreset[]>([]);

  useEffect(() => {
    if (!open) return;
    modelService
      .getFullCatalog()
      .then(({ catalog }) => {
        const list: ProviderPreset[] = (catalog?.providers || [])
          .map((p: any) => ({
            key: p.models?.[0]?.provider_key,
            label: p.provider_info?.display_name,
            baseUrl: p.provider_info?.base_url || "",
          }))
          .filter((p) => !!p.key && !!p.label);
        setPresets(list);
      })
      .catch(() => setPresets([]));
  }, [open]);

  return presets;
}

/** Shared provider dropdown: catalog presets + the 自定义 option. */
function ProviderSelect({
  presets,
  value,
  onChange,
}: {
  presets: ProviderPreset[];
  value: string;
  onChange: (next: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-full data-[size=default]:h-10">
        <SelectValue
          placeholder={t("modelConfig.addDialog.providerPlaceholder", {
            defaultValue: "选择服务商",
          })}
        />
      </SelectTrigger>
      <SelectContent>
        {presets.map((p) => (
          <SelectItem key={p.key} value={p.key}>
            {p.label}
          </SelectItem>
        ))}
        <SelectItem value={CUSTOM_PROVIDER_KEY}>
          {t("modelConfig.addDialog.customProvider", {
            defaultValue: "自定义",
          })}
        </SelectItem>
      </SelectContent>
    </Select>
  );
}

/* ------------------------------ shared helpers ------------------------------ */

async function createModel(
  tenantId: string | undefined,
  params: Record<string, any>
) {
  if (tenantId) {
    return modelService.createManageTenantModel({
      tenantId,
      ...params,
    } as any);
  }
  return modelService.addCustomModel(params as any);
}

// Resolved outlets use a stable duplicate-name business code. Legacy create
// endpoints retain their name-conflict text. A bare 409 may be a stale revision
// or another conflict, so never classify it as a duplicate by status alone.
const isDisplayNameConflictError = (error: unknown): boolean =>
  (error instanceof ApiError && error.code === "MODEL_DISPLAY_NAME_CONFLICT") ||
  (error instanceof ModelError && /is already in use/i.test(error.message));

/**
 * Always send chunk params for embedding-family rows (old-dialog parity):
 * saved gear values win, otherwise the same defaults the backend would
 * apply become explicit.
 */
function applyEmbeddingChunkParams(
  params: Record<string, unknown>,
  settings?: ModelAdvancedSettingsValue
) {
  if (!isEmbeddingModelType(params.type as string | undefined)) return;
  const expected =
    typeof settings?.expected_chunk_size === "number"
      ? settings.expected_chunk_size
      : DEFAULT_EXPECTED_CHUNK_SIZE;
  const maximum =
    typeof settings?.maximum_chunk_size === "number"
      ? settings.maximum_chunk_size
      : DEFAULT_MAXIMUM_CHUNK_SIZE;
  const batch =
    typeof settings?.chunk_batch === "number" && settings.chunk_batch > 0
      ? settings.chunk_batch
      : DEFAULT_CHUNKING_BATCH_SIZE;
  params.expectedChunkSize = expected;
  params.maximumChunkSize = maximum;
  params.chunkingBatchSize = batch;
}

/**
 * Merge an advanced-settings value (snake_case spec keys) into the create
 * params. buildInferenceParamsPayload emits snake_case top-level keys, but
 * buildCapacityRequestBody in modelService only reads camelCase — without
 * this explicit mapping the capacity fields are silently dropped on create
 * (mirrors the inline mapping ModelAddDialogV2 does for the same contract).
 */
function applyAdvancedSettingsToParams(
  params: Record<string, any>,
  settings: ModelAdvancedSettingsValue,
  reasoningCapability?: ReasoningCapability
) {
  const payload = buildInferenceParamsPayload(settings, reasoningCapability);
  Object.assign(params, payload);
  const hasCapacity =
    payload.context_window_tokens != null ||
    payload.max_input_tokens != null ||
    payload.max_output_tokens != null ||
    payload.default_output_reserve_tokens != null;
  if (payload.context_window_tokens != null)
    params.contextWindowTokens = payload.context_window_tokens;
  if (payload.max_input_tokens != null)
    params.maxInputTokens = payload.max_input_tokens;
  if (payload.max_output_tokens != null) {
    params.maxOutputTokens = payload.max_output_tokens;
    // Mirror max_output_tokens into the deprecated max_tokens column so
    // legacy readers stay consistent (same mirroring as buildCapacityPayload).
    params.maxTokens = payload.max_output_tokens;
  }
  if (payload.default_output_reserve_tokens != null)
    params.defaultOutputReserveTokens = payload.default_output_reserve_tokens;
  if (payload.tokenizer_family != null)
    params.tokenizerFamily = payload.tokenizer_family;
  if (hasCapacity) params.capacitySource = "operator";
  // Type-specific spec fields, gated by the row's current type (stale gear
  // values must survive a type change silently, not pollute the new type).
  // max_tokens only exists for rerank/tts; voice credentials only for stt/tts.
  if (
    supportsMaxTokensField(params.type as string | undefined) &&
    payload.max_tokens != null
  ) {
    params.maxTokens = payload.max_tokens;
  }
  Object.assign(
    params,
    buildVoiceCredentialParams(params.type as string | undefined, payload)
  );
}

/* ------------------------------ 单个添加 ------------------------------ */

/** Map a suggestCapacity response into advanced-settings form values
 *  (snake_case keys, same as the batch tab's per-row suggestions). */
function capacitySuggestionToSettings(
  sug: any
): ModelAdvancedSettingsValue | undefined {
  const val: ModelAdvancedSettingsValue = {};
  if (sug?.contextWindowTokens != null)
    val.context_window_tokens = sug.contextWindowTokens;
  if (sug?.maxInputTokens != null) val.max_input_tokens = sug.maxInputTokens;
  if (sug?.maxOutputTokens != null) val.max_output_tokens = sug.maxOutputTokens;
  if (sug?.defaultOutputReserveTokens != null)
    val.default_output_reserve_tokens = sug.defaultOutputReserveTokens;
  return Object.keys(val).length > 0 ? val : undefined;
}

function SingleAddForm({
  onLayoutChange,
  onDone,
  onSuccess,
  tenantId,
}: {
  onDone: () => void;
  onSuccess: (newModel?: { name: string; type: ModelType }) => void;
  tenantId?: string;
  onLayoutChange: (wide: boolean) => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const typeOptions = useTypeOptions();

  const [provider, setProvider] = useState<string>(CUSTOM_PROVIDER_KEY);
  const [type, setType] = useState<ModelType>(MODEL_TYPES.LLM as ModelType);
  const useOutletForm = type === MODEL_TYPES.LLM && !tenantId;
  useEffect(
    () => onLayoutChange(useOutletForm),
    [useOutletForm, onLayoutChange]
  );
  const presets = useProviderPresets(!useOutletForm);
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [override, setOverride] = useState<RowOverride | undefined>(undefined);
  const [showSettings, setShowSettings] = useState(false);
  // Auto-detected from the catalog (same lookup the batch tab runs per
  // fetched row): capacity prefill + reasoning capability.
  const [suggestion, setSuggestion] = useState<RowOverride | undefined>(
    undefined
  );
  const [capability, setCapability] = useState<ReasoningCapability | undefined>(
    undefined
  );
  // Optional connectivity probe; valid configurations can be saved unchecked.
  const [probe, setProbe] = useState<
    "idle" | "checking" | "available" | "unavailable"
  >("idle");

  // Auto-detect capacity + reasoning capability whenever name and URL are
  // filled (debounced); user-saved overrides (the gear) win over suggestions.
  useEffect(() => {
    if (useOutletForm || !name.trim() || !baseUrl.trim()) {
      setSuggestion(undefined);
      setCapability(undefined);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const s = await modelService.suggestCapacity({
          modelName: name.trim(),
          baseUrl: baseUrl.trim(),
          providerHint: provider,
          modelType: type,
        });
        if (cancelled) return;
        setCapability(s?.reasoningCapability);
        const settings = capacitySuggestionToSettings(s?.suggestions);
        setSuggestion(settings ? { settings } : undefined);
      } catch {
        if (!cancelled) {
          setSuggestion(undefined);
          setCapability(undefined);
        }
      }
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [name, baseUrl, provider, type, useOutletForm]);

  function changeProvider(next: string) {
    setProvider(next);
    const preset = presets.find((p) => p.key === next);
    if (preset?.baseUrl) {
      setBaseUrl(preset.baseUrl);
    }
  }

  const isCustom = provider === CUSTOM_PROVIDER_KEY;
  const canSubmit =
    name.trim().length > 0 && (!isCustom || baseUrl.trim().length > 0);
  // User-saved gear overrides win; otherwise the catalog suggestion applies.
  const effective = override ?? suggestion;
  const suggestionSettings = suggestion?.settings ?? {};
  // Compact reasoning summary for the auto-detect hint line.
  const thinkingLabel = t("modelConfig.advancedConfig.enableThinking", {
    defaultValue: "深度思考",
  });
  let reasoningBit: string | null = null;
  if (capability?.status === "supported") {
    if (capability.control === "budget_tokens") {
      reasoningBit = `${thinkingLabel}（${t("model.advanced.reasoningBudget", {
        defaultValue: "预算 tokens",
      })}）`;
    } else if (
      capability.control === "effort" &&
      capability.levels.length > 0
    ) {
      reasoningBit = `${thinkingLabel}（${t("model.advanced.reasoningEffort", {
        defaultValue: "思考挡位",
      })}: ${capability.levels.join(" / ")}）`;
    } else {
      reasoningBit = thinkingLabel;
    }
  }

  async function handleCheck() {
    if (probe === "checking" || !name.trim() || !baseUrl.trim()) return;
    setProbe("checking");
    try {
      const result = await modelService.verifyModelConfigConnectivity({
        modelName: name.trim(),
        modelType: type,
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim(),
        modelFactory: isCustom ? "OpenAI-API-Compatible" : provider,
        ...(effective?.settings
          ? buildInferenceParamsPayload(effective.settings)
          : {}),
        // voice 凭证随探测透传，按当前类型门控防止类型切换后过期值泄漏
        ...buildVoiceCredentialParams(type, effective?.settings),
      });
      setProbe(result.connectivity ? "available" : "unavailable");
    } catch {
      setProbe("unavailable");
    }
  }

  async function submit() {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try {
      const params: Record<string, any> = {
        name: name.trim(),
        type,
        url: baseUrl.trim(),
        apiKey: apiKey.trim(),
        displayName: displayName.trim() || name.trim(),
        // Embedding-family rows use max_tokens as the vector-dimension
        // placeholder (V2 parity); other types keep the generic default.
        maxTokens: isEmbeddingModelType(type) ? 1024 : 4096,
        modelFactory: isCustom ? "OpenAI-API-Compatible" : provider,
        connectStatus:
          probe === "available"
            ? "available"
            : probe === "unavailable"
              ? "unavailable"
              : "not_detected",
      };
      if (effective?.settings) {
        applyAdvancedSettingsToParams(params, effective.settings, capability);
      }
      // Embedding rows always carry chunk params (gear values or defaults).
      applyEmbeddingChunkParams(params, effective?.settings);
      await createModel(tenantId, params);
      onSuccess({ name: name.trim(), type });
      onDone();
    } catch (error: any) {
      log.error("add model failed", error);
      message.error(
        error instanceof ModelError
          ? error.message
          : t("modelConfig.addDialog.addFailed", {
              defaultValue: "添加模型失败",
            })
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (useOutletForm)
    return (
      <ModelOutletAddForm
        typeControl={
          <Select
            value={type}
            disabled={submitting}
            onValueChange={(value) => setType(value as ModelType)}
          >
            <SelectTrigger
              id="outlet-model-type"
              size="sm"
              className="!h-7 w-full rounded-[4px] gap-4"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {typeOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
        onDone={onDone}
        onSuccess={onSuccess}
        onPendingChange={setSubmitting}
      />
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="grid grid-cols-2 gap-x-4 gap-y-5">
          <div className="space-y-2">
            <Label>
              {t("modelConfig.addDialog.provider", { defaultValue: "服务商" })}
            </Label>
            <ProviderSelect
              presets={presets}
              value={provider}
              onChange={changeProvider}
            />
          </div>
          <div className="space-y-2">
            <Label>
              {t("modelConfig.addDialog.modelType", {
                defaultValue: "模型类型",
              })}
            </Label>
            <Select
              value={type}
              onValueChange={(v) => {
                setType(v as ModelType);
                setProbe("idle");
              }}
            >
              <SelectTrigger className="w-full data-[size=default]:h-10">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {typeOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="col-span-2 space-y-2">
            <Label>
              {t("modelConfig.addDialog.modelName", {
                defaultValue: "模型名称",
              })}
              <span className="ml-0.5 text-destructive">*</span>
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {t("modelConfig.addDialog.modelNameHint", {
                  defaultValue: "服务商提供的模型 ID",
                })}
              </span>
            </Label>
            <Input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setProbe("idle");
                // The name is the model identity: manual gear settings saved
                // for a previous name must not silently apply to the new
                // model. Catalog suggestions re-run automatically.
                setOverride(undefined);
              }}
              placeholder="Qwen/Qwen3-8B"
              autoComplete="off"
            />
          </div>
          <div className="col-span-2 space-y-2">
            <Label>
              {t("modelConfig.addDialog.displayName", {
                defaultValue: "展示名称",
              })}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {t("modelConfig.addDialog.displayNameHint", {
                  defaultValue: "选填，便于识别的别名",
                })}
              </span>
            </Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={
                name.trim()
                  ? `${t("modelConfig.addDialog.displayNameDefault", {
                      defaultValue: "默认使用",
                    })}「${name.trim()}」`
                  : t("modelConfig.addDialog.displayNamePlaceholder", {
                      defaultValue: "便于识别的别名",
                    })
              }
              autoComplete="off"
            />
          </div>
          <div className="col-span-2 space-y-2">
            <Label>
              {t("modelConfig.addDialog.baseUrl", { defaultValue: "Base URL" })}
            </Label>
            <Input
              value={baseUrl}
              onChange={(e) => {
                setBaseUrl(e.target.value);
                setProbe("idle");
              }}
              placeholder="https://api.example.com/v1"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              {isCustom
                ? t("modelConfig.addDialog.baseUrlCustomHint", {
                    defaultValue: "OpenAI 兼容接口地址",
                  })
                : t("modelConfig.addDialog.baseUrlPresetHint", {
                    defaultValue: "已按服务商预填，可修改（如私有化部署地址）",
                  })}
            </p>
          </div>
          <div className="col-span-2 space-y-2">
            <Label>
              {t("modelConfig.addDialog.apiKey", { defaultValue: "API Key" })}
            </Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                setProbe("idle");
              }}
              placeholder="sk-..."
              autoComplete="new-password"
            />
          </div>
        </div>

        {/* Auto-detected capacity / reasoning summary (catalog lookup) */}
        {(suggestion?.settings || capability?.status === "supported") && (
          <div className="mt-4 rounded-lg border bg-secondary/30 px-4 py-3 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">
              {t("modelConfig.addDialog.detected", {
                defaultValue: "已自动识别",
              })}
            </span>
            {suggestionSettings.context_window_tokens != null && (
              <span className="ml-2">
                {t("model.dialog.capacity.contextWindowTokens")}{" "}
                {Number(suggestionSettings.context_window_tokens)}
              </span>
            )}
            {suggestionSettings.max_input_tokens != null && (
              <span className="ml-2">
                {t("model.dialog.capacity.maxInputTokens")}{" "}
                {Number(suggestionSettings.max_input_tokens)}
              </span>
            )}
            {suggestionSettings.max_output_tokens != null && (
              <span className="ml-2">
                {t("model.dialog.capacity.maxOutputTokens")}{" "}
                {Number(suggestionSettings.max_output_tokens)}
              </span>
            )}
            {reasoningBit && <span className="ml-2">{reasoningBit}</span>}
            <span className="ml-2">
              {t("modelConfig.addDialog.detectedHint", {
                defaultValue: "可在高级设置中调整",
              })}
            </span>
          </div>
        )}
      </div>
      <div className="flex items-center justify-between border-t px-6 py-4">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setShowSettings(true)}
            className="gap-2"
          >
            <Settings2 className="size-4" />
            {t("modelConfig.addDialog.advancedSettings", {
              defaultValue: "高级设置",
            })}
            {effective?.settings && (
              <span className="size-1.5 rounded-full bg-primary" />
            )}
          </Button>
          <Button
            variant="outline"
            onClick={handleCheck}
            disabled={
              probe === "checking" ||
              submitting ||
              !name.trim() ||
              !baseUrl.trim()
            }
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
        <div className="flex gap-2">
          <Button variant="outline" onClick={onDone}>
            {t("common.cancel", { defaultValue: "取消" })}
          </Button>
          <Button disabled={!canSubmit || submitting} onClick={submit}>
            {submitting && <Loader2 className="size-4 animate-spin" />}
            {t("modelConfig.addDialog.submit", { defaultValue: "添加模型" })}
          </Button>
        </div>
      </div>

      {/* Advanced settings (capacity + inference params; embedding rows get
          the chunk/multimodal panel instead) */}
      {showSettings && (
        <RowSettingsDialog
          key="single"
          row={{
            id: "single",
            model_name: name.trim() || "model",
            model_type: type,
          }}
          override={effective}
          reasoningCapability={capability}
          onModelTypeChange={(next) => {
            setType(next);
            setProbe("idle");
          }}
          onSave={(next) => {
            setOverride(next);
            setProbe("idle");
            setShowSettings(false);
          }}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}

/* ------------------------------ 批量添加 ------------------------------ */

interface FetchedRow {
  id: string;
  model_name: string;
  model_type: ModelType;
}

/** Per-row settings override — a single ModelAdvancedSettingsValue that
 *  includes both capacity and inference params (the component renders them
 *  all in override mode), plus an optional custom display name. */
interface RowOverride {
  outletDraft?: ModelProfileDraftRequest;
  displayName?: string;
  settings?: ModelAdvancedSettingsValue;
}

function BatchAddForm({
  onDone,
  onSuccess,
  tenantId,
}: {
  onDone: () => void;
  onSuccess: (newModel?: { name: string; type: ModelType }) => void;
  tenantId?: string;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const presets = useProviderPresets(true);
  const typeOptions = useTypeOptions();
  const models = useQuery({
    queryKey: ["atomic-model-profiles"],
    queryFn: () => listModelProfiles({ page_size: 100 }),
  });
  const [issues, setIssues] = useState<Record<string, ModelCheckIssue>>({});
  const generations = useRef<Record<string, number>>({});
  const checkReceipts = useRef<Record<string, string>>({});
  const discoveryGeneration = useRef(0);
  const [profileMatches, setProfileMatches] = useState<Record<string, boolean>>(
    {}
  );
  function invalidateChecks(id?: string) {
    if (!id) {
      discoveryGeneration.current++;
      setFetching(false);
    }
    const ids = id ? [id] : fetched.map((row) => row.id);
    ids.forEach((key) => {
      generations.current[key] = (generations.current[key] ?? 0) + 1;
      delete checkReceipts.current[key];
    });
    setRowCheck((previous) => {
      const next = { ...previous };
      ids.forEach((key) => delete next[key]);
      return next;
    });
    setIssues((previous) => {
      const next = { ...previous };
      ids.forEach((key) => delete next[key]);
      return next;
    });
  }

  const [provider, setProvider] = useState<string>(CUSTOM_PROVIDER_KEY);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [sslVerify, setSslVerify] = useState(true);
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);
  const [headers, setHeaders] = useState<Record<string, string>>({});
  const [headersValid, setHeadersValid] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [fetched, setFetched] = useState<FetchedRow[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Per-row advanced overrides (capacity + inference params), keyed by model id.
  // rowSuggestions: auto-filled from suggestCapacity on fetch; used when the
  // user hasn't manually modified the row's settings.
  const [rowOverrides, setRowOverrides] = useState<Record<string, RowOverride>>(
    {}
  );
  const [rowSuggestions, setRowSuggestions] = useState<
    Record<string, RowOverride>
  >({});
  const [settingsRowId, setSettingsRowId] = useState<string | null>(null);
  // Per-row reasoning capability from the same suggestCapacity lookup —
  // drives the effort/budget controls in the per-row settings dialog.
  const [rowCapabilities, setRowCapabilities] = useState<
    Record<string, ReasoningCapability | undefined>
  >({});

  // Per-row connectivity check (optional, does not gate submit).
  const [rowCheck, setRowCheck] = useState<
    Record<string, "checking" | "available" | "unavailable">
  >({});
  const [batchChecking, setBatchChecking] = useState(false);

  function changeProvider(next: string) {
    invalidateChecks();
    setProvider(next);
    const preset = presets.find((p) => p.key === next);
    setBaseUrl(preset?.baseUrl || "");
    setFetched([]);
    setSelected({});
  }

  const selectedCount = useMemo(
    () => Object.values(selected).filter(Boolean).length,
    [selected]
  );

  // Search filters the display only; selections are keyed by model id so they
  // survive searching.
  const visibleRows = useMemo(() => {
    const kw = search.trim().toLowerCase();
    if (!kw) return fetched;
    return fetched.filter((row) => row.model_name.toLowerCase().includes(kw));
  }, [fetched, search]);
  const allSelected =
    visibleRows.length > 0 && visibleRows.every((row) => selected[row.id]);

  function toggleAll(on: boolean) {
    setSelected((s) => {
      const next = { ...s };
      visibleRows.forEach((row) => {
        next[row.id] = on;
      });
      return next;
    });
  }

  // The fetched type is the provider's guess (LLM by default); operators can
  // correct it per row before importing. The stored probe result was measured
  // under the previous type, so reset it to force a re-probe before submit.
  function updateRowType(rowId: string, next: ModelType) {
    invalidateChecks(rowId);
    setFetched((prev) =>
      prev.map((r) => (r.id === rowId ? { ...r, model_type: next } : r))
    );
    setRowCheck((s) => {
      const nextCheck = { ...s };
      delete nextCheck[rowId];
      return nextCheck;
    });
  }

  async function fetchModels() {
    if (provider === CUSTOM_PROVIDER_KEY && !baseUrl.trim()) {
      message.warning(
        t("modelConfig.addDialog.baseUrlRequired", {
          defaultValue: "自定义服务商需要填写 Base URL",
        })
      );
      return;
    }
    const generation = ++discoveryGeneration.current;
    setFetching(true);
    setFetched([]);
    setSelected({});
    try {
      const result = tenantId
        ? await modelService.addManageProviderModel({
            tenantId,
            provider,
            apiKey,
            sslVerify,
            timeoutSeconds,
            httpHeaders: headers,
            ...(baseUrl ? { baseUrl } : {}),
          })
        : await modelService.addProviderModel({
            provider,
            apiKey,
            sslVerify,
            timeoutSeconds,
            httpHeaders: headers,
            ...(baseUrl ? { baseUrl } : {}),
          });
      if (discoveryGeneration.current !== generation) return;
      // Drop nameless entries (gateway internals / soft-deleted endpoints).
      const rows: FetchedRow[] = (result || [])
        .filter((m: any) => !!(m.id || m.model_name))
        .map((m: any) => ({
          id: m.id || m.model_name,
          model_name: m.id || m.model_name,
          model_type: (m.model_type || MODEL_TYPES.LLM) as ModelType,
        }));
      setFetched(rows);
      // Nothing selected by default — the user picks what to import.
      setSelected({});
      setRowOverrides({});
      setRowSuggestions({});
      setRowCapabilities({});
      setRowCheck({});
      setIssues({});
      // Auto-fill capacity from the catalog (same as the old dialog):
      // suggestCapacity is a local lookup, fast enough to batch.
      const suggestions: Record<string, RowOverride> = {};
      const capabilities: Record<string, ReasoningCapability | undefined> = {};
      const matched: Record<string, boolean> = {};
      await Promise.all(
        rows.map(async (row) => {
          try {
            if (!tenantId && row.model_type === MODEL_TYPES.LLM) {
              const profile = suggestModelProfile(
                row.model_name,
                models.data?.items ?? []
              );
              const preview = await previewModelProfile({
                request_model_id: row.model_name,
                provider_info: {
                  base_url: baseUrl.trim(),
                  provider_id:
                    provider === CUSTOM_PROVIDER_KEY ? null : provider,
                  ssl_verify: sslVerify,
                  timeout_seconds: timeoutSeconds,
                },
                model_profile: profile
                  ? { key: profile.key, revision: profile.revision }
                  : null,
              });
              matched[row.id] = !!(
                preview.matched_profile || preview.selected.model
              );
              return;
            }
            const s = await modelService.suggestCapacity({
              modelName: row.model_name,
              baseUrl,
              providerHint: provider,
              modelType: row.model_type,
            });
            if (s?.reasoningCapability) {
              capabilities[row.id] = s.reasoningCapability;
            }
            const settings = capacitySuggestionToSettings(s?.suggestions);
            if (settings) {
              suggestions[row.id] = { settings };
            }
          } catch {
            // catalog miss — leave empty, user can fill manually
          }
        })
      );
      if (discoveryGeneration.current !== generation) return;
      setProfileMatches(matched);
      setRowSuggestions(suggestions);
      setRowCapabilities(capabilities);
    } catch (error: any) {
      if (discoveryGeneration.current !== generation) return;
      setIssues({ __connection: modelCheckFailure(error) });
      log.error("fetch provider models failed", error);
      message.error(
        error?.message ||
          t("modelConfig.addDialog.fetchFailed", {
            defaultValue: "获取模型列表失败",
          })
      );
    } finally {
      if (discoveryGeneration.current === generation) setFetching(false);
    }
  }

  function outletDraft(row: FetchedRow): ModelProfileDraftRequest {
    const configured = rowOverrides[row.id]?.outletDraft;
    const matched = suggestModelProfile(
      row.model_name,
      models.data?.items ?? []
    );
    return {
      model_profile: matched
        ? { key: matched.key, revision: matched.revision }
        : null,
      selection_mode: "auto",
      ...configured,
      authentication_scheme: apiKey.trim() ? "bearer_token_v1" : "no_auth_v1",
      request_model_id: row.model_name,
      http_headers: headers,
      provider_info: {
        ...configured?.provider_info,
        ssl_verify: sslVerify,
        timeout_seconds: timeoutSeconds,
        base_url: baseUrl.trim(),
        provider_id: provider === CUSTOM_PROVIDER_KEY ? null : provider,
      },
    };
  }

  async function resolveOutletDraft(row: FetchedRow) {
    const draft = outletDraft(row);
    const preview = await previewModelProfile(draft);
    if (
      draft.catalog_revision &&
      draft.catalog_revision !== preview.catalog_revision
    )
      throw new Error(t("modelProfile.previewRequired"));
    return {
      ...draft,
      catalog_revision: preview.catalog_revision,
      parameter_values: outletSamplingValues(
        draft.parameter_values ?? {},
        preview.parameter_values
      ),
    };
  }

  async function checkRow(row: FetchedRow) {
    if (submitting) return;
    const generation = (generations.current[row.id] ?? 0) + 1;
    generations.current[row.id] = generation;
    const apply = (ok: boolean, issue?: ModelCheckIssue | null) => {
      if (generations.current[row.id] !== generation) return;
      setRowCheck((previous) => ({
        ...previous,
        [row.id]: ok ? "available" : "unavailable",
      }));
      setIssues((previous) => {
        const next = { ...previous };
        if (!ok)
          next[row.id] = issue ?? {
            category: "MODEL_NETWORK_ERROR",
            scope: "connection",
          };
        else delete next[row.id];
        return next;
      });
    };
    delete checkReceipts.current[row.id];
    setRowCheck((s) => ({ ...s, [row.id]: "checking" }));
    try {
      if (!tenantId && row.model_type === MODEL_TYPES.LLM) {
        const draft = await resolveOutletDraft(row);
        const result = await validateModelOutlet({
          draft: {
            ...draft,
            api_key:
              draft.authentication_scheme === "no_auth_v1"
                ? null
                : apiKey.trim() || null,
          },
        });
        if (generations.current[row.id] === generation && result.check_receipt)
          checkReceipts.current[row.id] = result.check_receipt;
        apply(result.ok, result.error);
        return;
      }
      // voice 凭证随探测透传，按当前类型门控防止类型切换后过期值泄漏
      // （只取手动 override——目录建议不携带语音凭证）
      const result = await modelService.verifyModelConfigConnectivity({
        modelName: row.model_name,
        modelType: row.model_type,
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim(),
        ...buildVoiceCredentialParams(
          row.model_type,
          rowOverrides[row.id]?.settings
        ),
      });
      apply(result.connectivity, {
        category: "MODEL_HTTP_ERROR",
        scope: "connection",
      });
    } catch (error) {
      apply(false, modelCheckFailure(error));
    }
  }

  async function checkAllSelected() {
    const rows = fetched.filter((row) => selected[row.id]);
    if (rows.length === 0 || batchChecking || submitting) return;
    setBatchChecking(true);
    await Promise.all(rows.map((row) => checkRow(row)));
    setBatchChecking(false);
  }

  async function submit() {
    const rows = fetched.filter((row) => selected[row.id]);
    if (rows.length === 0 || submitting) return;
    setSubmitting(true);
    let created = 0;
    const failed: string[] = [];
    // Display names the backend rejected as duplicates (HTTP 409 name
    // conflict). Tracked separately from `failed` so the summary can tell
    // the user exactly which rows collided instead of a generic failure.
    const duplicateNames: string[] = [];
    const createdDisplayNames: string[] = [];
    for (const row of rows) {
      // User-modified overrides win; otherwise use catalog suggestions.
      const override = rowOverrides[row.id] ?? rowSuggestions[row.id];
      // develop #4009: no automatic renaming — the clean model name is
      // the default display name; a collision with an existing row is
      // reported as a per-row failure instead of silently suffixed.
      const displayName = override?.displayName?.trim() || row.model_name;
      try {
        if (!tenantId && row.model_type === MODEL_TYPES.LLM) {
          const draft = await resolveOutletDraft(row);
          await createModelOutlet({
            ...draft,
            check_receipt: checkReceipts.current[row.id],
            api_key:
              draft.authentication_scheme === "no_auth_v1"
                ? null
                : apiKey.trim() || null,
          });
          createdDisplayNames.push(
            draft.display_name?.trim() || row.model_name
          );
          created++;
          continue;
        }
        const params: Record<string, any> = {
          name: row.model_name,
          type: row.model_type,
          url: baseUrl.trim(),
          apiKey: apiKey.trim(),
          displayName,
          maxTokens: isEmbeddingModelType(row.model_type) ? 1024 : 4096,
          modelFactory:
            provider === CUSTOM_PROVIDER_KEY
              ? "OpenAI-API-Compatible"
              : provider,
          connectStatus:
            rowCheck[row.id] === "available"
              ? "available"
              : rowCheck[row.id] === "unavailable"
                ? "unavailable"
                : "not_detected",
          // Batch rows leave default-slot auto-configuration to the single
          // finalize call after the loop, so the whole batch competes for
          // empty slots at once (and occupied slots stay untouched) instead
          // of the first row permanently claiming them.
          skipDefaultBackfill: true,
        };
        if (override?.settings) {
          applyAdvancedSettingsToParams(
            params,
            override.settings,
            rowCapabilities[row.id]
          );
        }
        // Embedding rows always carry chunk params (gear values or defaults).
        applyEmbeddingChunkParams(params, override?.settings);
        await createModel(tenantId, params);
        createdDisplayNames.push(displayName);
        created++;
      } catch (error: any) {
        if (isDisplayNameConflictError(error)) {
          duplicateNames.push(displayName);
        } else {
          failed.push(row.model_name);
        }
        log.error("batch add model failed", row.model_name, error);
      }
    }
    if (created > 0) {
      // Single finalize for the whole batch: empty slots get the best model
      // among the freshly created ones; occupied slots are never touched.
      // Only the user-facing flow (no tenantId override) — the manage-tenant
      // path targets another tenant and keeps its own behavior.
      // Best-effort — a failure here does not fail the import.
      if (
        !tenantId &&
        rows.some(
          (row) =>
            row.model_type !== MODEL_TYPES.LLM &&
            rowCheck[row.id] === "available"
        )
      ) {
        try {
          await modelService.backfillDefaults(createdDisplayNames);
        } catch (error) {
          log.warn("Failed to finalize default-model backfill:", error);
        }
      }
    }
    setSubmitting(false);
    const duplicateList = duplicateNames.join("、");
    const failedCount = failed.length + duplicateNames.length;
    if (created > 0) {
      if (failedCount === 0) {
        message.success(
          t("modelConfig.addDialog.batchSuccess", {
            defaultValue: `已添加 ${created} 个模型`,
            count: created,
            created,
          })
        );
      } else if (duplicateNames.length > 0) {
        // Partial success with name collisions: name the duplicates so the
        // operator knows a retry only needs the non-duplicate rows.
        message.warning(
          t("modelConfig.addDialog.batchPartialDuplicates", {
            defaultValue: `已添加 ${created} 个模型，${failedCount} 个失败，其中 ${duplicateNames.length} 个模型已存在（${duplicateList}）`,
            count: created,
            failed: failedCount,
            duplicates: duplicateNames.length,
            names: duplicateList,
          })
        );
      } else {
        message.warning(
          t("modelConfig.addDialog.batchPartial", {
            defaultValue: `已添加 ${created} 个模型，${failed.length} 个失败`,
            count: created,
            created,
            failed: failed.length,
          })
        );
      }
      onSuccess();
      if (
        failed.length > 0 &&
        !tenantId &&
        rows.every((row) => row.model_type === MODEL_TYPES.LLM)
      ) {
        const remaining = new Set(failed);
        setFetched((previous) =>
          previous.filter(
            (row) => remaining.has(row.model_name) || !selected[row.id]
          )
        );
        setSelected(
          Object.fromEntries(
            rows
              .filter((row) => remaining.has(row.model_name))
              .map((row) => [row.id, true])
          )
        );
      } else {
        onDone();
      }
      return;
    }
    // All creates failed: keep the dialog open so the operator can fix the
    // cause (key / URL / names) without re-entering everything.
    if (duplicateNames.length > 0 && failed.length === 0) {
      // Every row collided with an existing display name — the most common
      // batch-add confusion, so say so instead of the generic failure text.
      message.error(
        t("modelConfig.addDialog.batchAllDuplicates", {
          defaultValue: `全部 ${duplicateNames.length} 个模型添加失败：模型已存在（${duplicateList}），请勿重复添加`,
          total: duplicateNames.length,
          names: duplicateList,
        })
      );
    } else if (duplicateNames.length > 0) {
      message.error(
        t("modelConfig.addDialog.batchAllFailedDuplicates", {
          defaultValue: `全部 ${failedCount} 个模型添加失败：${duplicateNames.length} 个模型已存在（${duplicateList}），${failed.length} 个请检查后重试`,
          failed: failedCount,
          duplicates: duplicateNames.length,
          names: duplicateList,
          others: failed.length,
        })
      );
    } else {
      message.error(
        t("modelConfig.addDialog.batchAllFailed", {
          defaultValue: `全部 ${failed.length} 个模型添加失败，请检查后重试`,
          failed: failed.length,
        })
      );
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <fieldset
        disabled={submitting}
        className="min-h-0 min-w-0 flex-1 overflow-y-auto px-6 py-5"
      >
        <div className="grid grid-cols-1 gap-x-5 gap-y-5 md:grid-cols-[minmax(0,0.7fr)_minmax(0,1.8fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-2">
            <Label>
              {t("modelConfig.addDialog.provider", { defaultValue: "服务商" })}
            </Label>
            <ProviderSelect
              presets={presets}
              value={provider}
              onChange={changeProvider}
            />
          </div>
          <div className="min-w-0 space-y-2">
            <Label>
              {t("modelConfig.addDialog.baseUrl", { defaultValue: "Base URL" })}
            </Label>
            <Input
              className="min-w-0"
              value={baseUrl}
              onChange={(e) => {
                invalidateChecks();
                setBaseUrl(e.target.value);
                // Stored probe results were measured against the previous
                // endpoint.
                setRowCheck({});
              }}
              placeholder="https://api.example.com/v1"
              autoComplete="off"
            />
          </div>
          <div className="min-w-0 space-y-2">
            <Label>
              {t("modelConfig.addDialog.apiKey", { defaultValue: "API Key" })}
            </Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => {
                invalidateChecks();
                setApiKey(e.target.value);
                // Stored probe results were measured with the previous key.
                setRowCheck({});
              }}
              placeholder="sk-..."
              autoComplete="new-password"
            />
          </div>
        </div>

        <details className="mt-4 border-t pt-3">
          <summary className="cursor-pointer text-xs">
            {t("modelProfile.connectionSettings")}
          </summary>
          <ModelOutletForm layout="vertical" className="!pt-4">
            <ModelHttpConnectionSettings
              sslVerify={sslVerify}
              onSslVerifyChange={(value) => {
                invalidateChecks();
                setSslVerify(value);
              }}
              timeout={timeoutSeconds}
              onTimeoutChange={(value) => {
                invalidateChecks();
                setTimeoutSeconds(value);
              }}
              headers={headers}
              onHeadersChange={(value) => {
                invalidateChecks();
                setHeaders(value as Record<string, string>);
              }}
              onValidityChange={setHeadersValid}
              pending={submitting || batchChecking}
            />
          </ModelOutletForm>
        </details>
        {/* Fetched list */}
        {fetched.length > 0 && (
          <div className="mt-5 overflow-hidden rounded-xl border">
            <div className="border-b bg-secondary/30 px-4 py-2.5">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("modelConfig.addDialog.searchPlaceholder", {
                    defaultValue: "搜索模型名称",
                  })}
                  className="h-8 pl-9"
                />
              </div>
            </div>
            <button
              type="button"
              onClick={() => toggleAll(!allSelected)}
              className="flex w-full items-center justify-between border-b bg-secondary/30 px-4 py-2.5 text-left"
            >
              <span className="flex items-center gap-3">
                <span
                  className={cn(
                    "flex size-4 items-center justify-center rounded border",
                    allSelected
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-input"
                  )}
                >
                  {allSelected && <Check className="size-3" />}
                </span>
                <span className="text-sm font-medium">
                  {t("modelConfig.addDialog.fetchedTitle", {
                    defaultValue: "可用模型",
                  })}
                </span>
                <span className="text-xs text-muted-foreground">
                  {selectedCount}/{fetched.length}
                </span>
              </span>
              <span className="text-xs text-muted-foreground">
                {t("modelConfig.addDialog.toggleAll", {
                  defaultValue: "全选/取消",
                })}
              </span>
            </button>
            <ul className="max-h-64 divide-y overflow-y-auto">
              {visibleRows.length === 0 && (
                <li className="px-4 py-8 text-center text-xs text-muted-foreground">
                  {t("modelConfig.addDialog.noMatch", {
                    defaultValue: "未找到匹配的模型",
                  })}
                </li>
              )}
              {visibleRows.map((row) => {
                const on = !!selected[row.id];
                return (
                  <li key={row.id}>
                    {/* A div (not a button): the row hosts a Select and icon
                        Buttons, and nesting interactive elements inside a
                        <button> is invalid HTML. The row keeps click-to-toggle
                        semantics via the handler below. */}
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        if (!submitting)
                          setSelected((s) => ({ ...s, [row.id]: !s[row.id] }));
                      }}
                      onKeyDown={(e) => {
                        if (submitting) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelected((s) => ({ ...s, [row.id]: !s[row.id] }));
                        }
                      }}
                      className={cn(
                        "flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors hover:bg-secondary/40",
                        on && "bg-secondary/30"
                      )}
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span
                          className={cn(
                            "flex size-4 shrink-0 items-center justify-center rounded border",
                            on
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-input"
                          )}
                        >
                          {on && <Check className="size-3" />}
                        </span>
                        <span className="truncate font-mono text-sm">
                          {row.model_name}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        {rowCheck[row.id] === "checking" && (
                          <Loader2 className="size-3 animate-spin text-muted-foreground" />
                        )}
                        {rowCheck[row.id] === "available" && (
                          <span className="size-2 rounded-full bg-emerald-500" />
                        )}
                        {rowCheck[row.id] === "unavailable" && (
                          <span className="text-xs text-red-500">
                            {t("modelProfile.checkFailed")}
                          </span>
                        )}
                        {/* Per-row type editor — styled like the old badge.
                            stopPropagation keeps opening the dropdown from
                            toggling the row's selection checkbox. The span is
                            a propagation barrier only (role=presentation), so
                            keyboard events are stopped the same way. */}
                        <span
                          role="presentation"
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => e.stopPropagation()}
                        >
                          <Select
                            value={row.model_type}
                            onValueChange={(v) =>
                              updateRowType(row.id, v as ModelType)
                            }
                          >
                            <SelectTrigger
                              className={cn(
                                "h-6 w-fit gap-1 border-0 px-2 text-xs font-normal shadow-none focus:ring-0",
                                TYPE_BADGE_CLASS[row.model_type]
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
                        </span>
                        {row.model_type === MODEL_TYPES.LLM && (
                          <span className="text-xs text-muted-foreground">
                            {t(
                              outletDraft(row).model_profile ||
                                profileMatches[row.id]
                                ? "modelProfile.profileMatched"
                                : "modelProfile.chooseProfile"
                            )}
                          </span>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-7"
                          aria-label={`${t("modelProfile.checkModel")} ${row.model_name}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            checkRow(row);
                          }}
                          disabled={rowCheck[row.id] === "checking"}
                        >
                          <ShieldCheck className="size-3.5" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-7"
                          aria-label={`${t("modelProfile.configureModel")} ${row.model_name}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setSettingsRowId(row.id);
                          }}
                        >
                          <Settings2 className="size-3.5" />
                        </Button>
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {fetched.length === 0 && !fetching && (
          <div className="mt-5 flex flex-col items-center gap-2 rounded-xl border border-dashed py-10 text-center">
            <PackageOpen className="size-7 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">
              {t("modelConfig.addDialog.fetchHint", {
                defaultValue: "填写服务连接信息后获取模型列表",
              })}
            </p>
          </div>
        )}
      </fieldset>

      <div className="flex items-center justify-between border-t px-6 py-4">
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            className="shrink-0"
            disabled={submitting || fetching || !provider || !headersValid}
            onClick={fetchModels}
          >
            {fetching ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            {t("modelConfig.addDialog.fetchModels", {
              defaultValue: "获取模型列表",
            })}
          </Button>
          <span className="text-sm text-muted-foreground">
            {selectedCount > 0
              ? t("modelConfig.addDialog.selectedCount", {
                  defaultValue: `已选 ${selectedCount} 个模型`,
                  selectedCount,
                })
              : ""}
          </span>
          {selectedCount > 0 && (
            <Button
              size="sm"
              variant="outline"
              disabled={batchChecking}
              onClick={checkAllSelected}
            >
              {batchChecking ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ShieldCheck className="size-4" />
              )}
              {t("modelConfig.addDialog.batchCheck", {
                defaultValue: "批量检测",
              })}
            </Button>
          )}
          <ModelCheckSummary
            issues={issues}
            onRetryShared={() => {
              if (batchChecking || submitting) return;
              setBatchChecking(true);
              void Promise.all(
                fetched.filter((row) => !!issues[row.id]).map(checkRow)
              ).finally(() => setBatchChecking(false));
            }}
            modelNames={Object.fromEntries(
              fetched.map((row) => [row.id, row.model_name])
            )}
            onConfigure={(id) => {
              if (!submitting) setSettingsRowId(id);
            }}
            onRetry={(id) => {
              const row = fetched.find((item) => item.id === id);
              if (row) void checkRow(row);
            }}
          />
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onDone}>
            {t("common.cancel", { defaultValue: "取消" })}
          </Button>
          <Button
            disabled={selectedCount === 0 || submitting || !headersValid}
            onClick={submit}
          >
            {submitting && <Loader2 className="size-4 animate-spin" />}
            <Plus className="size-4" />
            {selectedCount > 0
              ? t("modelConfig.addDialog.addSelected", {
                  defaultValue: `添加 ${selectedCount} 个模型`,
                  count: selectedCount,
                })
              : t("modelConfig.addDialog.submit", { defaultValue: "添加模型" })}
          </Button>
        </div>
      </div>
      {/* Per-row advanced settings: user overrides win, else show catalog
          suggestions. key forces remount per row so useState picks up the
          correct initial values (otherwise the first open's empty state
          sticks for all subsequent rows). */}
      {settingsRowId &&
      !tenantId &&
      fetched.find((row) => row.id === settingsRowId)?.model_type ===
        MODEL_TYPES.LLM ? (
        <Dialog open onOpenChange={(open) => !open && setSettingsRowId(null)}>
          <DialogContent className="flex max-h-[85vh] w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-5xl">
            <DialogHeader className="border-b px-6 py-4">
              <DialogTitle>
                {fetched.find((row) => row.id === settingsRowId)?.model_name}
              </DialogTitle>
              <DialogDescription>
                {t("modelProfile.batchConfigurationHint")}
              </DialogDescription>
            </DialogHeader>
            <ModelOutletAddForm
              key={settingsRowId}
              configuration={{
                draft: outletDraft(
                  fetched.find((row) => row.id === settingsRowId)!
                ),
                onApply: (draft) => {
                  invalidateChecks(settingsRowId);
                  setRowOverrides((previous) => ({
                    ...previous,
                    [settingsRowId]: { outletDraft: draft },
                  }));
                  setRowCheck((previous) => {
                    const next = { ...previous };
                    delete next[settingsRowId];
                    return next;
                  });
                  setSettingsRowId(null);
                },
              }}
              onPendingChange={() => {}}
              onSuccess={() => {}}
              onDone={() => setSettingsRowId(null)}
            />
          </DialogContent>
        </Dialog>
      ) : (
        settingsRowId && (
          <RowSettingsDialog
            key={settingsRowId}
            row={fetched.find((r) => r.id === settingsRowId) ?? null}
            override={
              rowOverrides[settingsRowId] ?? rowSuggestions[settingsRowId]
            }
            reasoningCapability={rowCapabilities[settingsRowId]}
            onModelTypeChange={(next) => updateRowType(settingsRowId, next)}
            onSave={(next) => {
              setRowOverrides((prev) => ({
                ...prev,
                [settingsRowId]: next,
              }));
              setSettingsRowId(null);
            }}
            onClose={() => setSettingsRowId(null)}
          />
        )
      )}
    </div>
  );
}

/* ------------------------ per-row advanced settings ------------------------ */

function RowSettingsDialog({
  row,
  override,
  reasoningCapability,
  onModelTypeChange,
  onSave,
  onClose,
}: {
  row: FetchedRow | null;
  override?: RowOverride;
  reasoningCapability?: ReasoningCapability;
  /** Live type updates for the multimodal switch (embedding ↔
   *  multi_embedding). The switch mirrors the old dialog: it edits the
   *  row's type immediately, like the row type Select itself. */
  onModelTypeChange?: (next: ModelType) => void;
  onSave: (next: RowOverride) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  // One flat value drives the whole form — ModelAdvancedConfig renders the
  // type-aware v0 field set (capacity + inference for LLM family; chunk /
  // multimodal for embedding; voice credentials for stt/tts).
  const [settings, setSettings] = useState<ModelAdvancedSettingsValue>(
    override?.settings ?? {}
  );
  const [displayName, setDisplayName] = useState(override?.displayName ?? "");

  if (!row) return null;

  const isEmbedding = isEmbeddingModelType(row.model_type);

  function handleSave() {
    onSave({
      displayName: displayName.trim() || undefined,
      settings: Object.keys(settings).length > 0 ? settings : undefined,
    });
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[80vh] w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="text-sm font-mono">
            {row.model_name}
          </DialogTitle>
          <DialogDescription>
            {isEmbedding
              ? t("modelConfig.addDialog.rowSettingsDescEmbedding", {
                  defaultValue: "切片与多模态配置（留空使用默认值）",
                })
              : t("modelConfig.addDialog.rowSettingsDesc", {
                  defaultValue: "容量与推理参数（留空使用默认值）",
                })}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-5 space-y-2">
            <Label>
              {t("modelConfig.addDialog.displayName", {
                defaultValue: "展示名称",
              })}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {t("modelConfig.addDialog.displayNameHint", {
                  defaultValue: "选填，留空使用模型名称",
                })}
              </span>
            </Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t("modelConfig.addDialog.displayNameDefault", {
                defaultValue: "默认使用模型名称",
              })}
            />
          </div>

          {/* Type-aware fields: embedding rows get the chunk/multimodal
              panel, rerank gets max tokens, stt/tts get voice credentials */}
          <ModelAdvancedConfig
            value={settings}
            onChange={setSettings}
            modelType={row.model_type}
            reasoningCapability={reasoningCapability}
            onModelTypeChange={onModelTypeChange}
          />
        </div>
        <div className="flex justify-end gap-2 border-t px-6 py-4">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel", { defaultValue: "取消" })}
          </Button>
          <Button onClick={handleSave}>
            {t("common.save", { defaultValue: "保存" })}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
