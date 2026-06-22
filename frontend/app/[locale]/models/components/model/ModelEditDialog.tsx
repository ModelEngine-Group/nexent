import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { Modal, Select, Input, Button, App } from "antd";

import { MODEL_TYPES, MODEL_STATUS } from "@/const/modelConfig";
import { useConfig } from "@/hooks/useConfig";
import { modelService } from "@/services/modelService";
import { ModelOption, ModelType } from "@/types/modelConfig";
import { getConnectivityMeta, ConnectivityStatusType } from "@/lib/utils";
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
import {
  buildCapacityPayload,
  capacityFormFromModel,
  emptyCapacityForm,
  ModelCapacityFields,
  validateCapacityForm,
} from "./ModelCapacityFields";

const { Option } = Select;

interface ModelEditDialogProps {
  isOpen: boolean;
  model: ModelOption | null;
  onClose: () => void;
  onSuccess: () => Promise<void>;
  tenantId?: string; // Optional tenant ID for manage operations
}

export const ModelEditDialog = ({
  isOpen,
  model,
  onClose,
  onSuccess,
  tenantId,
}: ModelEditDialogProps) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { updateModelConfig } = useConfig();
  const [form, setForm] = useState({
    type: MODEL_TYPES.LLM as ModelType,
    name: "",
    displayName: "",
    url: "",
    apiKey: "",
    maxTokens: "",
    timeoutSeconds: "120",
    concurrencyLimit: "",
    vectorDimension: "1024",
    chunkSizeRange: [
      DEFAULT_EXPECTED_CHUNK_SIZE,
      DEFAULT_MAXIMUM_CHUNK_SIZE,
    ] as [number, number],
    chunkingBatchSize: "10",
    // Voice model fields (STT/TTS)
    modelFactory: "",
    modelAppid: "",
    accessToken: "",
    ...emptyCapacityForm,
  });
  const [loading, setLoading] = useState(false);
  const [verifyingConnectivity, setVerifyingConnectivity] = useState(false);
  const [connectivityStatus, setConnectivityStatus] = useState<{
    status: ConnectivityStatusType;
    message: string;
  }>({
    status: null,
    message: "",
  });

  useEffect(() => {
    if (model) {
      setForm({
        type: model.type,
        name: model.name,
        displayName: model.displayName || model.name,
        url: model.apiUrl || "",
        apiKey: model.apiKey || "",
        maxTokens: model.maxTokens?.toString() || "",
        timeoutSeconds: model.timeoutSeconds?.toString() || "120",
        concurrencyLimit: model.concurrencyLimit?.toString() || "",
        vectorDimension: model.maxTokens?.toString() || "1024",
        chunkSizeRange: [
          model.expectedChunkSize || DEFAULT_EXPECTED_CHUNK_SIZE,
          model.maximumChunkSize || DEFAULT_MAXIMUM_CHUNK_SIZE,
        ] as [number, number],
        chunkingBatchSize: (model.chunkingBatchSize || 10).toString(),
        modelFactory: model.modelFactory || "",
        modelAppid: model.modelAppid || "",
        accessToken: model.accessToken || "",
        ...capacityFormFromModel(model),
      });
    }
  }, [model]);

  const handleFormChange = (field: string, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    // If the key configuration item changes, clear the verification status
    if ([
      "url",
      "apiKey",
      "maxTokens",
      "timeoutSeconds",
      "concurrencyLimit",
      "vectorDimension",
      "modelFactory",
      "modelAppid",
      "accessToken",
    ].includes(field)) {
      setConnectivityStatus({ status: null, message: "" });
    }
  };

  const isEmbeddingModel =
    form.type === MODEL_TYPES.EMBEDDING ||
    form.type === MODEL_TYPES.MULTI_EMBEDDING;
  const isRerankModel = form.type === MODEL_TYPES.RERANK;
  const connectivityModelType =
    form.type === MODEL_TYPES.VLM2 || form.type === MODEL_TYPES.VLM3
      ? (MODEL_TYPES.VLM as ModelType)
      : form.type;
  const isVoiceModel =
    form.type === MODEL_TYPES.STT || form.type === MODEL_TYPES.TTS;
  const supportsCapacityFields =
    !isEmbeddingModel && !isRerankModel && !isVoiceModel;
  const capacityValidationError = supportsCapacityFields
    ? validateCapacityForm(form, ["contextWindowTokens", "maxOutputTokens"])
    : null;

  const isFormValid = () => {
    if (
      supportsCapacityFields &&
      validateCapacityForm(form, ["contextWindowTokens", "maxOutputTokens"])
    ) {
      return false;
    }

    // Capacity panel replaces the legacy max_tokens field for LLM/VLM, so
    // the standalone max_tokens is only required for the types that still
    // render that field (voice and rerank-style).
    const needsMaxTokens =
      !supportsCapacityFields && !isEmbeddingModel && !isRerankModel;

    if (isVoiceModel) {
      if (needsMaxTokens && !isValidMaxTokens(form.maxTokens)) {
        return false;
      }
      if (form.modelFactory === "volcengine") {
        return (
          form.modelAppid.trim() !== "" &&
          form.accessToken.trim() !== ""
        );
      } else {
        return form.name.trim() !== "" && form.apiKey.trim() !== "";
      }
    }
    return (
      form.name.trim() !== "" &&
      form.url.trim() !== "" &&
      (!needsMaxTokens || isValidMaxTokens(form.maxTokens))
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
      // For LLM/VLM the legacy form.maxTokens field is no longer rendered;
      // use form.maxOutputTokens (capacity panel) for the connectivity-probe
      // budget. Do NOT fall back to form.maxTokens for capacity types --
      // the W1/W2 plan deprecates that field for LLM/VLM, and isFormValid
      // already guarantees form.maxOutputTokens is filled before this
      // probe runs.
      const llmProbeMaxTokens = supportsCapacityFields
        ? Number.parseInt(form.maxOutputTokens || "0", 10)
        : parseMaxTokens(form.maxTokens);
      const config: any = {
        modelName: form.name,
        modelType: connectivityModelType,
        baseUrl: form.url,
        apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
        maxTokens:
          form.type === MODEL_TYPES.EMBEDDING
            ? parseInt(form.vectorDimension)
            : form.type === MODEL_TYPES.RERANK
              ? 0
              : llmProbeMaxTokens,
        embeddingDim:
          form.type === MODEL_TYPES.EMBEDDING
            ? parseInt(form.vectorDimension)
            : undefined,
      };

      // Add voice model fields for STT/TTS
      if (isVoiceModel) {
        config.modelFactory = form.modelFactory;
        if (form.modelFactory === "volcengine") {
          config.modelAppid = form.modelAppid;
          config.accessToken = form.accessToken;
        }
      }

      const result = await modelService.verifyModelConfigConnectivity(config);

      // Set connectivity status
      let connectivityMessage = "";
      if (result.connectivity) {
        connectivityMessage = t("model.dialog.connectivity.status.available");
      } else {
        connectivityMessage = t("model.dialog.connectivity.status.unavailable");
      }
      setConnectivityStatus({
        status: result.connectivity
          ? MODEL_STATUS.AVAILABLE
          : MODEL_STATUS.UNAVAILABLE,
        message: connectivityMessage,
      });
    } catch (error) {
      setConnectivityStatus({
        status: "unavailable",
        message: t("model.dialog.connectivity.status.unavailable"),
      });
    } finally {
      setVerifyingConnectivity(false);
    }
  };

  const handleSave = async () => {
    if (!model) return;
    // Defensive gate: the Save button is already disabled via
    // `!isFormValid()`, but disabled state can lag a tick behind state
    // updates and the handler is also reachable from non-click paths.
    // Re-check here so we never persist a row whose required W2 capacity
    // fields are empty (this is how production glm-5.2 rows ended up with
    // context_window_tokens=NULL and max_output_tokens=NULL).
    if (!isFormValid()) return;
    setLoading(true);
    try {
      // Use update interface instead of delete + add
      const modelType = form.type as ModelType;
      // Determine max tokens.
      // For LLM/VLM (supportsCapacityFields), the legacy form.maxTokens
      // input is hidden and must not be read here per the W1/W2 plan
      // ("Never use legacy max_tokens"). Seed the legacy column with 0;
      // buildCapacityPayload(form) spreads max_tokens := max_output_tokens
      // a few lines below, keeping the deprecated NOT NULL column aligned
      // with the W2 source of truth.
      let maxTokensValue = supportsCapacityFields
        ? 0
        : parseMaxTokens(form.maxTokens) || 0;
      if (isEmbeddingModel || isRerankModel) maxTokensValue = 0;

      // Use original displayName for lookup, pass new displayName in body if changed
      const originalDisplayName = model.displayName || model.name;
      const newDisplayName = form.displayName;

      // Use manage interface if tenantId is provided
      if (tenantId) {
        await modelService.updateManageTenantModel({
          tenantId,
          currentDisplayName: originalDisplayName,
          displayName: newDisplayName !== originalDisplayName ? newDisplayName : undefined,
          url: form.url,
          apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          maxTokens: maxTokensValue !== 0 ? maxTokensValue : undefined,
          expectedChunkSize: isEmbeddingModel ? form.chunkSizeRange[0] : undefined,
          maximumChunkSize: isEmbeddingModel ? form.chunkSizeRange[1] : undefined,
          chunkingBatchSize: isEmbeddingModel ? parseInt(form.chunkingBatchSize) || 10 : undefined,
          modelFactory: isVoiceModel ? form.modelFactory : undefined,
          modelAppid: isVoiceModel && form.modelFactory === "volcengine" ? form.modelAppid : undefined,
          accessToken: isVoiceModel && form.modelFactory === "volcengine" ? form.accessToken : undefined,
          timeoutSeconds: !isEmbeddingModel && !isRerankModel ? parseInt(form.timeoutSeconds) || 120 : undefined,
          concurrencyLimit: !isEmbeddingModel && !isRerankModel ? (form.concurrencyLimit ? parseInt(form.concurrencyLimit) : undefined) : undefined,
          ...(supportsCapacityFields ? buildCapacityPayload(form) : {}),
        });
      } else {
        await modelService.updateSingleModel({
          currentDisplayName: originalDisplayName,
          // Only send displayName if it changed
          ...(newDisplayName !== originalDisplayName
            ? { displayName: newDisplayName }
            : {}),
          url: form.url,
          apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          ...(maxTokensValue !== 0 ? { maxTokens: maxTokensValue } : {}),
          source: model.source,
          // Send chunk size range for embedding models
          ...(isEmbeddingModel
            ? {
                expectedChunkSize: form.chunkSizeRange[0],
                maximumChunkSize: form.chunkSizeRange[1],
                chunkingBatchSize: parseInt(form.chunkingBatchSize) || 10,
              }
            : {}),
          // Send voice model fields
          ...(isVoiceModel
            ? {
                modelFactory: form.modelFactory,
                modelAppid: form.modelFactory === "volcengine" ? form.modelAppid : undefined,
                accessToken: form.modelFactory === "volcengine" ? form.accessToken : undefined,
              }
            : {}),
          // Send timeout for non-embedding models
          ...(!isEmbeddingModel && !isRerankModel
            ? {
                timeoutSeconds: parseInt(form.timeoutSeconds) || 120,
                concurrencyLimit: form.concurrencyLimit ? parseInt(form.concurrencyLimit) : undefined,
              }
            : {}),
          ...(supportsCapacityFields ? buildCapacityPayload(form) : {}),
        });
      }

      // Update local configuration (only when currently edited model is selected in configuration)
      const modelConfigKeyMap: Record<ModelType, string> = {
        llm: MODEL_TYPES.LLM,
        embedding: MODEL_TYPES.EMBEDDING,
        multi_embedding: MODEL_TYPES.MULTI_EMBEDDING,
        vlm: MODEL_TYPES.VLM,
        vlm2: MODEL_TYPES.VLM2,
        vlm3: MODEL_TYPES.VLM3,
        rerank: MODEL_TYPES.RERANK,
        tts: MODEL_TYPES.TTS,
        stt: MODEL_TYPES.STT,
      };
      const configKey = modelConfigKeyMap[modelType];
      updateModelConfig({
        [configKey]: {
          modelName: form.name,
          displayName: form.displayName || form.name,
          apiConfig: {
            apiKey: form.apiKey,
            modelUrl: form.url,
          },
          ...(supportsCapacityFields ? buildCapacityPayload(form) : {}),
          ...(isEmbeddingModel
            ? { dimension: parseInt(form.vectorDimension) }
            : {}),
          ...(isVoiceModel
            ? {
                modelFactory: form.modelFactory,
                modelAppid: form.modelFactory === "volcengine" ? form.modelAppid : "",
                accessToken: form.modelFactory === "volcengine" ? form.accessToken : "",
              }
            : {}),
        },
      });

      await onSuccess();
      message.success(t("model.dialog.editSuccess"));
      onClose();
    } catch (error: any) {
      if (error.code === 409) {
        message.error(
          t("model.dialog.error.nameConflict", {
            name: form.displayName || form.name,
          })
        );
      } else if (error.code === 404) {
        message.error(t("model.dialog.error.modelNotFound"));
      } else if (error.code === 500) {
        message.error(t("model.dialog.error.serverError"));
      } else {
        message.error(t("model.dialog.error.editFailed"));
        console.error(error);
      }
    } finally {
      setLoading(false);
    }
  };

  if (!model) return null;

  return (
    <Modal
      title={t("model.dialog.editTitle")}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <div className="space-y-4">
        {/* Model Name */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.displayName")}
          </label>
          <Input
            value={form.displayName}
            onChange={(e) => handleFormChange("displayName", e.target.value)}
          />
        </div>

        {/* URL */}
        {!isVoiceModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.url")}
            </label>
            <Input
              value={form.url}
              onChange={(e) => handleFormChange("url", e.target.value)}
            />
          </div>
        )}

        {/* Voice Model Factory */}
        {isVoiceModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {form.type === MODEL_TYPES.TTS
                ? t("model.dialog.label.ttsProvider")
                : t("model.dialog.label.sttProvider")}
            </label>
            <Select
              style={{ width: "100%" }}
              value={form.modelFactory || "dashscope"}
              onChange={(value) => handleFormChange("modelFactory", value)}
            >
              <Option value="dashscope">{t("model.provider.dashscope")}</Option>
              <Option value="volcengine">{t("model.provider.volcengine")}</Option>
            </Select>
          </div>
        )}

        {/* Voice Model App ID and Access Token (Volcengine) */}
        {isVoiceModel && form.modelFactory === "volcengine" && (
          <>
            <div>
              <label className="block mb-1 text-sm font-medium text-gray-700">
                {t("model.dialog.label.modelAppid")}
              </label>
              <Input
                value={form.modelAppid}
                onChange={(e) => handleFormChange("modelAppid", e.target.value)}
                autoComplete="new-password"
              />
            </div>
            <div>
              <label className="block mb-1 text-sm font-medium text-gray-700">
                {t("model.dialog.label.accessToken")}
              </label>
              <Input.Password
                value={form.accessToken}
                onChange={(e) => handleFormChange("accessToken", e.target.value)}
                autoComplete="new-password"
                visibilityToggle={false}
              />
            </div>
          </>
        )}

        {/* API Key */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.apiKey")}
          </label>
          <Input.Password
            value={form.apiKey}
            onChange={(e) => handleFormChange("apiKey", e.target.value)}
            autoComplete="new-password"
            visibilityToggle={false}
          />
        </div>

        {supportsCapacityFields && (
          <ModelCapacityFields
            value={form}
            onChange={(field, value) => handleFormChange(field, value)}
            validationError={capacityValidationError}
            capacitySource={model.capacitySource}
            capabilityProfileVersion={model.capabilityProfileVersion}
            requiredFields={["contextWindowTokens", "maxOutputTokens"]}
            // The deprecation warning only makes sense when the form still
            // has no max_output_tokens after capacityFormFromModel ran.
            // capacityFormFromModel auto-promotes legacy max_tokens into
            // the form's maxOutputTokens, so this stays true only when
            // neither column is populated on the model record.
            showDeprecatedMaxTokensWarning={
              Boolean(model.maxTokens) &&
              !model.maxOutputTokens &&
              !form.maxOutputTokens
            }
          />
        )}

        {/* maxTokens (legacy; only kept for types not covered by the capacity panel) */}
        {!isEmbeddingModel && !isRerankModel && !supportsCapacityFields && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.maxTokens")}{" "}
              <span className="text-red-500">*</span>
            </label>
            <ModelMaxTokensInput
              value={form.maxTokens}
              placeholder={t("model.dialog.placeholder.maxTokens")}
              onChange={(value) => handleFormChange("maxTokens", value)}
            />
          </div>
        )}

        {/* Timeout Seconds */}
        {!isEmbeddingModel && !isRerankModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.timeoutSeconds")}
            </label>
            <Input
              type="number"
              min="1"
              value={form.timeoutSeconds}
              onChange={(e) => handleFormChange("timeoutSeconds", e.target.value)}
            />
          </div>
        )}

        {/* Concurrency Limit */}
        {!isEmbeddingModel && !isRerankModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.concurrencyLimit")}
            </label>
            <Input
              type="number"
              min="1"
              value={form.concurrencyLimit}
              onChange={(e) => handleFormChange("concurrencyLimit", e.target.value)}
              placeholder={t("model.dialog.placeholder.concurrencyLimit")}
            />
            <div className="text-xs text-gray-500 mt-1">
              {t("model.dialog.hint.concurrencyLimit")}
            </div>
          </div>
        )}

        {/* Chunk Size Range for embedding models */}
        {isEmbeddingModel && (
          <div>
            <label className="block mb-2 text-sm font-medium text-gray-700">
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

        {/* Connectivity verification area */}
        <div className="p-3 bg-gray-50 border border-gray-200 rounded-md">
          <div className="flex items-center justify-between mb-1">
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
              loading={verifyingConnectivity}
              disabled={!isFormValid() || verifyingConnectivity}
            >
              {verifyingConnectivity
                ? t("model.dialog.button.verifying")
                : t("model.dialog.button.verify")}
            </Button>
          </div>
        </div>

        <div className="flex justify-end space-x-3">
          <Button onClick={onClose}>{t("common.button.cancel")}</Button>
          <Button
            type="primary"
            onClick={handleSave}
            loading={loading}
            disabled={!isFormValid()}
          >
            {t("common.button.save")}
          </Button>
        </div>
      </div>
    </Modal>
  );
};

