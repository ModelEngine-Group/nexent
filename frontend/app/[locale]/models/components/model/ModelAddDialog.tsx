import { useMemo, useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Modal, Select, Input, Button, Switch, Tooltip, App } from "antd";
import { InfoCircleFilled } from "@ant-design/icons";
import {
  LoaderCircle,
  ChevronRight,
  ChevronDown,
  Settings,
} from "lucide-react";

import { useConfig } from "@/hooks/useConfig";
import { getConnectivityMeta, ConnectivityStatusType } from "@/lib/utils";
import { modelService } from "@/services/modelService";
import {
  ModelType,
  SingleModelConfig,
  STTModelConfig,
  TTSModelConfig,
} from "@/types/modelConfig";
import { MODEL_TYPES, PROVIDER_LINKS } from "@/const/modelConfig";
import { useSiliconModelList } from "@/hooks/model/useSiliconModelList";
import { useDashscopeModelList } from "@/hooks/model/useDashscopeModelList";
import { useTokenPonyModelList } from "@/hooks/model/useTokenponyModelList";
import log from "@/lib/logger";
import {
  ModelChunkSizeSlider,
  DEFAULT_EXPECTED_CHUNK_SIZE,
  DEFAULT_MAXIMUM_CHUNK_SIZE,
} from "./ModelChunkSizeSilder";
import {
  isValidMaxTokens,
  ModelMaxTokensInput,
  parseMaxTokens,
} from "./ModelMaxTokensInput";

const { Option } = Select;

// Define the return type after adding a model
export interface AddedModel {
  name: string;
  type: ModelType;
}

interface ModelAddDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (model?: AddedModel) => Promise<void>;
  defaultProvider?: string; // Default provider to select when dialog opens
  defaultIsBatchImport?: boolean;
  tenantId?: string; // Optional tenant ID for manage operations
}

// Default form state for resetting
const DEFAULT_FORM_STATE = {
  type: MODEL_TYPES.LLM as ModelType,
  name: "",
  displayName: "",
  url: "",
  apiKey: "",
  maxTokens: "",
  isMultimodal: false,
  isBatchImport: false,
  provider: "modelengine",
  modelEngineUrl: "",
  vectorDimension: "1024",
  chunkSizeRange: [DEFAULT_EXPECTED_CHUNK_SIZE, DEFAULT_MAXIMUM_CHUNK_SIZE] as [
    number,
    number,
  ],
  chunkingBatchSize: "10",
  // STT specific fields
  sttProvider: "dashscope", // dashscope or volcengine
  modelAppid: "",
  accessToken: "",
  // TTS specific fields
  ttsProvider: "dashscope", // ali or volcengine
};

const resolveConnectivityModelType = (type: ModelType): ModelType =>
  type === MODEL_TYPES.VLM2 || type === MODEL_TYPES.VLM3
    ? (MODEL_TYPES.VLM as ModelType)
    : type;

const resolveConfigKey = (type: ModelType): string => type;

const isVlmConfigType = (type: ModelType): boolean =>
  type === MODEL_TYPES.VLM ||
  type === MODEL_TYPES.VLM2 ||
  type === MODEL_TYPES.VLM3;

const emptyModelConfig = {
  modelName: "",
  displayName: "",
  apiConfig: { apiKey: "", modelUrl: "" },
};

const BATCH_UNSUPPORTED_MODEL_TYPES_BY_PROVIDER: Record<
  string,
  readonly string[]
> = {
  silicon: [MODEL_TYPES.STT, MODEL_TYPES.TTS],
};

const isBatchModelTypeSupported = (
  provider: string,
  type: ModelType
): boolean =>
  !BATCH_UNSUPPORTED_MODEL_TYPES_BY_PROVIDER[provider]?.includes(type);

// Connectivity status type comes from utils

// Helper function to translate error messages from backend
const translateError = (
  errorMessage: string,
  t: (key: string, params?: any) => string
): string => {
  if (!errorMessage) return errorMessage;

  const errorLower = errorMessage.toLowerCase();

  // Extract model name from patterns like "Name 'xxx' is already in use"
  // Matches: "Name 'xxx' is already in use" or "Name xxx is already in use"
  const nameMatch = errorMessage.match(
    /Name\s+(?:['"]([^'"]+)['"]|([^\s,]+))\s+is already in use/i
  );
  if (nameMatch) {
    const modelName = nameMatch[1] || nameMatch[2];
    return t("model.dialog.error.nameAlreadyInUse", { name: modelName });
  }

  // Model not found pattern
  if (
    errorLower.includes("model not found") ||
    errorLower.includes("not found")
  ) {
    const modelNameMatch = errorMessage.match(
      /(?:Model not found|not found)[:\s]+([^\s,]+)/i
    );
    if (modelNameMatch) {
      return t("model.dialog.error.modelNotFound", { name: modelNameMatch[1] });
    }
    return t("model.dialog.error.modelNotFound", { name: "" });
  }

  // Unsupported model type
  if (errorLower.includes("unsupported model type")) {
    const typeMatch = errorMessage.match(
      /unsupported model type[:\s]+([^\s,]+)/i
    );
    if (typeMatch) {
      return t("model.dialog.error.unsupportedModelType", {
        type: typeMatch[1],
      });
    }
    return t("model.dialog.error.unsupportedModelType", { type: "unknown" });
  }

  // Connection failed patterns - extract model name and URL from backend error
  if (
    errorLower.includes("failed to connect") ||
    errorLower.includes("connection failed") ||
    errorLower.includes("connection error") ||
    errorLower.includes("unable to connect")
  ) {
    // Try to extract model name and URL from pattern: "Failed to connect to model 'xxx' at https://..."
    // Match URL that may end with period before the next sentence (e.g., "https://api.example.com. Please verify...")
    // Match URL pattern: http:// or https:// followed by domain (may contain dots) and optional path
    // Example: "Failed to connect to model 'qwen-plus' at https://api.siliconflow.cn. Please verify..."
    const connectMatch = errorMessage.match(
      /Failed to connect to model\s+['"]([^'"]+)['"]\s+at\s+(https?:\/\/[^\s]+?)(?:\.\s|\.$|$)/i
    );
    if (connectMatch) {
      // Remove trailing period if present (URL might end with period before next sentence)
      let url = connectMatch[2].replace(/\.$/, "");
      // Return fully translated message with model name and URL
      return t("model.dialog.error.failedToConnect", {
        modelName: connectMatch[1],
        url: url,
      });
    }
    // Fallback: return original error message (will be wrapped by connectivityFailed)
    return errorMessage;
  }

  // Invalid configuration
  if (errorLower.includes("invalid") && errorLower.includes("config")) {
    // Extract the actual error description
    const configError =
      errorMessage.replace(/^.*?invalid[^:]*:?\s*/i, "").trim() || errorMessage;
    return t("model.dialog.error.invalidConfiguration", { error: configError });
  }

  // ModelEngine specific errors
  if (
    errorLower.includes("authentication failed") ||
    errorLower.includes("invalid api key")
  ) {
    return t("model.dialog.error.apiConnectionFailed");
  }
  if (
    errorLower.includes("access forbidden") ||
    errorLower.includes("insufficient permissions")
  ) {
    return t("model.dialog.error.apiConnectionFailed");
  }
  if (
    errorLower.includes("endpoint not found") ||
    errorLower.includes("url may be incorrect")
  ) {
    return t("model.dialog.error.apiConnectionFailed");
  }
  if (errorLower.includes("server error") || errorLower.includes("http 5")) {
    return t("model.dialog.error.serverError");
  }
  if (
    errorLower.includes("connection failed") ||
    errorLower.includes("network") ||
    errorLower.includes("timeout")
  ) {
    return t("model.dialog.error.apiConnectionFailed");
  }
  if (errorLower.includes("ssl certificate")) {
    return t("model.dialog.error.apiConnectionFailed");
  }

  // Return original error if no pattern matches
  return errorMessage;
};

