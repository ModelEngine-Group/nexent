import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { Modal, Input, Button, App } from "antd";

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
    maxTokens: "4096",
    vectorDimension: "1024",
    chunkSizeRange: [
      DEFAULT_EXPECTED_CHUNK_SIZE,
      DEFAULT_MAXIMUM_CHUNK_SIZE,
    ] as [number, number],
    chunkingBatchSize: "10",
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
        maxTokens: model.maxTokens?.toString() || "4096",
        vectorDimension: model.maxTokens?.toString() || "1024",
        chunkSizeRange: [
          model.expectedChunkSize || DEFAULT_EXPECTED_CHUNK_SIZE,
          model.maximumChunkSize || DEFAULT_MAXIMUM_CHUNK_SIZE,
        ] as [number, number],
        chunkingBatchSize: (model.chunkingBatchSize || 10).toString(),
      });
    }
  }, [model]);

  const handleFormChange = (field: string, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    // If the key configuration item changes, clear the verification status
    if (["url", "apiKey", "maxTokens", "vectorDimension"].includes(field)) {
      setConnectivityStatus({ status: null, message: "" });
    }
  };

  const isEmbeddingModel =
    form.type === MODEL_TYPES.EMBEDDING ||
    form.type === MODEL_TYPES.MULTI_EMBEDDING;

  const isFormValid = () => {
    return form.name.trim() !== "" && form.url.trim() !== "";
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
      const modelType = form.type as ModelType;

      // Use manage interface if tenantId is provided
      if (tenantId) {
        // Call backend healthcheck API for tenant management
        const result = await modelService.checkManageTenantModelConnectivity(
          tenantId,
          form.displayName || form.name
        );

        // Set connectivity status
        let connectivityMessage = "";
        if (result) {
          connectivityMessage = t("model.dialog.connectivity.status.available");
        } else {
          connectivityMessage = t("model.dialog.connectivity.status.unavailable");
        }
        setConnectivityStatus({
          status: result
            ? MODEL_STATUS.AVAILABLE
            : MODEL_STATUS.UNAVAILABLE,
          message: connectivityMessage,
        });
      } else {
        // Use local config verification for non-tenant operations
        const config = {
          modelName: form.name,
          modelType: modelType,
          baseUrl: form.url,
          apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          maxTokens:
            form.type === MODEL_TYPES.EMBEDDING
              ? parseInt(form.vectorDimension)
              : parseInt(form.maxTokens),
          embeddingDim:
            form.type === MODEL_TYPES.EMBEDDING
              ? parseInt(form.vectorDimension)
              : undefined,
        };

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
      }
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
    setLoading(true);
    try {
      // Use update interface instead of delete + add
      const modelType = form.type as ModelType;
      // Determine max tokens
      let maxTokensValue = parseInt(form.maxTokens);
      if (isEmbeddingModel) maxTokensValue = 0;

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
        });
      }

      // Update local configuration (only when currently edited model is selected in configuration)
      const modelConfigKeyMap: Record<ModelType, string> = {
        llm: MODEL_TYPES.LLM,
        embedding: MODEL_TYPES.EMBEDDING,
        multi_embedding: MODEL_TYPES.MULTI_EMBEDDING,
        vlm: MODEL_TYPES.VLM,
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
          ...(isEmbeddingModel
            ? { dimension: parseInt(form.vectorDimension) }
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
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.url")}
          </label>
          <Input
            value={form.url}
            onChange={(e) => handleFormChange("url", e.target.value)}
          />
        </div>

        {/* API Key */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.apiKey")}
          </label>
          <Input.Password
            value={form.apiKey}
            onChange={(e) => handleFormChange("apiKey", e.target.value)}
            autoComplete="new-password"
          />
        </div>

        {/* maxTokens */}
        {!isEmbeddingModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t("model.dialog.label.maxTokens")}
            </label>
            <Input
              value={form.maxTokens}
              onChange={(e) => handleFormChange("maxTokens", e.target.value)}
            />
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
interface ProviderConfigEditDialogProps {
  isOpen: boolean
  initialApiKey?: string
  initialMaxTokens?: string
  modelType?: ModelType
  onClose: () => void
  onSave: (config: { apiKey: string; maxTokens: number }) => Promise<void> | void
}

export const ProviderConfigEditDialog = ({
  isOpen,
  initialApiKey = '',
  initialMaxTokens = '4096',
  modelType,
  onClose,
  onSave,
}: ProviderConfigEditDialogProps) => {
  const { t } = useTranslation()
  const [apiKey, setApiKey] = useState<string>(initialApiKey)
  const [maxTokens, setMaxTokens] = useState<string>(initialMaxTokens)
  const [saving, setSaving] = useState<boolean>(false)

  useEffect(() => {
    setApiKey(initialApiKey)
    setMaxTokens(initialMaxTokens)
  }, [initialApiKey, initialMaxTokens])

  const valid = () => {
    const parsed = parseInt(maxTokens)
    return !Number.isNaN(parsed) && parsed >= 0
  }

  const handleSave = async () => {
    if (!valid()) return
    try {
      setSaving(true)
      await onSave({ apiKey: apiKey.trim() === '' ? 'sk-no-api-key' : apiKey, maxTokens: parseInt(maxTokens) })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const isEmbeddingModel = modelType === MODEL_TYPES.EMBEDDING || modelType === MODEL_TYPES.MULTI_EMBEDDING

  return (
    <Modal
      title={t('common.button.editConfig')}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <div className="space-y-4">
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t('model.dialog.label.apiKey')}
          </label>
          <Input.Password value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </div>
        {!isEmbeddingModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.maxTokens')}
            </label>
            <Input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} />
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