// New: provider config edit dialog (only apiKey and maxTokens)
interface ProviderConfigInitialCapacity {
  contextWindowTokens?: number
  maxInputTokens?: number
  maxOutputTokens?: number
  /** Legacy alias passed through so capacityFormFromModel can auto-migrate it. */
  maxTokens?: number
  defaultOutputReserveTokens?: number
  tokenizerFamily?: string
  capacitySource?: string
  capabilityProfileVersion?: string
}

interface ProviderConfigEditDialogProps {
  isOpen: boolean
  initialApiKey?: string
  initialMaxTokens?: string
  initialTimeoutSeconds?: string
  initialConcurrencyLimit?: string
  initialCapacity?: ProviderConfigInitialCapacity
  hideCapacityFields?: boolean  // Suppress capacity controls when caller is a provider-level batch (not per-model)
  modelType?: ModelType
  showApiKeyField?: boolean  // Whether to show API Key field (default: true)
  onClose: () => void
  onSave: (config: {
    apiKey?: string
    maxTokens: number
    timeoutSeconds?: number
    concurrencyLimit?: number
    contextWindowTokens?: number
    maxInputTokens?: number
    maxOutputTokens?: number
    defaultOutputReserveTokens?: number
    tokenizerFamily?: string
    capacitySource?: string
  }) => Promise<void> | void
}

