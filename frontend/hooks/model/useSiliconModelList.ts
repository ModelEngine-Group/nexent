import { useEffect } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { modelService } from "@/services/modelService";
import { ModelType } from "@/types/modelConfig";
import { processProviderResponse } from "@/lib/providerError";
import log from "@/lib/logger";

interface UseSiliconModelListProps {
  form: {
    type: ModelType;
    isBatchImport: boolean;
    apiKey: string;
    provider: string;
    maxTokens: string;
    isMultimodal: boolean;
  };
  setModelList: (models: any[]) => void;
  setSelectedModelIds: (ids: Set<string>) => void;
  setShowModelList: (show: boolean) => void;
  setLoadingModelList: (loading: boolean) => void;
  tenantId?: string; // Optional tenant ID for manage operations
}

export const useSiliconModelList = ({
  form,
  setModelList,
  setSelectedModelIds,
  setShowModelList,
  setLoadingModelList,
  tenantId,
}: UseSiliconModelListProps) => {
  const { t } = useTranslation();

  const getModelList = async () => {
    setShowModelList(true);
    setLoadingModelList(true);
    const modelType =
      form.type === "embedding" && form.isMultimodal
        ? ("multi_embedding" as ModelType)
        : form.type;
    try {
      // Use manage interface if tenantId is provided (for super admin)
      const result = tenantId
        ? await modelService.addManageProviderModel({
            tenantId,
            provider: form.provider,
            type: modelType,
            apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
            baseUrl:
              form.provider === "modelengine" && form.apiKey.trim() !== ""
                ? (form as any).modelEngineUrl || ""
                : undefined,
          })
        : await modelService.addProviderModel({
            provider: form.provider,
            type: modelType,
            apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
            baseUrl:
              form.provider === "modelengine" && form.apiKey.trim() !== ""
                ? (form as any).modelEngineUrl || ""
                : undefined,
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

      // Ensure each model has a default max_tokens value
      const modelsWithDefaults = models.map((model: any) => ({
        ...model,
        max_tokens: model.max_tokens || parseInt(form.maxTokens) || 4096,
      }));
      setModelList(modelsWithDefaults);

      const selectedModels = (await getProviderSelectedModalList()) || [];
      // Key logic
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
          baseUrl:
            form.provider === "modelengine" && form.apiKey.trim() !== ""
              ? (form as any).modelEngineUrl || ""
              : undefined,
        });
    return result;
  };

  // Auto-fetch model list when batch import is enabled and API key is provided
  useEffect(() => {
    const requiresUrl =
      form.provider === "modelengine"
        ? ((form as any).modelEngineUrl || "").toString().trim() !== ""
        : true;

    if (form.isBatchImport && form.apiKey.trim() !== "" && requiresUrl) {
      getModelList();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.type, form.isBatchImport]);

  return {
    getModelList,
    getProviderSelectedModalList,
  };
};
