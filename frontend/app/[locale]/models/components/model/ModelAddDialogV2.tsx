"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import {
  Alert,
  App,
  Button,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from "antd";
import { LoaderCircle, Settings, Settings2 } from "lucide-react";

import { useConfig } from "@/hooks/useConfig";
import { getConnectivityMeta, ConnectivityStatusType } from "@/lib/utils";
import { modelService } from "@/services/modelService";
import {
  InferenceFieldSpecsByType,
  ModelCatalogFullPayload,
  ModelCatalogProviderInfo,
  ModelConfig,
  ModelOption,
  ModelType,
  SingleModelConfig,
} from "@/types/modelConfig";
import { MODEL_TYPES } from "@/const/modelConfig";
import log from "@/lib/logger";

import {
  ModelAdvancedSettings,
  ModelAdvancedSettingsValue,
  buildInferenceParamsPayload,
  advancedSettingsValueFromRecord,
} from "./ModelAdvancedSettings";
import {
  ModelChunkSizeSlider,
  DEFAULT_EXPECTED_CHUNK_SIZE,
  DEFAULT_MAXIMUM_CHUNK_SIZE,
} from "./ModelChunkSizeSilder";
import {
  buildCapacityPayload,
  capacityFormFromModel,
  emptyCapacityForm,
  ModelCapacityFields,
  ModelCapacityFormState,
  validateCapacityForm,
} from "./ModelCapacityFields";

// =============================================================================
// v2.6.0: ModelAddDialogV2 — new Add Model dialog with Tabs
// =============================================================================
// Tab A (default): "从服务商导入" — preset provider → fetch list → per-row
//   enable/type/advanced-settings/connectivity → batch create.
// Tab B: "自定义接入" — single custom model form (legacy access path).
//
// This dialog is intentionally separate from ModelAddDialog.tsx per the design
// doc; the original dialog is left untouched for backward compatibility.
// =============================================================================

const { Option } = Select;

export interface AddedModel {
  name: string;
  type: ModelType;
}

interface ModelAddDialogV2Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (model?: AddedModel) => Promise<void>;
  /** Optional tenant id for super-admin manage paths. When absent, current-tenant endpoints are used. */
  tenantId?: string;
  /** When provided, the dialog opens in edit mode: the "自定义接入" tab is
      selected by default and the custom form is prefilled from this model.
      On submit the update endpoints are used instead of the create ones. */
  model?: ModelOption | null;
  /** Edit mode only: called after a connectivity probe finishes so the parent
      can refresh the model list row's connect_status in place. */
  onConnectivityChange?: (
    displayName: string,
    modelType: ModelType,
    status: "available" | "unavailable"
  ) => void;
}

// =============================================================================
// Helpers (re-implemented locally to avoid coupling to ModelAddDialog internals)
// =============================================================================

const translateError = (
  errorMessage: string,
  t: (key: string, params?: any) => string
): string => {
  if (!errorMessage) return errorMessage;
  const lower = errorMessage.toLowerCase();

  const nameMatch = /Name\s+(?:['"]([^'"]+)['"]|([^\s,]+))\s+is already in use/i.exec(
    errorMessage
  );
  if (nameMatch) {
    return t("model.dialog.error.nameAlreadyInUse", {
      name: nameMatch[1] || nameMatch[2],
    });
  }
  if (lower.includes("not found")) {
    return t("model.dialog.error.modelNotFound", { name: "" });
  }
  if (lower.includes("unsupported model type")) {
    return t("model.dialog.error.unsupportedModelType", { type: "unknown" });
  }
  return errorMessage;
};

const supportsCapacityFields = (type: ModelType | undefined): boolean => {
  if (!type) return false;
  return (
    type === MODEL_TYPES.LLM ||
    type === MODEL_TYPES.VLM ||
    type === MODEL_TYPES.VLM2 ||
    type === MODEL_TYPES.VLM3
  );
};

const isEmbeddingType = (type: ModelType | undefined): boolean =>
  type === MODEL_TYPES.EMBEDDING || type === MODEL_TYPES.MULTI_EMBEDDING;

const isVoiceType = (type: ModelType | undefined): boolean =>
  type === MODEL_TYPES.STT || type === MODEL_TYPES.TTS;

// Fallback labels (zh-CN) for the custom-tab connectivity probe statuses.
const CUSTOM_CONNECTIVITY_FALLBACK_LABELS: Record<string, string> = {
  available: "可用",
  unavailable: "不可用",
  checking: "检测中",
};

// Fallback labels for the batch-table connectivity column (adds "detecting").
const ROW_CONNECTIVITY_FALLBACK_LABELS: Record<string, string> = {
  ...CUSTOM_CONNECTIVITY_FALLBACK_LABELS,
  detecting: "检测中",
};

/** Resolve the effective type: embedding + multimodal → multi_embedding. */
const resolveMultimodalEmbeddingType = (
  type: ModelType,
  isMultimodal: boolean
): ModelType =>
  type === MODEL_TYPES.EMBEDDING && isMultimodal
    ? (MODEL_TYPES.MULTI_EMBEDDING as ModelType)
    : type;

/** Embedding chunk fields shared by the custom-tab payloads. */
const buildEmbeddingChunkFields = (
  chunkSizeRange: [number, number],
  chunkingBatchSize: string | undefined
): Record<string, any> => ({
  // Vector dimension is fixed at 1024 (not user-editable, matching original)
  expectedChunkSize: chunkSizeRange[0],
  maximumChunkSize: chunkSizeRange[1],
  chunkingBatchSize: Number.parseInt(chunkingBatchSize ?? "", 10) || 10,
});

const generateRandomSuffix = (length: number = 5): string => {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  const values = new Uint32Array(length);
  crypto.getRandomValues(values);
  let result = "";
  for (let i = 0; i < length; i++) {
    result += chars.charAt(values[i] % chars.length);
  }
  return result;
};

const defaultDisplayName = (modelName: string): string => {
  // A nameless model must not degrade to a bare random suffix ("tvj17") --
  // the random string carries no meaning and looks like garbage in titles.
  const base = modelName?.trim() || "custom-model";
  return `${base}${generateRandomSuffix(5)}`;
};

// =============================================================================
// Per-row state shape for the batch table
// =============================================================================

interface BatchRowState {
  enabled: boolean;
  modelType: ModelType;
  advanced: ModelAdvancedSettingsValue;
  capacity: ModelCapacityFormState;
  connectivityStatus: ConnectivityStatusType;
  connectivityMessage: string;
  checking: boolean;
  // Embedding-specific: multimodal switch + chunk size range slider
  isMultimodal: boolean;
  chunkSizeRange: [number, number];
}

/** Resolve the effective model type for a batch row: embedding + multimodal → multi_embedding. */
const resolveBatchModelType = (state: BatchRowState): ModelType =>
  resolveMultimodalEmbeddingType(state.modelType, state.isMultimodal);

/** Show the backend's auto-configured default models as a toast.

 * The backend fills default-model slots the tenant never configured on the
 * first create; surface that to the user so the implicit change is visible.
 */
const notifyAutoConfiguredDefaults = (
  autoConfigured: any[] | undefined,
  t: (key: string, params?: any) => string,
  message: { info: (content: string) => void }
) => {
  if (!autoConfigured?.length) return;
  const names = autoConfigured
    .map((entry) => entry?.display_name)
    .filter(Boolean)
    .join("、");
  if (!names) return;
  message.info(
    t("model.dialog.v2.autoConfiguredDefaults", {
      defaultValue: `已自动设为默认模型：${names}`,
    })
  );
};