export const ProviderConfigEditDialog = ({
  isOpen,
  initialApiKey = '',
  initialMaxTokens = '',
  initialTimeoutSeconds = '120',
  initialConcurrencyLimit = '',
  initialCapacity,
  hideCapacityFields = false,
  modelType,
  showApiKeyField = true,
  onClose,
  onSave,
}: ProviderConfigEditDialogProps) => {
  const { t } = useTranslation()
  const [apiKey, setApiKey] = useState<string>(initialApiKey)
  const [maxTokens, setMaxTokens] = useState<string>(initialMaxTokens)
  const [timeoutSeconds, setTimeoutSeconds] = useState<string>(initialTimeoutSeconds)
  const [concurrencyLimit, setConcurrencyLimit] = useState<string>(initialConcurrencyLimit)
  const [capacityForm, setCapacityForm] = useState(
    initialCapacity ? capacityFormFromModel(initialCapacity) : emptyCapacityForm
  )
  const [saving, setSaving] = useState<boolean>(false)

  useEffect(() => {
    setApiKey(initialApiKey)
    setMaxTokens(initialMaxTokens)
    setTimeoutSeconds(initialTimeoutSeconds)
    setConcurrencyLimit(initialConcurrencyLimit)
    setCapacityForm(
      initialCapacity ? capacityFormFromModel(initialCapacity) : emptyCapacityForm
    )
  }, [initialApiKey, initialMaxTokens, initialTimeoutSeconds, initialConcurrencyLimit, initialCapacity])

  const isEmbeddingModel = modelType === MODEL_TYPES.EMBEDDING || modelType === MODEL_TYPES.MULTI_EMBEDDING
  const isRerankModel = modelType === MODEL_TYPES.RERANK
  const isVoiceModel = modelType === MODEL_TYPES.STT || modelType === MODEL_TYPES.TTS
  const supportsCapacityFields =
    !hideCapacityFields && !isEmbeddingModel && !isRerankModel && !isVoiceModel
  // Only rerank and voice models legitimately need the deprecated max_tokens
  // input. LLM/VLM use the capacity panel; when the dialog is in provider-
  // level mode (hideCapacityFields=true) it edits shared settings only --
  // capacity is per-model and lives on each gear-icon dialog. Per the W1/W2
  // plan, never surface legacy max_tokens for LLM/VLM regardless of the
  // hideCapacityFields flag.
  const needsLegacyMaxTokens = isRerankModel || isVoiceModel
  const capacityValidationError = supportsCapacityFields
    ? validateCapacityForm(capacityForm, [
        "contextWindowTokens",
        "maxOutputTokens",
      ])
    : null

  const handleCapacityChange = (field: keyof typeof capacityForm, value: string) => {
    setCapacityForm((prev) => ({ ...prev, [field]: value }))
  }

  const valid = () => {
    if (supportsCapacityFields) {
      // For LLM/VLM the legacy max_tokens input is hidden — the capacity
      // panel's max_output_tokens is the source of truth and is already
      // required by validateCapacityForm. Don't gate Save on the now-hidden
      // legacy input.
      return !capacityValidationError
    }
    if (needsLegacyMaxTokens) {
      return isValidMaxTokens(maxTokens)
    }
    // No capacity panel and no legacy field rendered (provider-level config
    // edit for LLM/VLM, embedding shared config): the dialog only owns
    // apiKey/timeoutSeconds/concurrencyLimit, so always valid.
    return true
  }

  const handleSave = async () => {
    if (!valid()) return
    try {
      setSaving(true)
      // Only rerank/voice models legitimately surface the legacy maxTokens
      // input. In every other case the maxTokens state still carries the
      // backend's DEFAULT_LLM_MAX_TOKENS sentinel from the row prefill, so
      // reading it would either be a no-op (LLM/VLM with capacity panel:
      // buildCapacityPayload's max_output_tokens mirror overrides) or
      // actively wrong (LLM/VLM provider-level config: would force the
      // 4096 sentinel onto every existing row). Sending 0 here makes
      // handleProviderConfigSave's `maxTokens || m.maxTokens` fall back to
      // each row's current value, preserving it.
      const legacyMaxTokens = needsLegacyMaxTokens
        ? parseMaxTokens(maxTokens) || 0
        : 0
      await onSave({
        ...(showApiKeyField ? { apiKey: apiKey.trim() === '' ? 'sk-no-api-key' : apiKey } : {}),
        maxTokens: legacyMaxTokens,
        ...(!isEmbeddingModel && !isRerankModel ? { timeoutSeconds: parseInt(timeoutSeconds) || 120 } : {}),
        ...(!isEmbeddingModel && !isRerankModel ? { concurrencyLimit: concurrencyLimit ? parseInt(concurrencyLimit) : undefined } : {}),
        ...(supportsCapacityFields ? buildCapacityPayload(capacityForm) : {}),
      })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={t('common.button.editConfig')}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <div className="space-y-4">
        {showApiKeyField && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.apiKey')}
            </label>
            <Input.Password value={apiKey} onChange={(e) => setApiKey(e.target.value)} visibilityToggle={false} />
          </div>
        )}
        {supportsCapacityFields && (
          <ModelCapacityFields
            value={capacityForm}
            onChange={handleCapacityChange}
            validationError={capacityValidationError}
            capacitySource={initialCapacity?.capacitySource}
            capabilityProfileVersion={initialCapacity?.capabilityProfileVersion}
            requiredFields={["contextWindowTokens", "maxOutputTokens"]}
            showDeprecatedMaxTokensWarning={
              Boolean(initialMaxTokens) &&
              !initialCapacity?.maxOutputTokens &&
              !capacityForm.maxOutputTokens
            }
          />
        )}
        {/* Legacy max_tokens input — only rendered for model types that
            legitimately still own this field (rerank, STT/TTS). LLM/VLM use
            the capacity panel; if hideCapacityFields=true is set (provider-
            level config edit) the dialog deliberately drops both the
            capacity panel and the legacy input -- per the W1/W2 plan
            ("Never use legacy max_tokens") capacity is set per-model from
            the gear icon, not via a provider-level shared value. */}
        {needsLegacyMaxTokens && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.maxTokens')} <span className="text-red-500">*</span>
            </label>
            <ModelMaxTokensInput
              value={maxTokens}
              placeholder={t("model.dialog.placeholder.maxTokens")}
              onChange={setMaxTokens}
            />
          </div>
        )}
        {!isEmbeddingModel && !isRerankModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.timeoutSeconds")}
            </label>
            <Input
              type="number"
              min="1"
              value={timeoutSeconds}
              onChange={(e) => setTimeoutSeconds(e.target.value)}
            />
          </div>
        )}
        {!isEmbeddingModel && !isRerankModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.concurrencyLimit")}
            </label>
            <Input
              type="number"
              min="1"
              value={concurrencyLimit}
              onChange={(e) => setConcurrencyLimit(e.target.value)}
              placeholder={t("model.dialog.placeholder.concurrencyLimit")}
            />
            <div className="text-xs text-gray-500 mt-1">
              {t("model.dialog.hint.concurrencyLimit")}
            </div>
          </div>
        )}
        <div className="flex justify-end space-x-3">
          <Button onClick={onClose}>{t('common.button.cancel')}</Button>
          <Button type="primary" onClick={handleSave} loading={saving} disabled={!valid()}>
            {t('common.button.save')}
          </Button>
        </div>
      </div>
    </Modal>
  )
} 