export const ModelAddDialog = ({
  isOpen,
  onClose,
  onSuccess,
  defaultProvider,
  defaultIsBatchImport,
  tenantId,
}: ModelAddDialogProps) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const {
    modelConfig: currentModelConfig,
    updateModelConfig,
    saveConfig,
  } = useConfig();

  // Parse backend error message and return i18n key with params
  const parseModelError = (
    errorMessage: string
  ): { key: string; params?: Record<string, string> } => {
    if (!errorMessage) {
      return { key: "model.dialog.error.addFailed" };
    }

    // Check for name conflict error
    const nameConflictMatch = errorMessage.match(
      /Name ['"]?([^'"]+)['"]? is already in use/i
    );
    if (nameConflictMatch) {
      return {
        key: "model.dialog.error.nameConflict",
        params: { name: nameConflictMatch[1] },
      };
    }

    // For other errors, return generic error key without showing backend details
    return { key: "model.dialog.error.addFailed" };
  };
  // Form state - initialize with default values
  const [form, setForm] = useState(DEFAULT_FORM_STATE);
  const [loading, setLoading] = useState(false);
  const [verifyingConnectivity, setVerifyingConnectivity] = useState(false);
  const [connectivityStatus, setConnectivityStatus] = useState<{
    status: ConnectivityStatusType;
    message: string;
  }>({
    status: null,
    message: "",
  });

  const [modelList, setModelList] = useState<any[]>([]);
  const [modelSearchTerm, setModelSearchTerm] = useState("");
  const [selectedModelIds, setSelectedModelIds] = useState<Set<string>>(
    new Set()
  );
  const [showModelList, setShowModelList] = useState(false);
  const [loadingModelList, setLoadingModelList] = useState(false);

  const persistModelConfig = useCallback(async () => {
    const ok = await saveConfig();
    if (!ok) {
      message.error(t("setup.page.error.saveConfig"));
    }
  }, [saveConfig, message, t]);

  // Settings modal state
  const [settingsModalVisible, setSettingsModalVisible] = useState(false);
  const [selectedModelForSettings, setSelectedModelForSettings] =
    useState<any>(null);
  const [modelMaxTokens, setModelMaxTokens] = useState("");

  // Use the silicon model list hook
  const siliconHook = useSiliconModelList({
    form,
    setModelList,
    setSelectedModelIds,
    setShowModelList,
    setLoadingModelList,
    tenantId,
  });
  const dashscopeHook = useDashscopeModelList({
    form,
    setModelList,
    setSelectedModelIds,
    setShowModelList,
    setLoadingModelList,
    tenantId,
  });
  const tokenponyHook = useTokenPonyModelList({
    form,
    setModelList,
    setSelectedModelIds,
    setShowModelList,
    setLoadingModelList,
    tenantId,
  });
  let getModelList;
  let getProviderSelectedModalList;

  // Use silicon hook for silicon and modelengine providers (both use the same API pattern)
  if (form.provider === "silicon" || form.provider === "modelengine") {
    ({ getModelList, getProviderSelectedModalList } = siliconHook);
  } else if (form.provider === "dashscope") {
    ({ getModelList, getProviderSelectedModalList } = dashscopeHook);
  } else if (form.provider === "tokenpony") {
    ({ getModelList, getProviderSelectedModalList } = tokenponyHook);
  }
  // Reset form to default state
  const resetForm = useCallback(() => {
    setForm(DEFAULT_FORM_STATE);
    setConnectivityStatus({ status: null, message: "" });
    setModelList([]);
    setModelSearchTerm("");
    setSelectedModelIds(new Set());
    setShowModelList(false);
  }, []);

  // Wrap onClose to reset form before closing
  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [onClose, resetForm]);

  // When dialog opens, apply default provider and optional default batch mode
  useEffect(() => {
    if (!isOpen) return;
    setForm((prev) => ({
      ...prev,
      provider: defaultProvider || prev.provider,
      isBatchImport:
        typeof defaultIsBatchImport !== "undefined"
          ? Boolean(defaultIsBatchImport)
          : prev.isBatchImport,
    }));
  }, [isOpen, defaultProvider, defaultIsBatchImport]);

  // Keep batch import on a provider/type pair that the provider catalog can fetch.
  useEffect(() => {
    if (
      form.isBatchImport &&
      !isBatchModelTypeSupported(form.provider, form.type)
    ) {
      handleFormChange("type", MODEL_TYPES.LLM);
    }
  }, [form.isBatchImport, form.provider, form.type]);

  const parseModelName = (name: string): string => {
    if (!name) return "";
    const parts = name.split("/");
    if (parts.length <= 2) {
      return parts[parts.length - 1];
    } else {
      return `${parts[0]}/${parts[parts.length - 1]}`;
    }
  };

  const filteredModelList = useMemo(() => {
    const keyword = modelSearchTerm.trim().toLowerCase();
    if (!keyword) {
      return modelList;
    }
    return modelList.filter((model: any) => {
      const candidates = [
        model.id,
        model.model_name,
        model.model_tag,
        model.description,
      ];
      return candidates.some(
        (text) =>
          typeof text === "string" && text.toLowerCase().includes(keyword)
      );
    });
  }, [modelList, modelSearchTerm]);

  // Handle model name change, automatically update the display name
  const handleModelNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value;
    setForm((prev) => ({
      ...prev,
      name,
      // If the display name is the same as the parsed result of the model name, it means the user has not manually modified the display name
      // At this time, the display name should be automatically updated
      displayName:
        prev.displayName === parseModelName(prev.name)
          ? parseModelName(name)
          : prev.displayName,
    }));
    // Clear the previous verification status
    setConnectivityStatus({ status: null, message: "" });
  };

  // Handle form change
  const handleFormChange = (field: string, value: string | boolean) => {
    setForm((prev) => ({
      ...prev,
      [field]: value,
      // When provider changes, clear provider-related fields
      ...(field === "provider"
        ? {
            url: "",
            apiKey: "",
            modelEngineUrl: "",
          }
        : {}),
    }));
    // If the key configuration item changes, clear the verification status
    if (
      ["type", "url", "apiKey", "maxTokens", "vectorDimension"].includes(
        field
      ) ||
      field === "provider"
    ) {
      setConnectivityStatus({ status: null, message: "" });
    }
    // Clear model search term when model type changes
    if (field === "type") {
      setModelSearchTerm("");
    }
    // Clear model list when provider changes
    if (field === "provider") {
      setModelList([]);
      setSelectedModelIds(new Set());
    }
  };

  // Verify if the vector dimension is valid
  const isValidVectorDimension = (value: string): boolean => {
    const dimension = Number.parseInt(value, 10);
    return !isNaN(dimension) && dimension > 0;
  };

  // Check if the form is valid
  const isFormValid = () => {
    const needsMaxTokens =
      form.type !== MODEL_TYPES.EMBEDDING &&
      form.type !== MODEL_TYPES.MULTI_EMBEDDING &&
      form.type !== MODEL_TYPES.STT;

    if (form.isBatchImport) {
      if (needsMaxTokens && !isValidMaxTokens(form.maxTokens)) {
        return false;
      }
      // If provider is ModelEngine, require the ModelEngine URL as well.
      if (form.provider === "modelengine") {
        return (
          form.provider.trim() !== "" &&
          form.apiKey.trim() !== "" &&
          ((form as any).modelEngineUrl || "").toString().trim() !== ""
        );
      }
      return form.provider.trim() !== "" && form.apiKey.trim() !== "";
    }
    if (needsMaxTokens && !isValidMaxTokens(form.maxTokens)) {
      return false;
    }
    if (form.type === MODEL_TYPES.EMBEDDING) {
      return (
        form.name.trim() !== "" &&
        form.url.trim() !== "" &&
        isValidVectorDimension(form.vectorDimension)
      );
    }
    if (form.type === MODEL_TYPES.RERANK) {
      return (
        form.name.trim() !== "" &&
        form.url.trim() !== "" &&
        form.apiKey.trim() !== ""
      );
    }
    if (form.type === MODEL_TYPES.STT) {
      // For STT models, validate based on provider type
      if (form.sttProvider === "volcengine") {
        // Volcano Engine requires appid and access_token
        return form.modelAppid.trim() !== "" && form.accessToken.trim() !== "";
      } else {
        // DashScope requires API Key and model name
        return form.apiKey.trim() !== "" && form.name.trim() !== "";
      }
    }
    if (form.type === MODEL_TYPES.TTS) {
      // For TTS models, validate based on provider type
      if (form.ttsProvider === "volcengine") {
        // Volcano Engine requires appid and access_token
        return form.modelAppid.trim() !== "" && form.accessToken.trim() !== "";
      } else {
        // Ali TTS requires API Key and model name (URL is optional)
        return form.apiKey.trim() !== "" && form.name.trim() !== "";
      }
    }
    return (
      form.name.trim() !== "" &&
      form.url.trim() !== "" &&
      isValidMaxTokens(form.maxTokens)
    );
  };

  // Verify model connectivity
  const handleVerifyConnectivity = async () => {
    if (!isFormValid()) {
      message.warning(t("model.dialog.warning.incompleteForm"));
      return;
    }

    setVerifyingConnectivity(true);
    setConnectivityStatus({
      status: "checking",
      message: t("model.dialog.status.verifying"),
    });

    try {
      const modelType =
        form.type === MODEL_TYPES.EMBEDDING && form.isMultimodal
          ? (MODEL_TYPES.MULTI_EMBEDDING as ModelType)
          : resolveConnectivityModelType(form.type);

      let connectivity = false;

      // Use manage interface if tenantId is provided
      if (tenantId) {
        connectivity = await modelService.checkManageTenantModelConnectivity(
          tenantId,
          form.displayName || form.name,
          modelType
        );
      } else if (form.type === MODEL_TYPES.STT) {
        // For STT models, build the appropriate config based on provider
        const sttConfig: any = {
          modelType: modelType,
          baseUrl: form.url,
        };

        if (form.sttProvider === "volcengine") {
          sttConfig.modelFactory = "volcengine";
          sttConfig.modelAppid = form.modelAppid.trim();
          sttConfig.accessToken = form.accessToken.trim();
        } else {
          sttConfig.apiKey = form.apiKey.trim() || "sk-no-api-key";
          sttConfig.modelFactory = "dashscope";
          sttConfig.modelName = form.name;
        }

        const result =
          await modelService.verifyModelConfigConnectivity(sttConfig);
        connectivity = result.connectivity;
      } else if (form.type === MODEL_TYPES.TTS) {
        // For TTS models, build the appropriate config based on provider
        const ttsConfig: any = {
          modelType: modelType,
          baseUrl: form.url,
        };

        if (form.ttsProvider === "volcengine") {
          ttsConfig.modelFactory = "volcengine";
          ttsConfig.modelAppid = form.modelAppid.trim();
          ttsConfig.accessToken = form.accessToken.trim();
        } else {
          ttsConfig.apiKey = form.apiKey.trim() || "sk-no-api-key";
          ttsConfig.modelFactory = "dashscope";
          ttsConfig.modelName = form.name;
        }

        const result =
          await modelService.verifyModelConfigConnectivity(ttsConfig);
        connectivity = result.connectivity;
      } else {
        // For other model types (LLM, Embedding, VLM, Rerank, etc.)
        const config = {
          modelName: form.name,
          modelType: modelType,
          baseUrl: form.url,
          apiKey: form.apiKey.trim() || "sk-no-api-key",
          maxTokens:
            form.type === MODEL_TYPES.EMBEDDING
              ? Number.parseInt(form.vectorDimension, 10)
              : parseMaxTokens(form.maxTokens),
          embeddingDim:
            form.type === MODEL_TYPES.EMBEDDING
              ? Number.parseInt(form.vectorDimension, 10)
              : undefined,
        };

        const result = await modelService.verifyModelConfigConnectivity(config);
        connectivity = result.connectivity;
      }

      // Set connectivity status
      if (connectivity) {
        setConnectivityStatus({
          status: "available",
          message: t("model.dialog.connectivity.status.available"),
        });
      } else {
        setConnectivityStatus({
          status: "unavailable",
          message: t("model.dialog.connectivity.status.unavailable"),
        });
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      setConnectivityStatus({
        status: "unavailable",
        message: t("model.dialog.connectivity.status.unavailable"),
      });
      const translatedError = translateError(errorMessage, t);
      const errorText =
        translatedError && translatedError.length > 0
          ? translatedError
          : errorMessage;
      message.error(
        t("model.dialog.error.connectivityFailed", { error: errorText })
      );
    } finally {
      setVerifyingConnectivity(false);
    }
  };

  const getResolvedModelType = (): ModelType =>
    form.type === MODEL_TYPES.EMBEDDING && form.isMultimodal
      ? (MODEL_TYPES.MULTI_EMBEDDING as ModelType)
      : form.type;

  const getApiKeyOrPlaceholder = () =>
    form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey;

  const getChunkingBatchSize = () =>
    Number.parseInt(form.chunkingBatchSize, 10) || 10;

  const buildEmbeddingBatchModelData = (model: any) => {
    const { max_tokens, ...modelWithoutMaxTokens } = model;
    return {
      ...modelWithoutMaxTokens,
      ...(isEmbeddingModel
        ? {
            expected_chunk_size: form.chunkSizeRange[0],
            maximum_chunk_size: form.chunkSizeRange[1],
            chunk_batch: getChunkingBatchSize(),
          }
        : {}),
    };
  };

  const buildBatchModelData = (model: any, modelType: ModelType) => {
    const isEmbeddingType =
      modelType === MODEL_TYPES.EMBEDDING ||
      modelType === MODEL_TYPES.MULTI_EMBEDDING;

    if (isEmbeddingType) {
      // Backend sets max_tokens for embedding models during connectivity checks.
      return buildEmbeddingBatchModelData(model);
    }

    if (modelType === MODEL_TYPES.STT) {
      const { max_tokens, ...modelWithoutMaxTokens } = model;
      return modelWithoutMaxTokens;
    }

    return {
      ...model,
      max_tokens: model.max_tokens ?? parseMaxTokens(form.maxTokens),
    };
  };

  const createBatchModels = async (modelType: ModelType, modelsData: any[]) => {
    // Use manage interface if tenantId is provided (for super admin), otherwise use current tenant.
    if (tenantId) {
      await modelService.batchCreateManageTenantModels({
        tenantId,
        provider: form.provider,
        type: modelType,
        apiKey: getApiKeyOrPlaceholder(),
        models: modelsData,
      });
      return;
    }

    await modelService.addBatchCustomModel({
      api_key: getApiKeyOrPlaceholder(),
      provider: form.provider,
      type: modelType,
      models: modelsData,
    });
  };

  const persistBatchVlmConfig = async (enabledModels: any[]) => {
    if (!isVlmConfigType(form.type) || enabledModels.length === 0) {
      return;
    }

    const selectedModel = enabledModels[0];
    const selectedDisplayName =
      selectedModel.displayName || selectedModel.id || "";
    const configKey = resolveConfigKey(form.type);
    const vlmConfigUpdate: any = {
      [configKey]: {
        modelName: selectedModel.id || selectedModel.model_name || "",
        displayName: selectedDisplayName,
        apiConfig: {
          apiKey: form.apiKey,
          modelUrl: "",
        },
      },
    };

    for (const key of [MODEL_TYPES.VLM, MODEL_TYPES.VLM2, MODEL_TYPES.VLM3]) {
      if (
        key !== configKey &&
        currentModelConfig?.[key]?.displayName === selectedDisplayName
      ) {
        vlmConfigUpdate[key] = emptyModelConfig;
      }
    }

    updateModelConfig(vlmConfigUpdate);
    await persistModelConfig();
  };

  // Handle batch adding models
  const handleBatchAddModel = async () => {
    // Only include models whose id is in selectedModelIds (i.e., switch is ON)
    const enabledModels = modelList.filter((model: any) =>
      selectedModelIds.has(model.id)
    );
    const modelType = getResolvedModelType();

    try {
      const modelsData = enabledModels.map((model: any) =>
        buildBatchModelData(model, modelType)
      );

      await createBatchModels(modelType, modelsData);
      await persistBatchVlmConfig(enabledModels);

      // Reset form state and close dialog on success
      resetForm();
      handleClose();

      // Notify parent to refresh model list - batch add returns all added models
      const addedModels: AddedModel[] = enabledModels.map((model: any) => ({
        name: model.displayName || model.id,
        type: modelType,
      }));
      await onSuccess(addedModels.length > 0 ? addedModels[0] : undefined);
    } catch (error: any) {
      const errorMessage =
        error?.message || t("model.dialog.error.addFailedLog");
      const translatedError = translateError(errorMessage, t);
      message.error(
        t("model.dialog.error.addFailed", { error: translatedError })
      );
    }
  };

  // Handle settings button click
  const handleSettingsClick = (model: any) => {
    setSelectedModelForSettings(model);
    setModelMaxTokens(model.max_tokens?.toString() || "");
    setSettingsModalVisible(true);
  };

  // Handle settings save
  const handleSettingsSave = () => {
    const nextMaxTokens = parseMaxTokens(modelMaxTokens);
    if (!nextMaxTokens) return;

    if (selectedModelForSettings) {
      // Update the model in the list with new max_tokens
      setModelList((prev) =>
        prev.map((model) =>
          model.id === selectedModelForSettings.id
            ? { ...model, max_tokens: nextMaxTokens }
            : model
        )
      );
    }
    setSettingsModalVisible(false);
    setSelectedModelForSettings(null);
  };

  // Handle adding a model
  const handleAddModel = async () => {
    // Check connectivity status before adding
    if (!form.isBatchImport && connectivityStatus.status !== "available") {
      message.warning(t("model.dialog.error.connectivityRequired"));
      return;
    }

    setLoading(true);
    if (form.isBatchImport) {
      await handleBatchAddModel();
      setLoading(false);
      return;
    }
    try {
      const modelType =
        form.type === MODEL_TYPES.EMBEDDING && form.isMultimodal
          ? (MODEL_TYPES.MULTI_EMBEDDING as ModelType)
          : form.type;

      // Determine the maximum tokens value
      let maxTokensValue = parseMaxTokens(form.maxTokens) || 0;
      if (
        form.type === MODEL_TYPES.EMBEDDING ||
        form.type === MODEL_TYPES.MULTI_EMBEDDING
      ) {
        // For embedding models, use the vector dimension as maxTokens
        maxTokensValue = 0;
      }

      // Add to the backend service - use manage interface if tenantId is provided
      if (tenantId) {
        const modelParams: any = {
          tenantId,
          name: form.name,
          type: modelType,
          url: form.url,
          apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          maxTokens: maxTokensValue,
          displayName: form.displayName || form.name,
        };

        // Add STT specific fields
        if (form.type === MODEL_TYPES.STT) {
          modelParams.modelFactory =
            form.sttProvider === "volcengine" ? "volcengine" : "dashscope";
          if (form.sttProvider === "volcengine") {
            modelParams.modelAppid = form.modelAppid;
            modelParams.accessToken = form.accessToken;
          }
        }

        // Add TTS specific fields
        if (form.type === MODEL_TYPES.TTS) {
          modelParams.modelFactory =
            form.ttsProvider === "volcengine" ? "volcengine" : "dashscope";
          if (form.ttsProvider === "volcengine") {
            modelParams.modelAppid = form.modelAppid;
            modelParams.accessToken = form.accessToken;
            modelParams.baseUrl = form.url;
          }
        }

        // Add embedding specific fields
        if (isEmbeddingModel) {
          modelParams.expectedChunkSize = form.chunkSizeRange[0];
          modelParams.maximumChunkSize = form.chunkSizeRange[1];
          modelParams.chunkingBatchSize =
            Number.parseInt(form.chunkingBatchSize, 10) || 10;
        }

        await modelService.createManageTenantModel(modelParams);
      } else {
        const modelParams: any = {
          name: form.name,
          type: modelType,
          url: form.url,
          apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          maxTokens: maxTokensValue,
          displayName: form.displayName || form.name,
        };

        // Add STT specific fields
        if (form.type === MODEL_TYPES.STT) {
          modelParams.modelFactory =
            form.sttProvider === "volcengine" ? "volcengine" : "dashscope";
          if (form.sttProvider === "volcengine") {
            modelParams.modelAppid = form.modelAppid;
            modelParams.accessToken = form.accessToken;
          }
        }

        // Add TTS specific fields
        if (form.type === MODEL_TYPES.TTS) {
          modelParams.modelFactory =
            form.ttsProvider === "volcengine" ? "volcengine" : "dashscope";
          if (form.ttsProvider === "volcengine") {
            modelParams.modelAppid = form.modelAppid;
            modelParams.accessToken = form.accessToken;
            modelParams.baseUrl = form.url;
          }
        }

        // Add embedding specific fields
        if (isEmbeddingModel) {
          modelParams.expectedChunkSize = form.chunkSizeRange[0];
          modelParams.maximumChunkSize = form.chunkSizeRange[1];
          modelParams.chunkingBatchSize =
            Number.parseInt(form.chunkingBatchSize, 10) || 10;
        }

        await modelService.addCustomModel(modelParams);
      }

      // Create the model configuration object
      // Note: id is set to 0 as placeholder; backend assigns the actual id when saving
      let modelConfig: SingleModelConfig | STTModelConfig | TTSModelConfig = {
        id: 0,
        modelName: form.name,
        displayName: form.displayName || form.name,
        apiConfig: {
          apiKey: form.apiKey,
          modelUrl: form.url,
        },
      };

      // Add STT specific fields to config
      if (form.type === MODEL_TYPES.STT) {
        (modelConfig as STTModelConfig).modelFactory =
          form.sttProvider === "volcengine" ? "volcengine" : "dashscope";
        if (form.sttProvider === "volcengine") {
          (modelConfig as STTModelConfig).modelAppid = form.modelAppid;
          (modelConfig as STTModelConfig).accessToken = form.accessToken;
        }
      }

      // Add TTS specific fields to config
      if (form.type === MODEL_TYPES.TTS) {
        (modelConfig as TTSModelConfig).modelFactory =
          form.ttsProvider === "volcengine" ? "volcengine" : "dashscope";
        if (form.ttsProvider === "volcengine") {
          (modelConfig as TTSModelConfig).modelAppid = form.modelAppid;
          (modelConfig as TTSModelConfig).accessToken = form.accessToken;
        }
      }

      // Add the dimension field for embedding models
      if (form.type === MODEL_TYPES.EMBEDDING) {
        modelConfig.dimension = Number.parseInt(form.vectorDimension, 10);
      }

      // Update the local storage according to the model type
      let configUpdate: any = {};
      const configKey = resolveConfigKey(form.type);

      switch (modelType) {
        case MODEL_TYPES.LLM:
          configUpdate = { llm: modelConfig };
          break;
        case MODEL_TYPES.EMBEDDING:
          configUpdate = { embedding: modelConfig };
          break;
        case MODEL_TYPES.MULTI_EMBEDDING:
          configUpdate = { multiEmbedding: modelConfig };
          break;
        case MODEL_TYPES.VLM:
        case MODEL_TYPES.VLM2:
        case MODEL_TYPES.VLM3:
          configUpdate = { [configKey]: modelConfig };
          for (const key of [
            MODEL_TYPES.VLM,
            MODEL_TYPES.VLM2,
            MODEL_TYPES.VLM3,
          ]) {
            if (
              key !== configKey &&
              currentModelConfig?.[key]?.displayName === modelConfig.displayName
            ) {
              configUpdate[key] = emptyModelConfig;
            }
          }
          break;
        case MODEL_TYPES.RERANK:
          configUpdate = { rerank: modelConfig };
          break;
        case MODEL_TYPES.TTS:
          configUpdate = { tts: modelConfig };
          break;
        case MODEL_TYPES.STT:
          configUpdate = { stt: modelConfig };
          break;
      }

      // Save to localStorage and persist to backend
      updateModelConfig(configUpdate);
      await persistModelConfig();

      // Create the returned model information
      const addedModel: AddedModel = {
        name: form.displayName,
        type: modelType,
      };

      // Reset form state
      resetForm();

      // Call the success callback, pass the new added model information
      await onSuccess(addedModel);

      // Close the dialog
      handleClose();
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      const translatedError = translateError(errorMessage, t);
      message.error(
        t("model.dialog.error.addFailed", { error: translatedError })
      );
      log.error(t("model.dialog.error.addFailedLog"), error);
    } finally {
      setLoading(false);
    }
  };

  const isEmbeddingModel = form.type === MODEL_TYPES.EMBEDDING;
  const isSTTModel = form.type === MODEL_TYPES.STT;
  const isTTSModel = form.type === MODEL_TYPES.TTS;

  return (
    <Modal
      title={t("model.dialog.title")}
      open={isOpen}
      onCancel={handleClose}
      footer={null}
      destroyOnHidden
    >
      <div className="space-y-4">
        {/* Batch Import Switch */}
        <div>
          <div className="flex justify-between items-center">
            <label className="block text-sm font-medium text-gray-700">
              {t("model.dialog.label.batchImport")}
            </label>
            <Switch
              checked={form.isBatchImport}
              onChange={(checked) => handleFormChange("isBatchImport", checked)}
            />
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {form.isBatchImport
              ? t("model.dialog.hint.batchImportEnabled")
              : t("model.dialog.hint.batchImportDisabled")}
          </div>
        </div>

        {/* Model Provider (shown only when batch import is enabled) */}
        {form.isBatchImport && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.provider")}
              <span className="text-red-500">*</span>
            </label>
            <Select
              style={{ width: "100%" }}
              value={form.provider}
              onChange={(value) => handleFormChange("provider", value)}
            >
              <Option value="modelengine">
                {t("model.provider.modelengine")}
              </Option>
              <Option value="silicon">{t("model.provider.silicon")}</Option>
              <Option value="dashscope">{t("model.provider.dashscope")}</Option>
              <Option value="tokenpony">{t("model.provider.tokenpony")}</Option>
            </Select>
            {/* ModelEngine URL input (only when provider is ModelEngine) */}
            {form.provider === "modelengine" && (
              <div className="mt-3">
                <label className="block mb-1 text-sm font-medium text-gray-700">
                  ModelEngine URL
                </label>
                <Input
                  placeholder={t("model.dialog.placeholder.modelEngineUrl")}
                  value={(form as any).modelEngineUrl}
                  onChange={(e) =>
                    handleFormChange("modelEngineUrl", e.target.value)
                  }
                />
              </div>
            )}
          </div>
        )}

        {/* API Key (shown only when batch import is enabled) */}
        {form.isBatchImport && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.apiKey")}
              <span className="text-red-500">*</span>
            </label>
            <Input.Password
              placeholder={t("model.dialog.placeholder.apiKey")}
              value={form.apiKey}
              onChange={(e) => handleFormChange("apiKey", e.target.value)}
              autoComplete="new-password"
            />
          </div>
        )}

        {/* Model Type */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.type")}{" "}
            <span className="text-red-500">*</span>
          </label>
          <Select
            style={{ width: "100%" }}
            value={form.type}
            onChange={(value) => handleFormChange("type", value)}
          >
            <Option value={MODEL_TYPES.LLM}>{t("model.type.llm")}</Option>
            <Option value={MODEL_TYPES.EMBEDDING}>
              {t("model.type.embedding")}
            </Option>
            <Option value={MODEL_TYPES.VLM}>
              {t("model.type.imageUnderstanding")}
            </Option>
            <Option value={MODEL_TYPES.VLM2}>
              {t("model.type.imageGeneration")}
            </Option>
            <Option value={MODEL_TYPES.VLM3}>
              {t("model.type.videoUnderstanding")}
            </Option>
            <Option value={MODEL_TYPES.RERANK}>{t("model.type.rerank")}</Option>
            <Option
              value={MODEL_TYPES.STT}
              disabled={
                form.isBatchImport &&
                !isBatchModelTypeSupported(form.provider, MODEL_TYPES.STT)
              }
            >
              {t("model.type.stt")}
            </Option>
            <Option
              value={MODEL_TYPES.TTS}
              disabled={
                form.isBatchImport &&
                !isBatchModelTypeSupported(form.provider, MODEL_TYPES.TTS)
              }
            >
              {t("model.type.tts")}
            </Option>
          </Select>
        </div>

        {/* Multimodal Switch */}
        {isEmbeddingModel && !form.isBatchImport && (
          <div>
            <div className="flex justify-between items-center">
              <label className="block text-sm font-medium text-gray-700">
                {t("model.dialog.label.multimodal")}
              </label>
              <Switch
                checked={form.isMultimodal}
                onChange={(checked) =>
                  handleFormChange("isMultimodal", checked)
                }
              />
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {form.isMultimodal
                ? t("model.dialog.hint.multimodalEnabled")
                : t("model.dialog.hint.multimodalDisabled")}
            </div>
          </div>
        )}

        {/* Model Name */}
        {!form.isBatchImport && (
          <div>
            <label
              htmlFor="name"
              className="block mb-1 text-sm font-medium text-gray-700"
            >
              {t("model.dialog.label.name")}{" "}
              <span className="text-red-500">*</span>
            </label>
            <Input
              id="name"
              placeholder={t("model.dialog.placeholder.name")}
              value={form.name}
              onChange={handleModelNameChange}
            />
          </div>
        )}

        {/* Display Name */}
        {!form.isBatchImport && (
          <div>
            <label
              htmlFor="displayName"
              className="block mb-1 text-sm font-medium text-gray-700"
            >
              {t("model.dialog.label.displayName")}
            </label>
            <Input
              id="displayName"
              placeholder={t("model.dialog.placeholder.displayName")}
              value={form.displayName}
              onChange={(e) => handleFormChange("displayName", e.target.value)}
            />
          </div>
        )}

        {/* Model URL */}
        {!form.isBatchImport && (
          <div>
            <label
              htmlFor="url"
              className="block mb-1 text-sm font-medium text-gray-700"
            >
              {t("model.dialog.label.url")}{" "}
              <span className="text-red-500">*</span>
            </label>
            <Input
              id="url"
              placeholder={
                form.type === MODEL_TYPES.EMBEDDING
                  ? t("model.dialog.placeholder.url.embedding")
                  : form.type === MODEL_TYPES.STT
                    ? t("model.dialog.placeholder.url.stt")
                    : form.type === MODEL_TYPES.TTS
                      ? t("model.dialog.placeholder.url.tts")
                      : t("model.dialog.placeholder.url")
              }
              value={form.url}
              onChange={(e) => handleFormChange("url", e.target.value)}
            />
          </div>
        )}

        {/* STT Provider Selection */}
        {!form.isBatchImport && isSTTModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.sttProvider")}
              <span className="text-red-500">*</span>
            </label>
            <Select
              style={{ width: "100%" }}
              value={form.sttProvider}
              onChange={(value) => handleFormChange("sttProvider", value)}
            >
              <Option value="dashscope">{t("model.provider.dashscope")}</Option>
              <Option value="volcengine">
                {t("model.provider.volcengine")}
              </Option>
            </Select>
          </div>
        )}

        {/* STT Fields for Volcano Engine */}
        {!form.isBatchImport &&
          isSTTModel &&
          form.sttProvider === "volcengine" && (
            <>
              <div>
                <label
                  htmlFor="modelAppid"
                  className="block mb-1 text-sm font-medium text-gray-700"
                >
                  {t("model.dialog.label.modelAppid")}
                  <span className="text-red-500">*</span>
                </label>
                <Input
                  id="modelAppid"
                  placeholder={t("model.dialog.placeholder.modelAppid")}
                  value={form.modelAppid}
                  onChange={(e) =>
                    handleFormChange("modelAppid", e.target.value)
                  }
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label
                  htmlFor="accessToken"
                  className="block mb-1 text-sm font-medium text-gray-700"
                >
                  {t("model.dialog.label.accessToken")}
                  <span className="text-red-500">*</span>
                </label>
                <Input.Password
                  id="accessToken"
                  placeholder={t("model.dialog.placeholder.accessToken")}
                  value={form.accessToken}
                  onChange={(e) =>
                    handleFormChange("accessToken", e.target.value)
                  }
                  autoComplete="new-password"
                />
              </div>
            </>
          )}

        {/* API Key (for DashScope STT) */}
        {!form.isBatchImport &&
          isSTTModel &&
          form.sttProvider === "dashscope" && (
            <div>
              <label
                htmlFor="apiKey"
                className="block mb-1 text-sm font-medium text-gray-700"
              >
                {t("model.dialog.label.apiKey")}{" "}
                <span className="text-red-500">*</span>
              </label>
              <Input.Password
                id="apiKey"
                placeholder={t("model.dialog.placeholder.apiKey")}
                value={form.apiKey}
                onChange={(e) => handleFormChange("apiKey", e.target.value)}
                autoComplete="new-password"
              />
            </div>
          )}

        {/* TTS Provider Selection */}
        {!form.isBatchImport && isTTSModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.ttsProvider")}
              <span className="text-red-500">*</span>
            </label>
            <Select
              style={{ width: "100%" }}
              value={form.ttsProvider}
              onChange={(value) => handleFormChange("ttsProvider", value)}
            >
              <Option value="dashscope">{t("model.provider.dashscope")}</Option>
              <Option value="volcengine">
                {t("model.provider.volcengine")}
              </Option>
            </Select>
          </div>
        )}

        {/* TTS Fields for Volcano Engine */}
        {!form.isBatchImport &&
          isTTSModel &&
          form.ttsProvider === "volcengine" && (
            <>
              <div>
                <label
                  htmlFor="modelAppid"
                  className="block mb-1 text-sm font-medium text-gray-700"
                >
                  {t("model.dialog.label.modelAppid")}
                  <span className="text-red-500">*</span>
                </label>
                <Input
                  id="modelAppid"
                  placeholder={t("model.dialog.placeholder.modelAppid")}
                  value={form.modelAppid}
                  onChange={(e) =>
                    handleFormChange("modelAppid", e.target.value)
                  }
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label
                  htmlFor="accessToken"
                  className="block mb-1 text-sm font-medium text-gray-700"
                >
                  {t("model.dialog.label.accessToken")}
                  <span className="text-red-500">*</span>
                </label>
                <Input.Password
                  id="accessToken"
                  placeholder={t("model.dialog.placeholder.accessToken")}
                  value={form.accessToken}
                  onChange={(e) =>
                    handleFormChange("accessToken", e.target.value)
                  }
                  autoComplete="new-password"
                />
              </div>
            </>
          )}

        {/* API Key (for Ali TTS) */}
        {!form.isBatchImport &&
          isTTSModel &&
          form.ttsProvider === "dashscope" && (
            <div>
              <label
                htmlFor="apiKey"
                className="block mb-1 text-sm font-medium text-gray-700"
              >
                {t("model.dialog.label.apiKey")}{" "}
                <span className="text-red-500">*</span>
              </label>
              <Input.Password
                id="apiKey"
                placeholder={t("model.dialog.placeholder.apiKey")}
                value={form.apiKey}
                onChange={(e) => handleFormChange("apiKey", e.target.value)}
                autoComplete="new-password"
              />
            </div>
          )}

        {/* API Key (for non-STT, non-TTS models) */}
        {!form.isBatchImport && !isSTTModel && !isTTSModel && (
          <div>
            <label
              htmlFor="apiKey"
              className="block mb-1 text-sm font-medium text-gray-700"
            >
              {t("model.dialog.label.apiKey")}{" "}
              {form.isBatchImport && <span className="text-red-500">*</span>}
            </label>
            <Input.Password
              id="apiKey"
              placeholder={t("model.dialog.placeholder.apiKey")}
              value={form.apiKey}
              onChange={(e) => handleFormChange("apiKey", e.target.value)}
              autoComplete="new-password"
            />
          </div>
        )}

        {/* Chunk Size Slider (Embedding model only) */}
        {isEmbeddingModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("modelConfig.slider.chunkingSize")}
            </label>
            <ModelChunkSizeSlider
              value={form.chunkSizeRange}
              onChange={(value) => {
                setForm((prev) => ({
                  ...prev,
                  chunkSizeRange: value,
                }));
              }}
            />
          </div>
        )}

        {/* Concurrent Request Count (Embedding model only) */}
        {isEmbeddingModel && (
          <div>
            <label
              htmlFor="chunkingBatchSize"
              className="block mb-1 text-sm font-medium text-gray-700"
            >
              {t("modelConfig.input.chunkingBatchSize")}
            </label>
            <Input
              id="chunkingBatchSize"
              type="number"
              min="1"
              placeholder="10"
              value={form.chunkingBatchSize}
              onChange={(e) =>
                handleFormChange("chunkingBatchSize", e.target.value)
              }
            />
          </div>
        )}

        {/* Vector dimension */}
        {isEmbeddingModel && (
          <div>
            <label
              htmlFor="vectorDimension"
              className="block mb-1 text-sm font-medium text-gray-700"
            ></label>
          </div>
        )}

        {/* Max Tokens */}
        {!isEmbeddingModel && !isSTTModel && (
          <div>
            <label
              htmlFor="maxTokens"
              className="block mb-1 text-sm font-medium text-gray-700"
            >
              {t("model.dialog.label.maxTokens")}{" "}
              <span className="text-red-500">*</span>
            </label>
            <ModelMaxTokensInput
              id="maxTokens"
              placeholder={t("model.dialog.placeholder.maxTokens")}
              value={form.maxTokens}
              onChange={(value) => handleFormChange("maxTokens", value)}
            />
          </div>
        )}

        {/* Connectivity verification area */}
        {!form.isBatchImport && (
          <div className="p-3 bg-gray-50 border border-gray-200 rounded-md">
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <span className="text-sm font-medium text-gray-700">
                  {t("model.dialog.connectivity.title")}
                </span>
                {connectivityStatus.status && (
                  <div className="ml-2 flex items-center">
                    {getConnectivityMeta(connectivityStatus.status).icon}
                    <span
                      className="ml-1 text-xs"
                      style={{
                        color: getConnectivityMeta(connectivityStatus.status)
                          .color,
                      }}
                    >
                      {connectivityStatus.status === "available" &&
                        t("model.dialog.connectivity.status.available")}
                      {connectivityStatus.status === "unavailable" &&
                        t("model.dialog.connectivity.status.unavailable")}
                      {connectivityStatus.status === "checking" &&
                        t("model.dialog.status.verifying")}
                    </span>
                  </div>
                )}
              </div>
              <Button
                size="small"
                type="default"
                onClick={handleVerifyConnectivity}
                disabled={!isFormValid() || verifyingConnectivity}
              >
                {verifyingConnectivity
                  ? t("model.dialog.button.verifying")
                  : t("model.dialog.button.verify")}
              </Button>
            </div>
          </div>
        )}

        {/* Model List */}
        {form.isBatchImport && (
          <div className="p-3 bg-gray-50 border border-gray-200 rounded-md">
            <div className="flex items-center justify-between mb-1">
              <button
                type="button"
                onClick={() => setShowModelList(!showModelList)}
                className="flex items-center focus:outline-none"
              >
                {showModelList ? (
                  <ChevronDown
                    className="text-sm text-gray-700 mr-1"
                    size={14}
                  />
                ) : (
                  <ChevronRight
                    className="text-sm text-gray-700 mr-1"
                    size={14}
                  />
                )}
                <span className="text-sm font-medium text-gray-700">
                  {t("model.dialog.modelList.title")}
                </span>
              </button>
              <Button
                size="small"
                type="default"
                onClick={getModelList}
                disabled={!isFormValid() || loadingModelList}
              >
                {loadingModelList
                  ? t("common.loading")
                  : t("model.dialog.button.modelList")}
              </Button>
            </div>
            {showModelList && (
              <div className="mt-2 max-h-60 overflow-y-auto">
                {modelList.length > 0 && (
                  <div className="sticky top-0 z-10 bg-gray-50 pb-2">
                    <Input
                      allowClear
                      size="small"
                      placeholder={t(
                        "model.dialog.modelList.searchPlaceholder"
                      )}
                      value={modelSearchTerm}
                      onChange={(event) =>
                        setModelSearchTerm(event.target.value)
                      }
                    />
                  </div>
                )}
                {loadingModelList ? (
                  <div className="flex flex-col items-center justify-center py-4 text-xs text-gray-500">
                    <LoaderCircle
                      className="animate-spin"
                      style={{
                        fontSize: 18,
                        color: "#1890ff",
                        marginBottom: 4,
                      }}
                    />
                    <span>{t("common.loading") || "获取中..."}</span>
                  </div>
                ) : modelList.length === 0 ? (
                  <div className="text-xs text-gray-500 text-center space-y-1">
                    <div>{t("model.dialog.message.noModels")}</div>
                  </div>
                ) : filteredModelList.length === 0 ? (
                  <div className="text-xs text-gray-500 text-center">
                    {t("model.dialog.modelList.noResults")}
                  </div>
                ) : (
                  filteredModelList.map((model: any) => {
                    const checked = selectedModelIds.has(model.id);
                    const toggleSelect = (value: boolean) => {
                      setSelectedModelIds((prev) => {
                        const next = new Set(prev);
                        if (value) {
                          next.add(model.id);
                        } else {
                          next.delete(model.id);
                        }
                        return next;
                      });
                    };
                    return (
                      <div
                        key={model.id}
                        className="p-2 flex justify-between items-center rounded hover:bg-gray-100 text-sm border border-transparent"
                      >
                        <div className="flex items-center min-w-0">
                          <span className="truncate" title={model.id}>
                            {model.id}
                          </span>
                          {model.model_type && (
                            <span className="ml-2 px-1.5 py-0.5 text-xs rounded bg-gray-200 text-gray-600 uppercase">
                              {String(model.model_tag)}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center space-x-2">
                          {!isEmbeddingModel && !isSTTModel && (
                            <Tooltip
                              title={t(
                                "model.dialog.modelList.tooltip.settings"
                              )}
                            >
                              <Button
                                type="text"
                                icon={<Settings size={14} />}
                                size="small"
                                onClick={(e) => {
                                  e.stopPropagation(); // Prevent switch toggle
                                  handleSettingsClick(model);
                                }}
                              />
                            </Tooltip>
                          )}
                          <Switch
                            size="small"
                            checked={checked}
                            onChange={toggleSelect}
                          />
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}
            {connectivityStatus.message && !showModelList && (
              <div className="text-xs text-gray-600">
                {connectivityStatus.message}
              </div>
            )}
          </div>
        )}

        {/* Help Text */}
        <div className="p-3 bg-blue-50 border border-blue-100 rounded-md text-xs text-blue-700">
          <div>
            <div className="flex items-center mb-1">
              <InfoCircleFilled className="text-md text-blue-500 mr-3" />
              <p className="font-bold text-medium">
                {t("model.dialog.help.title")}
              </p>
            </div>
            <div className="mt-0.5 ml-6">
              {(form.isBatchImport
                ? t("model.dialog.help.content.batchImport")
                : isSTTModel || isTTSModel
                  ? t("model.dialog.help.content.voice")
                  : t("model.dialog.help.content")
              )
                .split("\n")
                .map((line, index) => {
                  // Parse Markdown-style links: [text](url)
                  const markdownLinkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
                  const parts: (string | { text: string; url: string })[] = [];
                  let lastIndex = 0;
                  let match;

                  while ((match = markdownLinkRegex.exec(line)) !== null) {
                    // Add text before the link
                    if (match.index > lastIndex) {
                      parts.push(line.substring(lastIndex, match.index));
                    }
                    // Add the link object
                    parts.push({ text: match[1], url: match[2] });
                    lastIndex = match.index + match[0].length;
                  }

                  // Add remaining text after the last link
                  if (lastIndex < line.length) {
                    parts.push(line.substring(lastIndex));
                  }

                  // If no links found, just add the whole line
                  if (parts.length === 0) {
                    parts.push(line);
                  }

                  return (
                    <p key={index} className={index > 0 ? "mt-1" : ""}>
                      {parts.map((part, partIndex) => {
                        if (typeof part === "object") {
                          return (
                            <a
                              key={partIndex}
                              href={part.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-blue-600 hover:text-blue-800 underline"
                            >
                              {part.text}
                            </a>
                          );
                        }
                        return <span key={partIndex}>{part}</span>;
                      })}
                    </p>
                  );
                })}
            </div>
            <div className="mt-2 ml-6 flex items-center">
              <span>{t("model.dialog.label.currentlySupported")}</span>
              <Tooltip title="ModelEngine">
                <a
                  href={PROVIDER_LINKS.modelengine}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <img
                    src="/modelengine-logo.png"
                    alt="ModelEngine"
                    className="h-4 ml-1.5 cursor-pointer"
                  />
                </a>
              </Tooltip>
              {form.isBatchImport && (
                <>
                  <Tooltip title="SiliconFlow">
                    <a
                      href={PROVIDER_LINKS.siliconflow}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/siliconflow.png"
                        alt="SiliconFlow"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title={t("model.provider.dashscope")}>
                    <a
                      href={PROVIDER_LINKS.dashscope}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/aliyuncs.png"
                        alt="DashScope"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title={t("model.provider.tokenpony")}>
                    <a
                      href={PROVIDER_LINKS.tokenpony}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/tokenpony.png"
                        alt="TokenPony"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                </>
              )}
              {isSTTModel && (
                <>
                  <Tooltip title={t("model.provider.volcengine")}>
                    <a
                      href={PROVIDER_LINKS.volcengine}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/volcengine.png"
                        alt="VolcEngine"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title={t("model.provider.dashscope")}>
                    <a
                      href={PROVIDER_LINKS.dashscope}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/aliyuncs.png"
                        alt="AlibabaCloud"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                </>
              )}
              {isTTSModel && (
                <>
                  <Tooltip title={t("model.provider.volcengine")}>
                    <a
                      href={PROVIDER_LINKS.volcengine}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/volcengine.png"
                        alt="VolcEngine"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title={t("model.provider.dashscope")}>
                    <a
                      href={PROVIDER_LINKS.dashscope}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/aliyuncs.png"
                        alt="AlibabaCloud"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                </>
              )}
              {form.type === "llm" && !form.isBatchImport && (
                <>
                  <Tooltip title="OpenAI">
                    <a
                      href={PROVIDER_LINKS.openai}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/openai.png"
                        alt="OpenAI"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title="Kimi">
                    <a
                      href={PROVIDER_LINKS.kimi}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/kimi.png"
                        alt="Kimi"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title="Deepseek">
                    <a
                      href={PROVIDER_LINKS.deepseek}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/deepseek.png"
                        alt="Deepseek"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title="Qwen">
                    <a
                      href={PROVIDER_LINKS.qwen}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/qwen.png"
                        alt="Qwen"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <span className="ml-1.5">...</span>
                </>
              )}
              {form.type === "embedding" && !form.isBatchImport && (
                <>
                  <Tooltip title="OpenAI">
                    <a
                      href={PROVIDER_LINKS.openai}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/openai.png"
                        alt="OpenAI"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title="Qwen">
                    <a
                      href={PROVIDER_LINKS.qwen}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/qwen.png"
                        alt="Qwen"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title="Jina">
                    <a
                      href={PROVIDER_LINKS.jina}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/jina.png"
                        alt="Jina"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title="Baai">
                    <a
                      href={PROVIDER_LINKS.baai}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/baai.png"
                        alt="Baai"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <span className="ml-1.5">...</span>
                </>
              )}
              {form.type === "vlm" && !form.isBatchImport && (
                <>
                  <Tooltip title="Qwen">
                    <a
                      href={PROVIDER_LINKS.qwen}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/qwen.png"
                        alt="Qwen"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <Tooltip title="Deepseek">
                    <a
                      href={PROVIDER_LINKS.deepseek}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <img
                        src="/deepseek.png"
                        alt="Deepseek"
                        className="h-4 ml-1.5 cursor-pointer"
                      />
                    </a>
                  </Tooltip>
                  <span className="ml-1.5">...</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Footer Buttons */}
        <div className="flex justify-end space-x-3">
          <Button onClick={handleClose}>{t("common.button.cancel")}</Button>
          <Button
            type="primary"
            onClick={handleAddModel}
            disabled={
              !isFormValid() ||
              (!form.isBatchImport && connectivityStatus.status !== "available")
            }
            loading={loading}
          >
            {t("model.dialog.button.add")}
          </Button>
        </div>
      </div>

      {/* Settings Modal */}
      <Modal
        title={t("model.dialog.settings.title")}
        open={settingsModalVisible}
        onCancel={() => setSettingsModalVisible(false)}
        onOk={handleSettingsSave}
        okButtonProps={{ disabled: !isValidMaxTokens(modelMaxTokens) }}
        cancelText={t("common.cancel")}
        okText={t("common.confirm")}
        destroyOnHidden
      >
        <div className="space-y-3">
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.settings.label.maxTokens")}{" "}
              <span className="text-red-500">*</span>
            </label>
            <ModelMaxTokensInput
              value={modelMaxTokens}
              onChange={setModelMaxTokens}
              placeholder={t("model.dialog.placeholder.maxTokens")}
            />
          </div>
        </div>
      </Modal>
    </Modal>
  );
};
