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
} from "lucide-react";

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
import { ModelType } from "@/types/modelConfig";
import log from "@/lib/logger";

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

const TYPE_OPTIONS: ModelType[] = [
  MODEL_TYPES.LLM,
  MODEL_TYPES.EMBEDDING,
  MODEL_TYPES.MULTI_EMBEDDING,
  MODEL_TYPES.RERANK,
  MODEL_TYPES.VLM,
  MODEL_TYPES.VLM2,
  MODEL_TYPES.VLM3,
  MODEL_TYPES.VLM4,
  MODEL_TYPES.STT,
  MODEL_TYPES.TTS,
];

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

/* ------------------------------ shared helpers ------------------------------ */

function useTypeOptions() {
  const { t } = useTranslation();
  return useMemo(
    () =>
      TYPE_OPTIONS.map((v) => ({
        value: v,
        label: t(`model.type.${TYPE_LABEL_KEY_MAP[v] ?? v}`, {
          defaultValue: v,
        }),
      })),
    [t]
  );
}

function typeLabel(type: string, t: (key: string, opts?: any) => string) {
  return t(`model.type.${TYPE_LABEL_KEY_MAP[type] ?? type}`, {
    defaultValue: type,
  });
}

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

/* ------------------------------ 单个添加 ------------------------------ */

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

  async function submit() {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try {
      await createModel(tenantId, {
        name: name.trim(),
        type,
        url: baseUrl.trim(),
        apiKey: apiKey.trim(),
        displayName: displayName.trim() || name.trim(),
        maxTokens: type === MODEL_TYPES.EMBEDDING ? 1024 : 4096,
        modelFactory: isCustom ? "OpenAI-API-Compatible" : provider,
      });
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
            <Select value={provider} onValueChange={changeProvider}>
              <SelectTrigger className="w-full">
                <SelectValue />
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
          </div>
          <div className="space-y-2">
            <Label>
              {t("modelConfig.addDialog.modelType", {
                defaultValue: "模型类型",
              })}
            </Label>
            <Select value={type} onValueChange={(v) => setType(v as ModelType)}>
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
              onChange={(e) => setName(e.target.value)}
              placeholder="Qwen/Qwen3-8B"
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
            />
          </div>
          <div className="col-span-2 space-y-2">
            <Label>
              {t("modelConfig.addDialog.baseUrl", { defaultValue: "Base URL" })}
            </Label>
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
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
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
          </div>
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t px-6 py-4">
        <Button variant="outline" onClick={onDone}>
          {t("common.cancel", { defaultValue: "取消" })}
        </Button>
        <Button disabled={!canSubmit || submitting} onClick={submit}>
          {submitting && <Loader2 className="size-4 animate-spin" />}
          {t("modelConfig.addDialog.submit", { defaultValue: "添加模型" })}
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------ 批量添加 ------------------------------ */

interface FetchedRow {
  id: string;
  model_name: string;
  model_type: ModelType;
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

  const [provider, setProvider] = useState<string>("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [fetching, setFetching] = useState(false);
  const [fetched, setFetched] = useState<FetchedRow[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);

  // Default to the first preset once loaded.
  useEffect(() => {
    if (!provider && presets.length > 0) {
      setProvider(presets[0].key);
      setBaseUrl(presets[0].baseUrl);
    }
  }, [presets, provider]);

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
  const allSelected = fetched.length > 0 && selectedCount === fetched.length;

  function toggleAll(on: boolean) {
    const next: Record<string, boolean> = {};
    if (on) {
      fetched.forEach((row) => (next[row.id] = true));
    }
    setSelected(next);
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
      // v0 behavior: everything fetched is selected by default.
      const next: Record<string, boolean> = {};
      rows.forEach((row) => (next[row.id] = true));
      setSelected(next);
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

  async function submit() {
    const rows = fetched.filter((row) => selected[row.id]);
    if (rows.length === 0 || submitting) return;
    setSubmitting(true);
    let created = 0;
    const failed: string[] = [];
    for (const row of rows) {
      try {
        await createModel(tenantId, {
          name: row.model_name,
          type: row.model_type,
          url: baseUrl.trim(),
          apiKey: apiKey.trim(),
          displayName: defaultDisplayName(row.model_name),
          maxTokens: row.model_type === MODEL_TYPES.EMBEDDING ? 1024 : 4096,
          modelFactory: provider,
        });
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
            <Select value={provider} onValueChange={changeProvider}>
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
              </SelectContent>
            </Select>
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
              {fetched.map((row) => {
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
                      <Badge
                        variant="secondary"
                        className={cn(
                          "shrink-0 border-0 text-xs font-normal",
                          TYPE_BADGE_CLASS[row.model_type]
                        )}
                      >
                        {typeLabel(row.model_type, t)}
                      </Badge>
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
        <span className="text-sm text-muted-foreground">
          {selectedCount > 0
            ? t("modelConfig.addDialog.selectedCount", {
                defaultValue: `已选 ${selectedCount} 个模型`,
                count: selectedCount,
              })
            : ""}
        </span>
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
    </div>
  );
}
