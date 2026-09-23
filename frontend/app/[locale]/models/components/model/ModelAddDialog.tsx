"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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
import { modelService, ModelError } from "@/services/modelService";
import { ModelType, ReasoningCapability } from "@/types/modelConfig";
import log from "@/lib/logger";

import {
  ModelAdvancedSettingsValue,
  buildInferenceParamsPayload,
} from "./ModelAdvancedSettings";
import { ModelAdvancedConfig } from "./ModelAdvancedConfig";
import { TYPE_BADGE_CLASS, useTypeOptions } from "./modelTypeUi";

/**
 * v2.6.1 redesign (v0 design): the add-model dialog.
 *
 * Two tabs styled after the v0 ModelManagerDialog: 单个添加 (manual form:
 * provider / type / name / display name / base url / key) and 批量添加
 * (fetch the provider's model list and pick what to import). Built on the
 * project's shadcn/ui primitives.
 *
 * Deliberately simple: no per-row capacity or inference-param editing and
 * no pre-submit connectivity gate (the v0 logic) — models land in
 * not_detected state and are checked/edited from the library afterwards.
 * Both tabs reuse the existing single-model create endpoint per row.
 */

const CUSTOM_PROVIDER_KEY = "__custom__";

function generateRandomSuffix(length: number): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let result = "";
  const values = new Uint32Array(length);
  crypto.getRandomValues(values);
  for (let i = 0; i < length; i++) {
    result += chars.charAt(values[i] % chars.length);
  }
  return result;
}