/** Build the create-request params for one enabled batch row (Tab A submit). */
const buildBatchRowParams = (opts: {
  row: any;
  state: BatchRowState;
  baseUrl: string;
  apiKey: string;
  providerKey: string;
}): Record<string, any> => {
  const { row, state, baseUrl, apiKey, providerKey } = opts;
  const resolvedModelType = resolveBatchModelType(state);
  const capacityPayload: Record<string, any> = supportsCapacityFields(state.modelType)
    ? buildCapacityPayload(state.capacity)
    : {};

  const singleParams: Record<string, any> = {
    name: row.model_name,
    type: resolvedModelType,
    url: baseUrl,
    apiKey,
    maxTokens: row.max_tokens || (isEmbeddingType(resolvedModelType) ? 0 : 4096),
    displayName: (state.advanced.display_name as string) || defaultDisplayName(row.model_name),
    modelFactory: providerKey === "__custom__" ? "OpenAI-API-Compatible" : providerKey,
    // Batch submit requires every enabled row to have passed the probe
    // (hasUnchecked gate in handleBatchSubmit), so the verified result is
    // carried into the created record instead of resetting to not_detected.
    connectStatus: state.connectivityStatus === "available" ? "available" : undefined,
    contextWindowTokens: capacityPayload.contextWindowTokens,
    maxInputTokens: capacityPayload.maxInputTokens,
    maxOutputTokens: capacityPayload.maxOutputTokens,
    defaultOutputReserveTokens: capacityPayload.defaultOutputReserveTokens,
    tokenizerFamily: capacityPayload.tokenizerFamily,
    capacitySource: capacityPayload.capacitySource,
    // v2.6.0 inference params (temperature / top_p / extra_params incl. __custom__)
    // buildInferenceParamsPayload returns snake_case keys; buildInferenceParamsRequestBody
    // in modelService accepts both snake_case and camelCase.
    ...buildInferenceParamsPayload(state.advanced),
  };

  // Embedding-specific fields (aligned with original ModelAddDialog):
  // chunk size range from slider, batch size from dedicated input.
  // Vector dimension is fixed at 1024 (not user-editable, matching original).
  if (isEmbeddingType(resolvedModelType)) {
    singleParams.expectedChunkSize = state.chunkSizeRange[0];
    singleParams.maximumChunkSize = state.chunkSizeRange[1];
    singleParams.chunkingBatchSize = state.advanced.chunk_batch as number | undefined;
    singleParams.maxTokens = 1024;
  }

  // STT/TTS-specific fields (aligned with original ModelAddDialog)
  if (state.modelType === MODEL_TYPES.STT || state.modelType === MODEL_TYPES.TTS) {
    singleParams.modelFactory = (state.advanced.model_factory as string) || singleParams.modelFactory;
    singleParams.modelAppid = state.advanced.model_appid as string | undefined;
    singleParams.accessToken = state.advanced.access_token as string | undefined;
  }

  return singleParams;
};

const makeInitialRowState = (
  modelType: ModelType,
  catalogProfile?: any
): BatchRowState => {
  const advanced = advancedSettingsValueFromRecord(catalogProfile, {}, modelType);
  // STT/TTS default provider to DashScope (阿里灵积) when not provided by the
  // catalog, matching the original ModelAddDialog (sttProvider/ttsProvider:
  // "dashscope"). Ensures the STT服务商 dropdown is pre-selected when a voice
  // model row is created in the batch flow.
  if (
    (modelType === MODEL_TYPES.STT || modelType === MODEL_TYPES.TTS) &&
    !advanced.model_factory
  ) {
    advanced.model_factory = "dashscope";
  }
  return {
    enabled: false,
    modelType,
    advanced,
    capacity: capacityFormFromModel({
      contextWindowTokens: catalogProfile?.context_window_tokens,
      maxInputTokens: catalogProfile?.max_input_tokens,
      maxOutputTokens: catalogProfile?.max_output_tokens,
      defaultOutputReserveTokens:
        catalogProfile?.default_output_reserve_tokens,
      tokenizerFamily: catalogProfile?.tokenizer_family,
    }),
    connectivityStatus: null,
    connectivityMessage: "",
    checking: false,
    isMultimodal: false,
    chunkSizeRange: [DEFAULT_EXPECTED_CHUNK_SIZE, DEFAULT_MAXIMUM_CHUNK_SIZE],
  };
};

// =============================================================================
// Main dialog
// =============================================================================

