import { useEffect } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { modelService } from "@/services/modelService";
import { ModelType } from "@/types/modelConfig";
import { processProviderResponse } from "@/lib/providerError";
import log from "@/lib/logger";

interface UseDashscopeModelListProps {
  form: {
    type: ModelType;
    isBatchImport: boolean;
    apiKey: string;
    provider: string; // Expected to be "dashscope"
    maxTokens: string;
    // W2 capacity-panel top-level default for max_output_tokens. Threaded
    // through so the row max_tokens fallback honors the new field; without
    // it batch-add rows fall back to the legacy 4096 sentinel.
    maxOutputTokens: string;
    isMultimodal: boolean;
  };
  setModelList: (models: any[]) => void;
  setSelectedModelIds: (ids: Set<string>) => void;
  setShowModelList: (show: boolean) => void;
  setLoadingModelList: (loading: boolean) => void;
  tenantId?: string; // Optional tenant ID for manage operations
}

export const useDashscopeModelList = ({
  form,
  setModelList,
  setSelectedModelIds,
  setShowModelList,
  setLoadingModelList,
  tenantId,
}: UseDashscopeModelListProps) => {
  const { t } = useTranslation();

  const getModelList = async () => {
    setShowModelList(true);
    setLoadingModelList(true);

    const modelType =
      form.type === "embedding" && form.isMultimodal
        ? ("multi_embedding" as ModelType)
        : form.type === "vlm2" || form.type === "vlm3"
          ? ("vlm" as ModelType)
          : form.type;

    try {
      // Use manage interface if tenantId is provided (for super admin)
      const result = tenantId
        ? await modelService.addManageProviderModel({
            tenantId,
            provider: form.provider,
            type: modelType,
            apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          })
        : await modelService.addProviderModel({
            provider: form.provider,
            type: modelType,
            apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
          });

      // Use centralized error processing
      const { models, error } = processProviderResponse(
        result,
        form.provider,
        t
      );

      if (error) {
        message.error(error);
        setModelList([]);
        setSelectedModelIds(new Set());
        setLoadingModelList(false);
        return;
      }

      // Ensure token-based models have a default max_tokens value.
      // Fallback order: catalog value -> top-level batch default for the new
      // W2 max_output_tokens field -> legacy max_tokens input -> hardcoded
      // safety net. Without including form.maxOutputTokens the new capacity
      // panel's value never reaches the row, and gear modals fall through to
      // the 4096 sentinel even when the user has filled a sensible default.
      const modelsWithDefaults =
        modelType === "stt"
          ? models
          : models.map((model: any) => ({
              ...model,
              max_tokens:
                model.max_tokens ||
                parseInt(form.maxOutputTokens) ||
                parseInt(form.maxTokens) ||
                4096,
            }));
      setModelList(modelsWithDefaults);

      const selectedModels = (await getProviderSelectedModalList()) || [];

      // Key logic: Sync previously selected models
      if (!selectedModels.length) {
        // Select none
        setSelectedModelIds(new Set());
      } else {
        // Only select selectedModels
        setSelectedModelIds(new Set(selectedModels.map((m: any) => m.id)));
      }
    } catch (error) {
      message.error(t("model.dialog.error.addFailed", { error }));
      log.error(t("model.dialog.error.addFailedLog"), error);
    } finally {
      setLoadingModelList(false);
    }
  };

  const getProviderSelectedModalList = async () => {
    const modelType =
      form.type === "embedding" && form.isMultimodal
        ? ("multi_embedding" as ModelType)
        : form.type;

    // Use manage interface if tenantId is provided (for super admin)
    const result = tenantId
      ? await modelService.getManageProviderSelectedModalList({
          tenantId,
          provider: form.provider,
          type: modelType,
        })
      : await modelService.getProviderSelectedModalList({
          provider: form.provider,
          type: modelType,
          api_key: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
        });

    return result;
  };

  // Auto-fetch model list when batch import is enabled and API key is provided
  useEffect(() => {
    if (form.isBatchImport && form.apiKey.trim() !== "") {
      getModelList();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.type, form.isBatchImport]);

  return {
    getModelList,
    getProviderSelectedModalList,
  };
};