const defaultDisplayName = (modelName: string): string => {
  const base = modelName?.trim() || "custom-model";
  return `${base}${generateRandomSuffix(5)}`;
};

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
  const [tab, setTab] = useState<"single" | "batch">(initialTab);

  // Reset the tab whenever the dialog reopens (the sync-ModelEngine button
  // opens it on the batch tab).
  useEffect(() => {
    if (isOpen) setTab(initialTab);
  }, [isOpen, initialTab]);

  return (
    <Dialog open={isOpen} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[85vh] w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="text-base">
            {t("modelConfig.addDialog.title", { defaultValue: "添加模型" })}
          </DialogTitle>
          <DialogDescription>
            {t("modelConfig.addDialog.description", {
              defaultValue:
                "手动添加单个模型，或从服务商一键批量导入可用模型。",
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 pt-5">
          <div className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1">
            <TabButton
              active={tab === "single"}
              onClick={() => setTab("single")}
              icon={<Plus className="size-4" />}
              title={t("modelConfig.addDialog.singleTab", {
                defaultValue: "单个添加",
              })}
              desc={t("modelConfig.addDialog.singleTabDesc", {
                defaultValue: "手动填写模型信息",
              })}
            />
            <TabButton
              active={tab === "batch"}
              onClick={() => setTab("batch")}
              icon={<Layers className="size-4" />}
              title={t("modelConfig.addDialog.batchTab", {
                defaultValue: "批量添加",
              })}
              desc={t("modelConfig.addDialog.batchTabDesc", {
                defaultValue: "从服务商导入",
              })}
            />
          </div>
        </div>

        {tab === "single" ? (
          <SingleAddForm
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
  desc,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 rounded-lg px-4 py-2.5 text-left transition-all",
        active
          ? "bg-card text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg",
          active ? "bg-primary text-primary-foreground" : "bg-background"
        )}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium leading-tight">{title}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {desc}
        </span>
      </span>
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
      <SelectTrigger className="w-full">
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

/**
 * Merge an advanced-settings value (snake_case spec keys) into the create
 * params. buildInferenceParamsPayload emits snake_case top-level keys, but
 * buildCapacityRequestBody in modelService only reads camelCase — without
 * this explicit mapping the capacity fields are silently dropped on create
 * (mirrors the inline mapping ModelAddDialogV2 does for the same contract).
 */
function applyAdvancedSettingsToParams(
  params: Record<string, any>,
  settings: ModelAdvancedSettingsValue
) {
  const payload = buildInferenceParamsPayload(settings);
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

  const [provider, setProvider] = useState<string>(CUSTOM_PROVIDER_KEY);
  const [type, setType] = useState<ModelType>(MODEL_TYPES.LLM as ModelType);
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
  // Connectivity probe; the submit is gated on a passing result, matching
  // the batch tab. Any form change resets it.
  const [probe, setProbe] = useState<
    "idle" | "checking" | "available" | "unavailable"
  >("idle");

  // Auto-detect capacity + reasoning capability whenever name and URL are
  // filled (debounced); user-saved overrides (the gear) win over suggestions.
  useEffect(() => {
    if (!name.trim() || !baseUrl.trim()) {
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
  }, [name, baseUrl, provider, type]);

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
      });
      setProbe(result.connectivity ? "available" : "unavailable");
    } catch {
      setProbe("unavailable");
    }
  }

  async function submit() {
    if (!canSubmit || submitting) return;
    // Same gate as the batch tab: the model must pass the probe first.
    if (probe !== "available") {
      message.warning(
        t("modelConfig.addDialog.singleUntestedWarning", {
          defaultValue: "请先通过连通性检测再添加模型",
        })
      );
      return;
    }
    setSubmitting(true);
    try {
      const params: Record<string, any> = {
        name: name.trim(),
        type,
        url: baseUrl.trim(),
        apiKey: apiKey.trim(),
        displayName: displayName.trim() || name.trim(),
        maxTokens: type === MODEL_TYPES.EMBEDDING ? 1024 : 4096,
        modelFactory: isCustom ? "OpenAI-API-Compatible" : provider,
        // The gate above guarantees a passing probe with these exact values.
        connectStatus: "available",
      };
      if (effective?.settings) {
        applyAdvancedSettingsToParams(params, effective.settings);
      }
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
              <SelectTrigger className="w-full">
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

      {/* Advanced settings (capacity + inference params) */}
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

  const [provider, setProvider] = useState<string>(CUSTOM_PROVIDER_KEY);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
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
    if (!apiKey.trim()) {
      message.warning(
        t("model.dialog.v2.warn.apiKeyRequired", {
          defaultValue: "请先输入 API Key",
        })
      );
      return;
    }
    if (provider === CUSTOM_PROVIDER_KEY && !baseUrl.trim()) {
      message.warning(
        t("modelConfig.addDialog.baseUrlRequired", {
          defaultValue: "自定义服务商需要填写 Base URL",
        })
      );
      return;
    }
    setFetching(true);
    setFetched([]);
    setSelected({});
    try {
      const result = tenantId
        ? await modelService.addManageProviderModel({
            tenantId,
            provider,
            apiKey,
            ...(baseUrl ? { baseUrl } : {}),
          })
        : await modelService.addProviderModel({
            provider,
            apiKey,
            ...(baseUrl ? { baseUrl } : {}),
          });
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
      // Auto-fill capacity from the catalog (same as the old dialog):
      // suggestCapacity is a local lookup, fast enough to batch.
      const suggestions: Record<string, RowOverride> = {};
      const capabilities: Record<string, ReasoningCapability | undefined> = {};
      await Promise.all(
        rows.map(async (row) => {
          try {
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
      setRowSuggestions(suggestions);
      setRowCapabilities(capabilities);
    } catch (error: any) {
      log.error("fetch provider models failed", error);
      message.error(
        error?.message ||
          t("modelConfig.addDialog.fetchFailed", {
            defaultValue: "获取模型列表失败",
          })
      );
    } finally {
      setFetching(false);
    }
  }

  async function checkRow(row: FetchedRow) {
    setRowCheck((s) => ({ ...s, [row.id]: "checking" }));
    try {
      const result = await modelService.verifyModelConfigConnectivity({
        modelName: row.model_name,
        modelType: row.model_type,
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim(),
      });
      setRowCheck((s) => ({
        ...s,
        [row.id]: result.connectivity ? "available" : "unavailable",
      }));
    } catch {
      setRowCheck((s) => ({ ...s, [row.id]: "unavailable" }));
    }
  }

  async function checkAllSelected() {
    const rows = fetched.filter((row) => selected[row.id]);
    if (rows.length === 0 || batchChecking) return;
    setBatchChecking(true);
    await Promise.all(rows.map((row) => checkRow(row)));
    setBatchChecking(false);
  }

  async function submit() {
    const rows = fetched.filter((row) => selected[row.id]);
    if (rows.length === 0 || submitting) return;
    // Require all selected models to have passed the connectivity probe —
    // same gate as the old dialog. Prevents adding models that can't connect.
    const untested = rows.filter((row) => rowCheck[row.id] !== "available");
    if (untested.length > 0) {
      message.warning(
        t("modelConfig.addDialog.untestedWarning", {
          defaultValue: `有 ${untested.length} 个模型未通过连通性检测，请先批量检测`,
          count: untested.length,
        })
      );
      return;
    }
    setSubmitting(true);
    let created = 0;
    const failed: string[] = [];
    for (const row of rows) {
      // User-modified overrides win; otherwise use catalog suggestions.
      const override = rowOverrides[row.id] ?? rowSuggestions[row.id];
      try {
        const params: Record<string, any> = {
          name: row.model_name,
          type: row.model_type,
          url: baseUrl.trim(),
          apiKey: apiKey.trim(),
          displayName:
            override?.displayName?.trim() || defaultDisplayName(row.model_name),
          maxTokens: row.model_type === MODEL_TYPES.EMBEDDING ? 1024 : 4096,
          modelFactory:
            provider === CUSTOM_PROVIDER_KEY
              ? "OpenAI-API-Compatible"
              : provider,
          // The batch gate requires every selected model to have passed the
          // connectivity probe (rowCheck === "available") before submit, so
          // carry the verified result into the created record instead of
          // resetting to not_detected.
          connectStatus: "available",
        };
        if (override?.settings) {
          applyAdvancedSettingsToParams(params, override.settings);
        }
        await createModel(tenantId, params);
        created++;
      } catch (error: any) {
        failed.push(row.model_name);
        log.error("batch add model failed", row.model_name, error);
      }
    }
    setSubmitting(false);
    if (created > 0) {
      if (failed.length === 0) {
        message.success(
          t("modelConfig.addDialog.batchSuccess", {
            defaultValue: `已添加 ${created} 个模型`,
            count: created,
          })
        );
      } else {
        message.warning(
          t("modelConfig.addDialog.batchPartial", {
            defaultValue: `已添加 ${created} 个模型，${failed.length} 个失败`,
            count: created,
            failed: failed.length,
          })
        );
      }
    }
    onSuccess();
    onDone();
  }

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
              {t("modelConfig.addDialog.apiKey", { defaultValue: "API Key" })}
            </Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
          </div>
          <div className="col-span-2 space-y-2">
            <Label>
              {t("modelConfig.addDialog.baseUrl", { defaultValue: "Base URL" })}
            </Label>
            <div className="flex gap-2">
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
              />
              <Button
                variant="outline"
                className="shrink-0"
                disabled={fetching || !provider}
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
            </div>
          </div>
        </div>

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
                    <button
                      type="button"
                      onClick={() =>
                        setSelected((s) => ({ ...s, [row.id]: !s[row.id] }))
                      }
                      className={cn(
                        "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors hover:bg-secondary/40",
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
                          <span className="size-2 rounded-full bg-red-500" />
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
                        {rowOverrides[row.id] && (
                          <span className="size-1.5 rounded-full bg-primary" />
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-7"
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
                          onClick={(e) => {
                            e.stopPropagation();
                            setSettingsRowId(row.id);
                          }}
                        >
                          <Settings2 className="size-3.5" />
                        </Button>
                      </span>
                    </button>
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
                defaultValue: "填写 API Key 后获取模型列表",
              })}
            </p>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {selectedCount > 0
              ? t("modelConfig.addDialog.selectedCount", {
                  defaultValue: `已选 ${selectedCount} 个模型`,
                  count: selectedCount,
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
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onDone}>
            {t("common.cancel", { defaultValue: "取消" })}
          </Button>
          <Button disabled={selectedCount === 0 || submitting} onClick={submit}>
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
      {settingsRowId && (
        <RowSettingsDialog
          key={settingsRowId}
          row={fetched.find((r) => r.id === settingsRowId) ?? null}
          override={
            rowOverrides[settingsRowId] ?? rowSuggestions[settingsRowId]
          }
          reasoningCapability={rowCapabilities[settingsRowId]}
          onSave={(next) => {
            setRowOverrides((prev) => ({
              ...prev,
              [settingsRowId]: next,
            }));
            setSettingsRowId(null);
          }}
          onClose={() => setSettingsRowId(null)}
        />
      )}
    </div>
  );
}

/* ------------------------ per-row advanced settings ------------------------ */

function RowSettingsDialog({
  row,
  override,
  reasoningCapability,
  onSave,
  onClose,
}: {
  row: FetchedRow | null;
  override?: RowOverride;
  reasoningCapability?: ReasoningCapability;
  onSave: (next: RowOverride) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  // One flat value drives the whole form — ModelAdvancedConfig renders the
  // fixed v0 field set (capacity + inference + custom params).
  const [settings, setSettings] = useState<ModelAdvancedSettingsValue>(
    override?.settings ?? {}
  );
  const [displayName, setDisplayName] = useState(override?.displayName ?? "");

  if (!row) return null;

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
            {t("modelConfig.addDialog.rowSettingsDesc", {
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
                  defaultValue: "选填，留空自动生成",
                })}
              </span>
            </Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t("modelConfig.addDialog.displayNameDefault", {
                defaultValue: "默认自动生成",
              })}
            />
          </div>
          <ModelAdvancedConfig
            value={settings}
            onChange={setSettings}
            modelType={row.model_type}
            reasoningCapability={reasoningCapability}
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