export const ModelAddDialogV2 = ({
  isOpen,
  onClose,
  onSuccess,
  tenantId,
  model,
  onConnectivityChange,
}: ModelAddDialogV2Props) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { modelConfig, updateModelConfig, saveConfig } = useConfig();

  // ---------- shared state ----------
  const [activeTab, setActiveTab] = useState<"batch" | "custom">("batch");
  const [loading, setLoading] = useState(false);
  const [inferenceSpecs, setInferenceSpecs] = useState<InferenceFieldSpecsByType>({});

  // ---------- Tab A (batch) state ----------
  const [catalog, setCatalog] = useState<ModelCatalogFullPayload | null>(null);
  const [providerKey, setProviderKey] = useState<string>("__custom__");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<any[]>([]);
  // Client-side filter for the fetched model table (model name substring).
  const [modelSearchTerm, setModelSearchTerm] = useState("");
  const [rowStates, setRowStates] = useState<Record<string, BatchRowState>>({});
  const [settingsModalRowId, setSettingsModalRowId] = useState<string | null>(null);

  // ---------- Tab B (custom) state ----------
  const [customForm, setCustomForm] = useState({
    type: MODEL_TYPES.LLM as ModelType,
    name: "",
    displayName: "",
    url: "",
    apiKey: "",
    maxTokens: "4096",
    // Embedding-specific
    isMultimodal: false,
    chunkSizeRange: [DEFAULT_EXPECTED_CHUNK_SIZE, DEFAULT_MAXIMUM_CHUNK_SIZE] as [number, number],
    chunkingBatchSize: "10",
  });
  const [customCapacity, setCustomCapacity] =
    useState<ModelCapacityFormState>(emptyCapacityForm);
  const [customAdvanced, setCustomAdvanced] = useState<ModelAdvancedSettingsValue>({});
  // Suffix generated once per custom-access form lifecycle; reused while
  // the operator types the model name so display_name stays stable instead
  // of regenerating a new suffix on every keystroke. Regenerated on reset.
  const customNameSuffixRef = useRef(generateRandomSuffix(5));
  const [customAdvancedOpen, setCustomAdvancedOpen] = useState(false);
  const [customConnectivity, setCustomConnectivity] = useState<{
    status: ConnectivityStatusType;
    message: string;
  }>({ status: null, message: "" });
  const [verifyingCustom, setVerifyingCustom] = useState(false);
  // Whether the debounced capacity lookup found a suggestion for the current
  // model name. Drives the "已配置" tag next to the advanced settings button.
  const [capacityAutoFilled, setCapacityAutoFilled] = useState(false);

  // ---------- load inference specs + catalog on open ----------
  useEffect(() => {
    if (!isOpen) return;
    modelService
      .getInferenceFieldSpecs()
      .then((specs) => setInferenceSpecs(specs))
      .catch(() => setInferenceSpecs({}));
    modelService
      .getFullCatalog()
      .then(({ catalog }) => setCatalog(catalog))
      .catch(() => setCatalog(null));
  }, [isOpen]);

  // ---------- edit mode: default to "自定义接入" tab ----------
  // When opening, pick the initial tab from the mode: edit (model provided)
  // lands on "custom", add lands on "batch".
  useEffect(() => {
    if (!isOpen) return;
    setActiveTab(model ? "custom" : "batch");
  }, [isOpen, model]);

  // ---------- edit mode: prefill custom form from the existing model ----------
  // inferenceSpecs is in the dependency list so a late specs load (after the
  // model is set) re-runs this effect and populates inference params correctly.
  useEffect(() => {
    if (!isOpen || !model) return;
    setCustomForm({
      type: model.type,
      name: model.name,
      displayName: model.displayName || model.name,
      url: model.apiUrl || "",
      apiKey: model.apiKey || "",
      maxTokens: model.maxTokens?.toString() || "4096",
      isMultimodal: model.type === MODEL_TYPES.MULTI_EMBEDDING,
      chunkSizeRange: [
        model.expectedChunkSize || DEFAULT_EXPECTED_CHUNK_SIZE,
        model.maximumChunkSize || DEFAULT_MAXIMUM_CHUNK_SIZE,
      ] as [number, number],
      chunkingBatchSize: (model.chunkingBatchSize ?? 10).toString(),
    });
    setCustomCapacity(capacityFormFromModel(model));
    const advancedValue = advancedSettingsValueFromRecord(
      {
        temperature: model.temperature,
        top_p: model.topP,
        extra_params: model.extraParams,
        display_name: model.displayName,
        model_factory: model.modelFactory,
        model_appid: model.modelAppid,
        access_token: model.accessToken,
      },
      inferenceSpecs,
      model.type
    );
    // display_name drives the custom form's display-name field; ensure it is
    // always seeded even when not part of the inference specs.
    advancedValue.display_name = model.displayName || model.name;
    if (model.modelFactory) advancedValue.model_factory = model.modelFactory;
    if (model.modelAppid) advancedValue.model_appid = model.modelAppid;
    if (model.accessToken) advancedValue.access_token = model.accessToken;
    setCustomAdvanced(advancedValue);
    setCustomConnectivity({ status: null, message: "" });
    // Edit mode: if the existing model already carries capacity values, show
    // the "已配置" tag right away (the debounce lookup will also re-check and
    // fill any EMPTY field from catalog/LiteLLM when the name settles).
    const prefilled = capacityFormFromModel(model);
    setCapacityAutoFilled(
      Object.values(prefilled).some((v) => v !== "")
    );
  }, [isOpen, model, inferenceSpecs]);

  // ---------- Tab B: debounced capacity auto-lookup on model name ----------
  // When the operator types a model name in the custom-access form, wait for a
  // pause (500ms) then query suggest_capacity (catalog → bundled LiteLLM).
  // Only fills EMPTY capacity fields — values the user already typed (or that
  // came from an edit-mode prefill) are never overwritten. Sets the
  // "已配置" tag when a suggestion was found.
  useEffect(() => {
    if (!isOpen) return;
    const name = customForm.name.trim();
    if (!name || !supportsCapacityFields(customForm.type)) {
      setCapacityAutoFilled(false);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const suggestion = await modelService.suggestCapacity({
          modelName: name,
          baseUrl: customForm.url || undefined,
          modelType: customForm.type,
        });
        const s = suggestion?.suggestions;
        if (!s) {
          setCapacityAutoFilled(false);
          return;
        }
        setCapacityAutoFilled(true);
        setCustomCapacity((prev) => ({
          ...prev,
          ...(s.contextWindowTokens && !prev.contextWindowTokens
            ? { contextWindowTokens: String(s.contextWindowTokens) }
            : {}),
          ...(s.maxInputTokens && !prev.maxInputTokens
            ? { maxInputTokens: String(s.maxInputTokens) }
            : {}),
          ...(s.maxOutputTokens && !prev.maxOutputTokens
            ? { maxOutputTokens: String(s.maxOutputTokens) }
            : {}),
          ...(s.defaultOutputReserveTokens && !prev.defaultOutputReserveTokens
            ? { defaultOutputReserveTokens: String(s.defaultOutputReserveTokens) }
            : {}),
          ...(s.tokenizerFamily && !prev.tokenizerFamily
            ? { tokenizerFamily: s.tokenizerFamily }
            : {}),
        }));
      } catch {
        setCapacityAutoFilled(false);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [isOpen, customForm.name, customForm.url, customForm.type]);

  // ---------- derived: model type options (aligned with original ModelAddDialog) ----------
  const modelTypeOptions = useMemo(() => [
    { value: MODEL_TYPES.LLM, label: t("model.type.llm", { defaultValue: "LLM" }) },
    { value: MODEL_TYPES.EMBEDDING, label: t("model.type.embedding", { defaultValue: "Embedding" }) },
    { value: MODEL_TYPES.VLM, label: t("model.type.imageUnderstanding", { defaultValue: "VLM" }) },
    { value: MODEL_TYPES.VLM2, label: t("model.type.imageGeneration", { defaultValue: "VLM2" }) },
    { value: MODEL_TYPES.VLM3, label: t("model.type.videoUnderstanding", { defaultValue: "VLM3" }) },
    { value: MODEL_TYPES.RERANK, label: t("model.type.rerank", { defaultValue: "Rerank" }) },
    { value: MODEL_TYPES.STT, label: t("model.type.stt", { defaultValue: "STT" }) },
    { value: MODEL_TYPES.TTS, label: t("model.type.tts", { defaultValue: "TTS" }) },
  ], [t]);

  // ---------- derived: provider options ----------
  const providerOptions = useMemo(() => {
    console.log("catalog", catalog);
    const preset =
      catalog?.providers.map((p) => ({
        value: p.models?.[0]?.provider_key,
        label: p.provider_info.display_name,
        info: p.provider_info,
      })) || [];
    return [
      ...preset,
      { value: "__custom__", label: t("model.dialog.v2.customProvider", { defaultValue: "自定义 provider (OpenAI 兼容)" }), info: null },
    ];
  }, [catalog, t]);

  const selectedProviderInfo = useMemo<ModelCatalogProviderInfo | null>(() => {
    if (!catalog) return null;
    for (const p of catalog.providers) {
      if (p.models?.[0]?.provider_key === providerKey) {
        return p.provider_info;
      }
    }
    return null;
  }, [catalog, providerKey]);

  // Auto-fill base URL when a preset provider is selected
  useEffect(() => {
    if (selectedProviderInfo?.base_url) {
      setBaseUrl(selectedProviderInfo.base_url);
    } else if (providerKey === "__custom__") {
      // keep whatever the user typed
    }
  }, [selectedProviderInfo, providerKey]);

  // ---------- Tab A: fetch models ----------
  // All models are fetched from the live provider API via the OpenAI-compatible
  // GET /models endpoint. No catalog fallback.
  // For each fetched model, capacity is queried via suggest_capacity (see
  // applyRows) — model_catalog.json is no longer the capacity source.

  const applyRows = useCallback(async (rows: any[]) => {
    setFetchedModels(rows);
    const initStates: Record<string, BatchRowState> = {};
    await Promise.all(
      rows.map(async (row) => {
        const initialState = makeInitialRowState(row.model_type);
        // Default display_name to model name + 5-char random suffix
        initialState.advanced.display_name = defaultDisplayName(row.model_name);
        // Unified capacity source: query capability_profiles.py / bundled
        // LiteLLM JSON via suggest_capacity. Pure local lookups, no HTTP
        // probes, so batching one call per fetched model is cheap.
        try {
          const suggestion = await modelService.suggestCapacity({
            modelName: row.model_name,
            baseUrl,
            providerHint: providerKey,
            modelType: row.model_type,
          });
          const s = suggestion?.suggestions;
          if (s) {
            if (s.contextWindowTokens)
              initialState.capacity.contextWindowTokens = String(s.contextWindowTokens);
            if (s.maxInputTokens)
              initialState.capacity.maxInputTokens = String(s.maxInputTokens);
            if (s.maxOutputTokens)
              initialState.capacity.maxOutputTokens = String(s.maxOutputTokens);
            if (s.defaultOutputReserveTokens)
              initialState.capacity.defaultOutputReserveTokens = String(s.defaultOutputReserveTokens);
            if (s.tokenizerFamily)
              initialState.capacity.tokenizerFamily = s.tokenizerFamily;
          }
        } catch {
          // catalog miss + LLM disabled → leave empty; connectivity will fill
        }
        initStates[row.id] = initialState;
      })
    );
    setRowStates(initStates);
  }, [baseUrl, providerKey]);

  const handleFetchModels = useCallback(async () => {
    if (!apiKey.trim()) {
      message.warning(t("model.dialog.v2.warn.apiKeyRequired", { defaultValue: "请先输入 API Key" }));
      return;
    }
    setFetchingModels(true);
    setFetchedModels([]);
    setRowStates({});
    try {
      const result = tenantId
        ? await modelService.addManageProviderModel({
            tenantId,
            provider: providerKey,
            apiKey,
            ...(baseUrl ? { baseUrl } : {}),
          })
        : await modelService.addProviderModel({
            provider: providerKey,
            apiKey,
            ...(baseUrl ? { baseUrl } : {}),
          });
      // Provider /models responses occasionally carry nameless entries
      // (empty id) -- gateway internals or soft-deleted endpoints. They carry
      // no usable identity, so drop them instead of letting a bare random
      // suffix become the model's display name.
      const rows = (result || [])
        .filter((m: any) => !!(m.id || m.model_name))
        .map((m: any) => ({
          id: m.id || m.model_name,
          model_name: m.id || m.model_name,
          model_type: (m.model_type || MODEL_TYPES.LLM) as ModelType,
          max_tokens: m.max_tokens,
        }));
      await applyRows(rows);
    } catch (error: any) {
      message.error(
        t("model.dialog.v2.fetchFailed", {
          defaultValue: "获取模型列表失败",
          error: error?.message || "",
        })
      );
    } finally {
      setFetchingModels(false);
    }
  }, [apiKey, baseUrl, providerKey, tenantId, applyRows, message, t]);

  // ---------- Tab A: per-row connectivity check ----------
  const handleRowConnectivity = useCallback(
    async (rowId: string) => {
      const row = fetchedModels.find((m) => m.id === rowId);
      const state = rowStates[rowId];
      if (!row || !state) return;
      setRowStates((prev) => ({
        ...prev,
        [rowId]: { ...prev[rowId], checking: true },
      }));
      try {
        const inferencePayload = buildInferenceParamsPayload(state.advanced);
        const capacityPayload = supportsCapacityFields(state.modelType)
          ? buildCapacityPayload(state.capacity)
          : {};
        // Resolve actual model type: embedding + isMultimodal → multi_embedding
        const resolvedModelType: ModelType =
          state.modelType === MODEL_TYPES.EMBEDDING && state.isMultimodal
            ? (MODEL_TYPES.MULTI_EMBEDDING as ModelType)
            : state.modelType;
        // Embedding-specific params for connectivity check.
        // Vector dimension is fixed at 1024 (not user-editable, matching original).
        const embeddingPayload = isEmbeddingType(resolvedModelType)
          ? {
              expectedChunkSize: state.chunkSizeRange[0],
              maximumChunkSize: state.chunkSizeRange[1],
              chunkingBatchSize: state.advanced.chunk_batch as number | undefined,
              embeddingDim: 1024,
            }
          : {};
        const response = await modelService.verifyModelConfigConnectivity({
          modelName: row.model_name,
          modelType: resolvedModelType,
          baseUrl,
          apiKey,
          ...capacityPayload,
          ...inferencePayload,
          ...embeddingPayload,
        });
        setRowStates((prev) => {
          const next: BatchRowState = {
            ...prev[rowId],
            checking: false,
            connectivityStatus: response.connectivity ? "available" : "unavailable",
            connectivityMessage: response.error || "",
          };
          // Connectivity runs the full suggest_capacity flow (catalog + LLM
          // fallback), unlike the catalog-only fetch-time prefill. Fill only
          // verified non-empty fields so we don't wipe gear-popup edits.
          if (response.connectivity && response.capacitySuggestion?.suggestions) {
            const s = response.capacitySuggestion.suggestions;
            if (s.contextWindowTokens)
              next.capacity = { ...next.capacity, contextWindowTokens: String(s.contextWindowTokens) };
            if (s.maxInputTokens)
              next.capacity = { ...next.capacity, maxInputTokens: String(s.maxInputTokens) };
            if (s.maxOutputTokens)
              next.capacity = { ...next.capacity, maxOutputTokens: String(s.maxOutputTokens) };
            if (s.defaultOutputReserveTokens)
              next.capacity = { ...next.capacity, defaultOutputReserveTokens: String(s.defaultOutputReserveTokens) };
            if (s.tokenizerFamily)
              next.capacity = { ...next.capacity, tokenizerFamily: s.tokenizerFamily };
          }
          return { ...prev, [rowId]: next };
        });
      } catch (error: any) {
        setRowStates((prev) => ({
          ...prev,
          [rowId]: {
            ...prev[rowId],
            checking: false,
            connectivityStatus: "unavailable",
            connectivityMessage: error?.message || "",
          },
        }));
      }
    },
    [fetchedModels, rowStates, baseUrl, apiKey]
  );

  // ---------- Tab A: batch connectivity check (enabled rows only) ----------
  const [batchChecking, setBatchChecking] = useState(false);
  // Shared guard for the batch actions: the enabled rows, or null when none
  // are selected (the caller then shows the no-selection warning).
  const getEnabledRows = useCallback((): any[] | null => {
    const enabledRows = fetchedModels.filter((row) => rowStates[row.id]?.enabled);
    if (enabledRows.length === 0) {
      message.warning(t("model.dialog.v2.warn.noSelection", { defaultValue: "请至少启用一个模型" }));
      return null;
    }
    return enabledRows;
  }, [fetchedModels, rowStates, message, t]);

  const handleBatchConnectivity = useCallback(async () => {
    const enabledRows = getEnabledRows();
    if (!enabledRows) {
      return;
    }
    setBatchChecking(true);
    try {
      // Probe all enabled rows in parallel (mirrors the model-config page's
      // batch verify): row state updates are functional, so concurrent
      // completions land independently as they arrive.
      await Promise.all(
        enabledRows.map((row) => handleRowConnectivity(row.id))
      );
    } finally {
      setBatchChecking(false);
    }
  }, [getEnabledRows, handleRowConnectivity]);

  // ---------- Tab A: submit batch ----------
  const handleBatchSubmit = useCallback(async () => {
    const enabledRows = getEnabledRows();
    if (!enabledRows) {
      return;
    }
    // Require all enabled models to have passed connectivity testing before submit.
    const hasUnchecked = enabledRows.some(
      (row) => rowStates[row.id]?.connectivityStatus !== "available"
    );
    if (hasUnchecked) {
      message.warning(
        t("model.dialog.v2.warn.untestedModels", {
          defaultValue: "请先完成所有启用模型的连通性测试",
        })
      );
      return;
    }
    setLoading(true);
    try {
      let createdCount = 0;
      let autoConfiguredDefaults: any[] = [];
      for (const row of enabledRows) {
        const state = rowStates[row.id];
        const singleParams = buildBatchRowParams({
          row,
          state,
          baseUrl,
          apiKey,
          providerKey,
        });

        try {
          const createResult = tenantId
            ? await modelService.createManageTenantModel({ tenantId, ...singleParams } as any)
            : await modelService.addCustomModel(singleParams as any);
          if (createResult?.auto_configured_defaults?.length) {
            autoConfiguredDefaults = createResult.auto_configured_defaults;
          }
          createdCount++;
        } catch (error: any) {
          // Some models may have been created before this failure — refresh
          // the list so the user can see what succeeded.
          if (createdCount > 0) {
            await onSuccess().catch(() => {});
          }
          throw new Error(
            `${row.model_name}: ${translateError(error?.message || "", t)}`
          );
        }
      }
      message.success(t("model.dialog.v2.batchSuccess", { defaultValue: "批量入库成功" }));
      notifyAutoConfiguredDefaults(autoConfiguredDefaults, t, message);
      resetBatchState();
      onClose();
      // Use resolved model type for the success callback (embedding + isMultimodal → multi_embedding)
      const firstRow = enabledRows[0];
      const firstState = firstRow ? rowStates[firstRow.id] : null;
      await onSuccess(
        firstRow && firstState
          ? {
              name: (firstState.advanced.display_name as string) ||
                defaultDisplayName(firstRow.model_name),
              type: resolveBatchModelType(firstState),
            }
          : undefined
      );
    } catch (error: any) {
      message.error(
        t("model.dialog.v2.batchFailed", {
          defaultValue: "批量入库失败",
          error: error?.message || "",
        })
      );
    } finally {
      setLoading(false);
    }
  }, [getEnabledRows, rowStates, apiKey, baseUrl, providerKey, tenantId, message, t, onClose, onSuccess]);

  const resetBatchState = useCallback(() => {
    setFetchedModels([]);
    setRowStates({});
    setApiKey("");
    setBaseUrl("");
    setProviderKey("__custom__");
  }, []);

  // ---------- Tab B: connectivity + submit ----------
  const validateCustomForm = useCallback((): boolean => {
    if (!customForm.name.trim()) {
      message.warning(t("model.dialog.v2.warn.modelNameRequired", { defaultValue: "请填写模型名称" }));
      return false;
    }
    if (!customForm.url.trim()) {
      message.warning(t("model.dialog.v2.warn.urlRequired", { defaultValue: "请填写 Base URL" }));
      return false;
    }
    if (!model && !isVoiceType(customForm.type) && !customForm.apiKey.trim()) {
      message.warning(t("model.dialog.v2.warn.apiKeyRequired", { defaultValue: "请填写 API Key" }));
      return false;
    }
    return true;
  }, [customForm, model, message, t]);

  // Shared payload/context builder for the custom-tab handlers: the
  // connectivity probe and the submit paths resolve the same fields from the
  // custom form + advanced settings + capacity form.
  const buildCustomRequestContext = useCallback(() => {
    const inferencePayload = buildInferenceParamsPayload(customAdvanced);
    const capacityPayload = supportsCapacityFields(customForm.type)
      ? buildCapacityPayload(customCapacity)
      : {};
    // Resolve actual model type: embedding + isMultimodal → multi_embedding
    const resolvedModelType = resolveMultimodalEmbeddingType(
      customForm.type,
      customForm.isMultimodal
    );
    const isEmbedding = isEmbeddingType(resolvedModelType);
    const embeddingPayload = isEmbedding
      ? {
          embeddingDim: 1024,
          ...buildEmbeddingChunkFields(
            customForm.chunkSizeRange,
            customForm.chunkingBatchSize
          ),
        }
      : {};
    return {
      inferencePayload,
      capacityPayload,
      resolvedModelType,
      isEmbedding,
      embeddingPayload,
    };
  }, [customForm, customAdvanced, customCapacity]);

  const handleCustomConnectivity = useCallback(async () => {
    if (!validateCustomForm()) return;
    setVerifyingCustom(true);
    try {
      const {
        inferencePayload,
        capacityPayload,
        resolvedModelType,
        embeddingPayload,
      } = buildCustomRequestContext();
      const response = await modelService.verifyModelConfigConnectivity({
        modelName: customForm.name,
        modelType: resolvedModelType,
        baseUrl: customForm.url,
        apiKey: customForm.apiKey,
        ...capacityPayload,
        ...inferencePayload,
        ...embeddingPayload,
      });
      setCustomConnectivity({
        status: response.connectivity ? "available" : "unavailable",
        message: response.error || "",
      });
      // Edit mode: push the probe result back to the parent so the model list
      // row's connect_status refreshes in place (list state otherwise keeps
      // the stale status from the last loadModelLists).
      if (model && onConnectivityChange) {
        onConnectivityChange(
          model.displayName || model.name,
          resolvedModelType,
          response.connectivity ? "available" : "unavailable"
        );
      }
      // Capacity auto-fill moved to the model-name onChange debounce effect:
      // connectivity check only probes liveness with the CURRENT form config
      // and never mutates capacity fields the user may have already set.
    } catch (error: any) {
      setCustomConnectivity({
        status: "unavailable",
        message: error?.message || "",
      });
      if (model && onConnectivityChange) {
        onConnectivityChange(
          model.displayName || model.name,
          resolveMultimodalEmbeddingType(
            customForm.type,
            customForm.isMultimodal
          ),
          "unavailable"
        );
      }
    } finally {
      setVerifyingCustom(false);
    }
  }, [customForm, model, onConnectivityChange, message, t, validateCustomForm, buildCustomRequestContext]);

  // Custom-tab edit path: update the existing model row (manage or single API).
  const submitCustomEditPath = useCallback(
    async (
      ctx: ReturnType<typeof buildCustomRequestContext>,
      displayNameValue: string,
      isVoice: boolean
    ) => {
      const { capacityPayload, resolvedModelType, isEmbedding, inferencePayload } = ctx;
      const inferenceUpdate = {
        temperature: inferencePayload.temperature as number | undefined,
        topP: inferencePayload.top_p as number | undefined,
        extraParams: inferencePayload.extra_params as
          | Record<string, unknown>
          | undefined,
      };
      // Look up the existing row by its original display name, then send the
      // edited fields. Mirrors ModelEditDialogV2's update payload shape,
      // adapted to the fields exposed by the custom-access form.
      const originalDisplayName = model!.displayName || model!.name;
      const updateBase = {
        currentDisplayName: originalDisplayName,
        name: customForm.name,
        ...(displayNameValue !== originalDisplayName
          ? { displayName: displayNameValue }
          : {}),
        url: customForm.url,
        // Stored API keys are not returned to the browser. Keep the existing
        // key when editing and only send a key when it is replaced.
        ...(customForm.apiKey.trim() ? { apiKey: customForm.apiKey } : {}),
        ...(isEmbedding
          ? buildEmbeddingChunkFields(
              customForm.chunkSizeRange,
              customForm.chunkingBatchSize
            )
          : {}),
        ...(isVoice
          ? {
              modelFactory:
                (customAdvanced.model_factory as string) || undefined,
              modelAppid: customAdvanced.model_appid as string | undefined,
              accessToken: customAdvanced.access_token as string | undefined,
            }
          : {}),
        ...(supportsCapacityFields(customForm.type) ? capacityPayload : {}),
        ...inferenceUpdate,
      };
      if (tenantId) {
        await modelService.updateManageTenantModel({
          tenantId,
          ...updateBase,
        });
      } else {
        await modelService.updateSingleModel({
          ...updateBase,
          source: model!.source,
        });
      }
      return resolvedModelType;
    },
    [model, tenantId, customForm, customAdvanced, buildCustomRequestContext]
  );

  // Custom-tab create path: add a new model row (manage or single API).
  const submitCustomCreatePath = useCallback(
    async (
      ctx: ReturnType<typeof buildCustomRequestContext>,
      displayNameValue: string,
      maxTokensValue: number
    ) => {
      const { capacityPayload, resolvedModelType, isEmbedding, inferencePayload } = ctx;
      const modelParams: any = {
        name: customForm.name,
        type: resolvedModelType,
        url: customForm.url,
        apiKey: customForm.apiKey.trim() === "" ? "sk-no-api-key" : customForm.apiKey,
        maxTokens: maxTokensValue,
        displayName: displayNameValue,
        ...capacityPayload,
        ...inferencePayload,
        ...(isEmbedding
          ? {
              // Vector dimension is fixed at 1024 (not user-editable, matching original)
              maxTokens: 1024,
              ...buildEmbeddingChunkFields(
                customForm.chunkSizeRange,
                customForm.chunkingBatchSize
              ),
            }
          : {}),
      };

      if (tenantId) {
        const createResult = await modelService.createManageTenantModel({ tenantId, ...modelParams });
        return {
          resolvedModelType,
          autoConfiguredDefaults: createResult?.auto_configured_defaults ?? [],
        };
      } else {
        const createResult = await modelService.addCustomModel(modelParams);
        return {
          resolvedModelType,
          autoConfiguredDefaults: createResult?.auto_configured_defaults ?? [],
        };
      }
    },
    [tenantId, customForm, buildCustomRequestContext]
  );

  // Persist the custom-tab model into the local config (best-effort).
  const persistCustomLocalConfig = useCallback(
    async (ctx: ReturnType<typeof buildCustomRequestContext>, displayNameValue: string) => {
      const configKey: keyof ModelConfig =
        ctx.resolvedModelType === MODEL_TYPES.MULTI_EMBEDDING
          ? "multiEmbedding"
          : ctx.resolvedModelType;
      const existingApiKey = modelConfig?.[configKey]?.apiConfig?.apiKey || "";
      const nextModelConfig: SingleModelConfig = {
        id: 0,
        modelName: customForm.name,
        displayName: displayNameValue,
        apiConfig: {
          apiKey: model
            ? customForm.apiKey || existingApiKey
            : customForm.apiKey,
          modelUrl: customForm.url,
        },
        ...ctx.capacityPayload,
      };
      updateModelConfig({ [configKey]: nextModelConfig });
      const ok = await saveConfig();
      if (!ok) {
        log.warn("Failed to persist model config after custom add");
      }
    },
    [customForm, model, modelConfig, updateModelConfig, saveConfig]
  );

  const handleCustomSubmit = useCallback(async () => {
    if (!validateCustomForm()) return;
    if (supportsCapacityFields(customForm.type) && validateCapacityForm(customCapacity, [])) {
      message.error(t("model.dialog.capacity.error.positiveInteger"));
      return;
    }
    setLoading(true);
    try {
      const ctx = buildCustomRequestContext();
      const { resolvedModelType, isEmbedding } = ctx;
      const maxTokensValue = isEmbedding
        ? 0
        : Number.parseInt(customForm.maxTokens, 10) || 0;

      const displayNameValue =
        (customAdvanced.display_name as string) || defaultDisplayName(customForm.name);
      const isVoice = isVoiceType(resolvedModelType);

      let createResult: { resolvedModelType: ModelType; autoConfiguredDefaults: any[] } | null = null;
      if (model) {
        // ---------- edit (update) path ----------
        await submitCustomEditPath(ctx, displayNameValue, isVoice);
      } else {
        // ---------- add (create) path ----------
        createResult = await submitCustomCreatePath(ctx, displayNameValue, maxTokensValue);
      }

      await persistCustomLocalConfig(ctx, displayNameValue);

      message.success(
        model
          ? t("model.dialog.editSuccess", { defaultValue: "模型更新成功" })
          : t("model.dialog.v2.customSuccess", { defaultValue: "模型添加成功" })
      );
      notifyAutoConfiguredDefaults(createResult?.autoConfiguredDefaults, t, message);
      resetCustomForm();
      onClose();
      await onSuccess({
        name: (customAdvanced.display_name as string) || defaultDisplayName(customForm.name),
        type: resolvedModelType,
      });
    } catch (error: any) {
      message.error(
        t(
          model
            ? "model.dialog.error.editFailed"
            : "model.dialog.error.addFailed",
          {
            error: translateError(error?.message || "", t),
          }
        )
      );
    } finally {
      setLoading(false);
    }
  }, [customForm, customAdvanced, customCapacity, tenantId, model, message, t, onClose, onSuccess, validateCustomForm, buildCustomRequestContext, submitCustomEditPath, submitCustomCreatePath, persistCustomLocalConfig]);

  const resetCustomForm = useCallback(() => {
    setCustomForm({
      type: MODEL_TYPES.LLM as ModelType,
      name: "",
      displayName: "",
      url: "",
      apiKey: "",
      maxTokens: "4096",
      isMultimodal: false,
      chunkSizeRange: [DEFAULT_EXPECTED_CHUNK_SIZE, DEFAULT_MAXIMUM_CHUNK_SIZE],
      chunkingBatchSize: "10",
    });
    setCustomCapacity(emptyCapacityForm);
    setCustomAdvanced({});
    setCustomConnectivity({ status: null, message: "" });
    setCapacityAutoFilled(false);
    // Regenerate suffix so the next custom-access form gets a fresh one
    customNameSuffixRef.current = generateRandomSuffix(5);
  }, []);

  const handleClose = useCallback(() => {
    resetBatchState();
    resetCustomForm();
    setActiveTab("batch");
    onClose();
    console.log(providerOptions);
  }, [onClose, resetBatchState, resetCustomForm]);

  // ---------- Tab A: table columns ----------
  const batchColumns = useMemo(() => {
    return [
      {
        title: t("model.dialog.v2.col.modelName", { defaultValue: "模型" }),
        dataIndex: "model_name",
        key: "model_name",
        ellipsis: true,
      },
      {
        title: t("model.dialog.v2.col.type", { defaultValue: "类型" }),
        key: "model_type",
        width: 140,
        render: (_: any, row: any) => {
          const state = rowStates[row.id];
          if (!state) return row.model_type;
          return (
            <Select
              className="w-full"
              value={state.modelType}
              onChange={(next) =>
                setRowStates((prev) => ({
                  ...prev,
                  [row.id]: {
                    ...prev[row.id],
                    modelType: next as ModelType,
                    // reset advanced fields on type change
                    advanced: {},
                    capacity: emptyCapacityForm,
                  },
                }))
              }
              options={modelTypeOptions}
            />
          );
        },
      },
      {
        title: t("model.dialog.v2.col.enabled", { defaultValue: "启用" }),
        key: "enabled",
        width: 80,
        render: (_: any, row: any) => {
          const state = rowStates[row.id];
          if (!state) return null;
          return (
            <Switch
              checked={state.enabled}
              onChange={(checked) =>
                setRowStates((prev) => ({
                  ...prev,
                  [row.id]: { ...prev[row.id], enabled: checked },
                }))
              }
            />
          );
        },
      },
      {
        title: t("model.dialog.v2.col.advanced", { defaultValue: "高级设置" }),
        key: "advanced",
        width: 110,
        render: (_: any, row: any) => (
          <Button
            size="small"
            icon={<Settings size={14} />}
            onClick={() => setSettingsModalRowId(row.id)}
          >
            {t("model.dialog.v2.btn.advanced", { defaultValue: "设置" })}
          </Button>
        ),
      },
      {
        title: t("model.dialog.v2.col.connectivity", { defaultValue: "连通性" }),
        key: "connectivity",
        width: 180,
        render: (_: any, row: any) => {
          const state = rowStates[row.id];
          if (!state) return null;
          const meta = getConnectivityMeta(state.connectivityStatus);
          const statusText = state.connectivityStatus
            ? t(`model.connectivity.${state.connectivityStatus}`, {
                defaultValue:
                  ROW_CONNECTIVITY_FALLBACK_LABELS[state.connectivityStatus] ?? "",
              })
            : "";
          return (
            <Space size={6}>
              <Button
                size="small"
                loading={state.checking}
                onClick={() => handleRowConnectivity(row.id)}
              >
                {t("model.dialog.v2.btn.check", { defaultValue: "校验" })}
              </Button>
              {state.connectivityStatus && (
                <Tag color={meta.color}>{statusText}</Tag>
              )}
            </Space>
          );
        },
      },
    ];
  }, [rowStates, handleRowConnectivity, t]);

  // ---------- render ----------
  const settingsRow = settingsModalRowId
    ? fetchedModels.find((m) => m.id === settingsModalRowId)
    : null;
  const settingsState = settingsModalRowId
    ? rowStates[settingsModalRowId]
    : null;

  return (
    <Modal
      open={isOpen}
      onCancel={handleClose}
      title={
        model
          ? t("model.dialog.editTitle", { defaultValue: "编辑模型" })
          : t("model.dialog.v2.title", { defaultValue: "添加模型" })
      }
      width={900}
      footer={null}
      destroyOnClose
    >
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as "batch" | "custom")}
        items={[
          {
            key: "batch",
            label: t("model.dialog.v2.tab.batchImport", { defaultValue: "从服务商导入" }),
            children: (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-3">
                  <div>
                    <label className="block mb-1 text-sm font-medium text-gray-700">
                      {t("model.dialog.v2.provider", { defaultValue: "服务商" })}
                    </label>
                    <Select
                      className="w-full"
                      value={providerKey}
                      onChange={(v) => {
                        console.log(v);
                        setProviderKey(v);
                        setFetchedModels([]);
                        setRowStates({});
                      }}
                      options={providerOptions}
                      showSearch
                      optionFilterProp="label"
                    />
                  </div>
                  <div>
                    <label className="block mb-1 text-sm font-medium text-gray-700">
                      {t("model.dialog.v2.apiKey", { defaultValue: "API Key" })}
                    </label>
                    <Input.Password
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="sk-..."
                    />
                  </div>
                  <div>
                    <label className="block mb-1 text-sm font-medium text-gray-700">
                      {t("model.dialog.v2.baseUrl", { defaultValue: "Base URL" })}
                    </label>
                    <Input
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      placeholder="https://..."
                      // Editable even for preset providers: the auto-filled
                      // value is just a default, operators may point a preset
                      // provider at a mirror/private gateway.
                    />
                  </div>
                </div>

                <Space>
                  <Button
                    type="primary"
                    icon={fetchingModels ? <LoaderCircle size={14} className="animate-spin" /> : null}
                    onClick={handleFetchModels}
                    loading={fetchingModels}
                  >
                    {t("model.dialog.v2.btn.fetch", { defaultValue: "获取模型列表 (全部类型)" })}
                  </Button>
                  {fetchedModels.length > 0 && (
                    <Button
                      icon={batchChecking ? <LoaderCircle size={14} className="animate-spin" /> : null}
                      onClick={handleBatchConnectivity}
                      loading={batchChecking}
                      disabled={
                        Object.values(rowStates).filter((s) => s?.enabled).length === 0
                      }
                    >
                      {t("model.dialog.v2.btn.batchConnectivity", {
                        defaultValue: "批量测试连通性",
                        count: Object.values(rowStates).filter((s) => s?.enabled).length,
                      })}
                    </Button>
                  )}
                </Space>

                {fetchedModels.length > 0 && (
                  <>
                    <Input
                      allowClear
                      value={modelSearchTerm}
                      onChange={(e) => setModelSearchTerm(e.target.value)}
                      placeholder={t("model.dialog.v2.searchModels", {
                        defaultValue: "搜索模型名称过滤列表",
                      })}
                      style={{ maxWidth: 320 }}
                    />
                    <Table
                      size="small"
                      rowKey="id"
                      columns={batchColumns}
                      dataSource={
                        modelSearchTerm.trim()
                          ? fetchedModels.filter((m) =>
                              String(m.model_name || m.id || "")
                                .toLowerCase()
                                .includes(modelSearchTerm.trim().toLowerCase())
                            )
                          : fetchedModels
                      }
                      pagination={{ pageSize: 10, showSizeChanger: false }}
                      scroll={{ x: 700 }}
                    />
                  </>
                )}

                <div className="flex justify-end gap-2 pt-2 border-t">
                  <Button onClick={handleClose}>
                    {t("common.cancel", { defaultValue: "取消" })}
                  </Button>
                  <Button
                    type="primary"
                    loading={loading}
                    onClick={handleBatchSubmit}
                    disabled={
                      Object.values(rowStates).filter((s) => s?.enabled).length === 0 ||
                      Object.values(rowStates).some(
                        (s) => s?.enabled && s?.connectivityStatus !== "available"
                      )
                    }
                  >
                    {t("model.dialog.v2.btn.batchSubmit", {
                      defaultValue: "批量入库",
                      count: Object.values(rowStates).filter((s) => s.enabled).length,
                    })}
                  </Button>
                </div>
              </div>
            ),
          },
          {
            key: "custom",
            label: t("model.dialog.v2.tab.custom", { defaultValue: "自定义接入" }),
            children: (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-3">
                  <div>
                    <label className="block mb-1 text-sm font-medium text-gray-700">
                      {t("model.dialog.type", { defaultValue: "模型类型" })}
                    </label>
                    <Select
                      className="w-full"
                      value={customForm.type}
                      onChange={(v) => {
                        setCustomForm((prev) => ({ ...prev, type: v as ModelType }));
                        // STT defaults its provider to DashScope (阿里灵积) when
                        // empty, matching the original ModelAddDialog
                        // (sttProvider: "dashscope").
                        setCustomAdvanced(
                          v === MODEL_TYPES.STT ? { model_factory: "dashscope" } : {}
                        );
                        // Regenerate suffix on type switch for a fresh lifecycle
                        customNameSuffixRef.current = generateRandomSuffix(5);
                      }}
                      options={modelTypeOptions}
                    />
                  </div>
                  <div>
                    <label className="block mb-1 text-sm font-medium text-gray-700">
                      {t("model.dialog.name", { defaultValue: "模型名称" })}
                      <span className="text-red-500"> *</span>
                    </label>
                    <Input
                      value={customForm.name}
                      onChange={(e) => {
                        const name = e.target.value;
                        setCustomForm((prev) => ({ ...prev, name }));
                        // Name changed — the previous capacity lookup result no
                        // longer applies; the debounce effect will re-query.
                        setCapacityAutoFilled(false);
                        // Auto-populate display_name in advanced settings to
                        // align with batch-access behavior (defaultDisplayName).
                        // Uses the stable suffix from customNameSuffixRef so
                        // the random part doesn't change on every keystroke.
                        setCustomAdvanced((prev) => ({
                          ...prev,
                          display_name: name
                            ? `${name}${customNameSuffixRef.current}`
                            : "",
                        }));
                      }}
                    />
                  </div>
                  <div>
                    <label className="block mb-1 text-sm font-medium text-gray-700">
                      {t("model.dialog.url", { defaultValue: "Base URL" })}
                      <span className="text-red-500"> *</span>
                    </label>
                    <Input
                      value={customForm.url}
                      onChange={(e) => setCustomForm((prev) => ({ ...prev, url: e.target.value }))}
                      placeholder="https://..."
                    />
                  </div>
                  {/* TTS/STT don't need an API key */}
                  {!isVoiceType(customForm.type) && (
                    <div>
                      <label className="block mb-1 text-sm font-medium text-gray-700">
                        {t("model.dialog.apiKey", { defaultValue: "API Key" })}
                        <span className="text-red-500"> *</span>
                      </label>
                      <Input.Password
                        value={customForm.apiKey}
                        onChange={(e) =>
                          setCustomForm((prev) => ({ ...prev, apiKey: e.target.value }))
                        }
                        placeholder={
                          model
                            ? t("model.dialog.placeholder.apiKeyKeepExisting")
                            : t("model.dialog.placeholder.apiKey")
                        }
                      />
                    </div>
                  )}
                </div>

                {/* TTS/STT: render inference params inline (no popup).
                    Other types: advanced settings button + popup with
                    capacity, embedding-specific, and inference params. */}
                {isVoiceType(customForm.type) ? (
                  <ModelAdvancedSettings
                    modelType={customForm.type}
                    specs={inferenceSpecs}
                    value={customAdvanced}
                    onChange={setCustomAdvanced}
                    mode="default"
                  />
                ) : (
                  <div className="flex items-center gap-2">
                    <Button
                      size="small"
                      icon={<Settings2 size={14} />}
                      onClick={() => {
                        // Safety net: ensure STT defaults its provider to
                        // DashScope (阿里灵积) when opening the advanced
                        // settings, even if the type-select onChange default
                        // was bypassed (e.g. type already STT on open).
                        if (
                          customForm.type === MODEL_TYPES.STT &&
                          !customAdvanced.model_factory
                        ) {
                          setCustomAdvanced({
                            ...customAdvanced,
                            model_factory: "dashscope",
                          });
                        }
                        setCustomAdvancedOpen(true);
                      }}
                    >
                      {t("model.advanced.title", { defaultValue: "高级设置" })}
                    </Button>
                    {(capacityAutoFilled ||
                      Object.entries(customAdvanced).some(([k, v]) => {
                        if (k === "display_name") return false;
                        if (Array.isArray(v)) return v.length > 0;
                        return v != null && v !== "";
                      })) && (
                      <Tag color="blue">
                        {t("model.advanced.configured", { defaultValue: "已配置" })}
                      </Tag>
                    )}
                  </div>
                )}

                {/* connectivity */}
                <Space>
                  <Button
                    loading={verifyingCustom}
                    onClick={handleCustomConnectivity}
                  >
                    {t("model.dialog.v2.btn.checkConnectivity", { defaultValue: "校验连通性" })}
                  </Button>
                  {customConnectivity.status && (
                    <Tag color={getConnectivityMeta(customConnectivity.status).color}>
                      {t(`model.connectivity.${customConnectivity.status}`, {
                        defaultValue:
                          CUSTOM_CONNECTIVITY_FALLBACK_LABELS[
                            customConnectivity.status
                          ] ?? "",
                      })}
                    </Tag>
                  )}
                </Space>
                {customConnectivity.message && (
                  <Alert type="error" showIcon message={customConnectivity.message} />
                )}

                <div className="flex justify-end gap-2 pt-2 border-t">
                  <Button onClick={handleClose}>
                    {t("common.cancel", { defaultValue: "取消" })}
                  </Button>
                  <Button
                    type="primary"
                    loading={loading}
                    onClick={handleCustomSubmit}
                  >
                    {t("common.save", { defaultValue: "保存" })}
                  </Button>
                </div>
              </div>
            ),
          },
        ]}
      />

      {/* per-row advanced settings modal (Tab A) */}
      <Modal
        open={!!settingsModalRowId}
        onCancel={() => setSettingsModalRowId(null)}
        title={
          settingsRow
            ? `${t("model.advanced.title", { defaultValue: "高级设置" })} · ${settingsRow.model_name} (${settingsState?.modelType || ""})`
            : ""
        }
        width={640}
        footer={<Button onClick={() => setSettingsModalRowId(null)}>{t("common.close", { defaultValue: "关闭" })}</Button>}
      >
        {settingsRow && settingsState && (
          <div className="space-y-4">
            {supportsCapacityFields(settingsState.modelType) && (
              <ModelCapacityFields
                value={settingsState.capacity}
                onChange={(field, val) =>
                  setRowStates((prev) => ({
                    ...prev,
                    [settingsRow.id]: {
                      ...prev[settingsRow.id],
                      capacity: { ...prev[settingsRow.id].capacity, [field]: val },
                    },
                  }))
                }
                formMode="add"
              />
            )}
            {/* Embedding-specific: multimodal switch, chunk size slider, batch size */}
            {isEmbeddingType(settingsState.modelType) && (
              <div className="space-y-3 border-t pt-3">
                {/* Multimodal Switch */}
                <div>
                  <div className="flex justify-between items-center">
                    <label className="block text-sm font-medium text-gray-700">
                      {t("model.dialog.label.multimodal", { defaultValue: "多模态" })}
                    </label>
                    <Switch
                      checked={settingsState.isMultimodal}
                      onChange={(checked) =>
                        setRowStates((prev) => ({
                          ...prev,
                          [settingsRow.id]: {
                            ...prev[settingsRow.id],
                            isMultimodal: checked,
                          },
                        }))
                      }
                    />
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    {settingsState.isMultimodal
                      ? t("model.dialog.hint.multimodalEnabled", { defaultValue: "已启用多模态，将使用 multi_embedding 类型" })
                      : t("model.dialog.hint.multimodalDisabled", { defaultValue: "未启用多模态" })}
                  </div>
                </div>

                {/* Chunk Size Slider */}
                <div>
                  <label className="block mb-1 text-sm font-medium text-gray-700">
                    {t("modelConfig.slider.chunkingSize", { defaultValue: "文档切片大小" })}
                  </label>
                  <ModelChunkSizeSlider
                    value={settingsState.chunkSizeRange}
                    onChange={(value) =>
                      setRowStates((prev) => ({
                        ...prev,
                        [settingsRow.id]: {
                          ...prev[settingsRow.id],
                          chunkSizeRange: value,
                        },
                      }))
                    }
                  />
                </div>

                {/* Concurrent Request Count (chunk_batch) */}
                <div>
                  <label className="block mb-1 text-sm font-medium text-gray-700">
                    {t("modelConfig.input.chunkingBatchSize", { defaultValue: "单次请求切片量" })}
                  </label>
                  <Input
                    type="number"
                    min="1"
                    placeholder="10"
                    value={(settingsState.advanced.chunk_batch as number) ?? ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      setRowStates((prev) => ({
                        ...prev,
                        [settingsRow.id]: {
                          ...prev[settingsRow.id],
                          advanced: {
                            ...prev[settingsRow.id].advanced,
                            chunk_batch: val === "" ? undefined : Number(val),
                          },
                        },
                      }));
                    }}
                  />
                </div>
              </div>
            )}
            {inferenceSpecs[settingsState.modelType]?.length > 0 && (
              <ModelAdvancedSettings
                modelType={settingsState.modelType}
                specs={inferenceSpecs}
                value={settingsState.advanced}
                onChange={(next) =>
                  setRowStates((prev) => ({
                    ...prev,
                    [settingsRow.id]: { ...prev[settingsRow.id], advanced: next },
                  }))
                }
                mode="default"
              />
            )}
          </div>
        )}
      </Modal>

      {/* Tab B (custom): advanced settings popup */}
      <Modal
        open={customAdvancedOpen}
        onCancel={() => setCustomAdvancedOpen(false)}
        onOk={() => setCustomAdvancedOpen(false)}
        title={`${t("model.advanced.title", { defaultValue: "高级设置" })} - ${
          (customAdvanced.display_name as string) ||
          // Empty model name falls back to the type label, NOT a generated
          // "custom-modelXXXXX" placeholder -- a synthetic name in the title
          // reads like garbage (that suffix only makes sense at save time).
          (customForm.name ? defaultDisplayName(customForm.name) : "") ||
          customForm.type
        }`}
        okText={t("common.confirm", { defaultValue: "确定" })}
        cancelText={t("common.cancel", { defaultValue: "取消" })}
        width={640}
        centered
        destroyOnClose={false}
        styles={{ body: { maxHeight: "60vh", overflowY: "auto" } }}
      >
        <div className="space-y-4">
          {/* 1. Capacity fields (LLM/VLM) */}
          {supportsCapacityFields(customForm.type) && (
            <ModelCapacityFields
              value={customCapacity}
              onChange={(field, val) =>
                setCustomCapacity((prev) => ({ ...prev, [field]: val }))
              }
              formMode="add"
            />
          )}

          {/* 2. Embedding-specific fields */}
          {isEmbeddingType(customForm.type) && (
            <div className="space-y-3 border-t pt-3">
              {/* Multimodal Switch */}
              <div>
                <div className="flex justify-between items-center">
                  <label className="block text-sm font-medium text-gray-700">
                    {t("model.dialog.label.multimodal", { defaultValue: "多模态" })}
                  </label>
                  <Switch
                    checked={customForm.isMultimodal}
                    onChange={(checked) =>
                      setCustomForm((prev) => ({ ...prev, isMultimodal: checked }))
                    }
                  />
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {customForm.isMultimodal
                    ? t("model.dialog.hint.multimodalEnabled", { defaultValue: "已启用多模态，将使用 multi_embedding 类型" })
                    : t("model.dialog.hint.multimodalDisabled", { defaultValue: "未启用多模态" })}
                </div>
              </div>

              {/* Chunk Size Slider */}
              <div>
                <label className="block mb-1 text-sm font-medium text-gray-700">
                  {t("modelConfig.slider.chunkingSize", { defaultValue: "文档切片大小" })}
                </label>
                <ModelChunkSizeSlider
                  value={customForm.chunkSizeRange}
                  onChange={(value) =>
                    setCustomForm((prev) => ({ ...prev, chunkSizeRange: value }))
                  }
                />
              </div>

              {/* Concurrent Request Count (chunk_batch) */}
              <div>
                <label className="block mb-1 text-sm font-medium text-gray-700">
                  {t("modelConfig.input.chunkingBatchSize", { defaultValue: "单次请求切片量" })}
                </label>
                <Input
                  type="number"
                  min="1"
                  placeholder="10"
                  value={customForm.chunkingBatchSize}
                  onChange={(e) =>
                    setCustomForm((prev) => ({ ...prev, chunkingBatchSize: e.target.value }))
                  }
                />
              </div>
            </div>
          )}

          {/* 3. Inference params */}
          <ModelAdvancedSettings
            modelType={customForm.type}
            specs={inferenceSpecs}
            value={customAdvanced}
            onChange={setCustomAdvanced}
            mode="default"
          />
        </div>
      </Modal>
    </Modal>
  );
};

export default ModelAddDialogV2;
