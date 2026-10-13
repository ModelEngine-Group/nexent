"use client";

import { Button, Modal } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

interface KnowledgeModelMismatchModalProps {
  open: boolean;
  info: {
    existingModel: string;
    newModel: string;
    existingKBName: string;
    newKBName: string;
  } | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export function KnowledgeModelMismatchModal({
  open,
  info,
  onCancel,
  onConfirm,
}: KnowledgeModelMismatchModalProps) {
  const { t } = useTranslation();
  return (
    <Modal
      open={open}
      onCancel={onCancel}
      title={
        <div className="flex items-center gap-2">
          <ExclamationCircleOutlined
            style={{ color: "#faad14", fontSize: 20 }}
          />
          <span>
            {t(
              "toolConfig.knowledgeBaseSelector.modelMismatch.title",
              "模型不匹配"
            )}
          </span>
        </div>
      }
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel")}
        </Button>,
        <Button key="confirm" type="primary" danger onClick={onConfirm}>
          {t(
            "toolConfig.knowledgeBaseSelector.modelMismatch.switchModel",
            "切换模型"
          )}
        </Button>,
      ]}
    >
      <div className="py-4">
        <p className="mb-4 text-gray-600">
          {t(
            "toolConfig.knowledgeBaseSelector.modelMismatch.description",
            "所选知识库的向量化模型与其他已选知识库不一致。"
          )}
        </p>
        {info && (
          <div className="space-y-3 rounded-lg bg-gray-50 p-4">
            <div className="flex items-start">
              <span className="w-20 shrink-0 text-gray-500">
                {t(
                  "toolConfig.knowledgeBaseSelector.modelMismatch.existing",
                  "已选知识库"
                )}
                :
              </span>
              <div className="flex-1">
                <div className="font-medium text-gray-800">
                  {info.existingKBName}
                </div>
                <div className="text-sm text-gray-500">
                  {t(
                    "toolConfig.knowledgeBaseSelector.modelMismatch.model",
                    "模型"
                  )}
                  : {info.existingModel}
                </div>
              </div>
            </div>
            <div className="flex items-start">
              <span className="w-20 shrink-0 text-gray-500">
                {t(
                  "toolConfig.knowledgeBaseSelector.modelMismatch.new",
                  "新选择"
                )}
                :
              </span>
              <div className="flex-1">
                <div className="font-medium text-gray-800">
                  {info.newKBName}
                </div>
                <div className="text-sm text-gray-500">
                  {t(
                    "toolConfig.knowledgeBaseSelector.modelMismatch.model",
                    "模型"
                  )}
                  : {info.newModel}
                </div>
              </div>
            </div>
          </div>
        )}
        <p className="mt-4 text-sm text-gray-500">
          {t(
            "toolConfig.knowledgeBaseSelector.modelMismatch.hint",
            "提示：向量化模型不一致的知识库可能无法同时用于检索，建议选择相同模型的知识库。"
          )}
        </p>
      </div>
    </Modal>
  );
}
