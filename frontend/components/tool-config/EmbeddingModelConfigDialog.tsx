"use client";

import React, { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Modal, Select, App, Spin } from "antd";
import { ExclamationCircleFilled } from "@ant-design/icons";

import { useModelList } from "@/hooks/model/useModelList";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import log from "@/lib/logger";

interface EmbeddingModelConfigDialogProps {
  isOpen: boolean;
  knowledgeBaseName: string;
  indexName: string;
  isModelMismatch?: boolean;
  kbIdsToUpdate?: string[];
  onClose: () => void;
  onConfigComplete: (
    indexNames: string,
    modelId: string,
    modelDisplayName?: string
  ) => void;
}

export default function EmbeddingModelConfigDialog({
  isOpen,
  knowledgeBaseName,
  indexName,
  isModelMismatch = false,
  kbIdsToUpdate = [],
  onClose,
  onConfigComplete,
}: EmbeddingModelConfigDialogProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { data: allModels = [], isLoading: modelsLoading } = useModelList();

  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Filter available embedding models
  const embeddingModels = allModels.filter(
    (model) => model.type === "embedding" && model.connect_status === "available"
  );

  // Reset state when dialog opens
  useEffect(() => {
    log.info("[EmbeddingModelConfigDialog] isOpen changed to:", isOpen);
    if (isOpen) {
      setSelectedModelId(null);
      setIsSubmitting(false);
    }
  }, [isOpen]);

  // Handle model selection
  const handleModelChange = (value: string) => {
    log.info("[EmbeddingModelConfigDialog] handleModelChange:", value);
    setSelectedModelId(value);
  };

  // Handle submit
  const handleSubmit = async () => {
    log.info("[EmbeddingModelConfigDialog] handleSubmit called, isSubmitting:", isSubmitting, "selectedModelId:", selectedModelId);
    if (!selectedModelId) {
      message.warning(t("knowledgeBase.embeddingModel.selectPlaceholder"));
      return;
    }

    setIsSubmitting(true);
    log.info("[EmbeddingModelConfigDialog] isSubmitting set to true, calling API...");
    try {
      // Determine which index names to update
      const indexNamesToUpdate =
        kbIdsToUpdate.length > 0
          ? kbIdsToUpdate.join(",")
          : indexName;

      // Get model display name
      const selectedModel = embeddingModels.find(
        (m) => String(m.id) === selectedModelId || m.name === selectedModelId
      );
      const modelDisplayName = selectedModel?.displayName || selectedModel?.name || selectedModelId;

      // Call API to update embedding model for all indices
      const indexNameList = indexNamesToUpdate.split(",").filter(Boolean);
      for (const idxName of indexNameList) {
        await knowledgeBaseService.updateEmbeddingModel(idxName.trim(), selectedModelId);
      }

      message.success(t("knowledgeBase.embeddingModel.updateSuccess"));
      // Save values before resetting state
      const completedModelId = selectedModelId;
      const completedModelDisplayName = modelDisplayName;
      log.info("[EmbeddingModelConfigDialog] API succeeded, about to call onConfigComplete. resetting local state and isSubmitting");
      // Reset local UI state only — do NOT call onClose() here.
      // Closing is handled exclusively by onConfigComplete to ensure
      // the parent has processed the result before the dialog unmounts.
      setSelectedModelId(null);
      setIsSubmitting(false);
      log.info("[EmbeddingModelConfigDialog] Calling onConfigComplete...");
      // Call onConfigComplete which handles closing and parent state updates
      onConfigComplete(indexNamesToUpdate, completedModelId, completedModelDisplayName);
      log.info("[EmbeddingModelConfigDialog] onConfigComplete returned");
    } catch (error) {
      log.error("[EmbeddingModelConfigDialog] API failed:", error);
      message.error(
        error instanceof Error ? error.message : t("knowledgeBase.embeddingModel.updateFailed")
      );
      log.info("[EmbeddingModelConfigDialog] isSubmitting set to false after error");
      setIsSubmitting(false);
    }
  };

  // Handle cancel
  const handleCancel = () => {
    log.info("[EmbeddingModelConfigDialog] handleCancel called, isSubmitting:", isSubmitting);
    if (isSubmitting) return;
    setSelectedModelId(null);
    setIsSubmitting(false);
    onClose();
  };

  // Get dialog title based on mode
  const getDialogTitle = () => {
    if (isModelMismatch) {
      return t("knowledgeBase.embeddingModel.modelMismatchTitle");
    }
    return t("knowledgeBase.embeddingModel.configRequiredTitle");
  };

  // Get dialog description based on mode
  const getDialogDescription = () => {
    if (isModelMismatch) {
      return t("knowledgeBase.embeddingModel.mismatchDescription");
    }
    return t("knowledgeBase.embeddingModel.configDescription", {
      name: knowledgeBaseName,
    });
  };

  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <ExclamationCircleFilled style={{ color: "#faad14", fontSize: 20 }} />
          <span>{getDialogTitle()}</span>
        </div>
      }
      open={isOpen}
      onCancel={handleCancel}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      onOk={handleSubmit}
      confirmLoading={isSubmitting}
      okButtonProps={{
        disabled: !selectedModelId,
      }}
      cancelButtonProps={{
        disabled: isSubmitting,
      }}
      centered
    >
      <div className="py-4">
        <p className="mb-4 text-gray-600">{getDialogDescription()}</p>

        {modelsLoading ? (
          <div className="flex items-center justify-center py-8">
            <Spin />
          </div>
        ) : embeddingModels.length === 0 ? (
          <div className="text-center py-4">
            <p className="text-gray-500 mb-2">
              {t("knowledgeBase.embeddingModel.noModelsAvailable")}
            </p>
            <p className="text-gray-400 text-sm">
              {t("knowledgeBase.embeddingModel.noModelsAvailableDesc")}
            </p>
          </div>
        ) : (
          <div className="mb-4">
            <label className="block mb-2 text-sm font-medium text-gray-700">
              {t("knowledgeBase.embeddingModel.selectPlaceholder")}
            </label>
            <Select
              className="w-full"
              placeholder={t("knowledgeBase.embeddingModel.selectPlaceholder")}
              value={selectedModelId}
              onChange={handleModelChange}
              showSearch
              optionFilterProp="children"
              filterOption={(input, option) =>
                (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
              }
              options={embeddingModels.map((model) => ({
                value: String(model.id),
                label: model.displayName || model.name,
              }))}
            />
          </div>
        )}

        {kbIdsToUpdate.length > 1 && (
          <p className="text-gray-500 text-sm mt-4">
            {t("knowledgeBase.embeddingModel.batchUpdateNote", {
              count: kbIdsToUpdate.length,
            })}
          </p>
        )}
      </div>
    </Modal>
  );
}
