"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Modal, Card, Space, App } from "antd";

import {
  MODEL_TYPES,
  LAYOUT_CONFIG,
  CARD_THEMES,
} from "@/const/modelConfig";
import { ModelOption, ModelType } from "@/types/modelConfig";

import { ModelListCard } from "./ModelListCard";

export interface DefaultModelDialogProps {
  open: boolean;
  models: ModelOption[];
  selectedModels: Record<string, Record<string, string>>;
  errorFields: { [key: string]: boolean };
  onClose: () => void;
  onChange: (
    category: string,
    option: string,
    displayName: string
  ) => Promise<void>;
  onVerifyModel?: (modelName: string, type: ModelType) => void;
}

type ModelDataShape = Record<
  string,
  { title: string; options: { id: string; name: string }[] }
>;

const CARD_KEYS = ["llm", "embedding", "reranker", "multimodal", "voice"] as const;
type CardKey = (typeof CARD_KEYS)[number];

const getModelData = (t: any): ModelDataShape => ({
  llm: {
    title: t("modelConfig.category.llm", { defaultValue: "大语言模型" }),
    options: [
      {
        id: "main",
        name: t("modelConfig.option.mainModel", { defaultValue: "主模型" }),
      },
    ],
  },
  embedding: {
    title: t("modelConfig.category.embedding", { defaultValue: "嵌入模型" }),
    options: [
      {
        id: MODEL_TYPES.EMBEDDING,
        name: t("modelConfig.option.embeddingModel", {
          defaultValue: "文本嵌入",
        }),
      },
      {
        id: MODEL_TYPES.MULTI_EMBEDDING,
        name: t("modelConfig.option.multiEmbeddingModel", {
          defaultValue: "多模态嵌入",
        }),
      },
    ],
  },
  reranker: {
    title: t("modelConfig.category.reranker", { defaultValue: "重排模型" }),
    options: [
      {
        id: "reranker",
        name: t("modelConfig.option.rerankerModel", {
          defaultValue: "重排模型",
        }),
      },
    ],
  },
  multimodal: {
    title: t("modelConfig.category.multimodal", { defaultValue: "多模态模型" }),
    options: [
      {
        id: MODEL_TYPES.VLM,
        name: t("modelConfig.option.imageUnderstandingModel", {
          defaultValue: "图像理解",
        }),
      },
      {
        id: MODEL_TYPES.VLM2,
        name: t("modelConfig.option.imageGenerationModel", {
          defaultValue: "图像生成",
        }),
      },
      {
        id: MODEL_TYPES.VLM3,
        name: t("modelConfig.option.videoUnderstandingModel", {
          defaultValue: "视频理解",
        }),
      },
    ],
  },
  voice: {
    title: t("modelConfig.category.voice", { defaultValue: "语音模型" }),
    options: [
      {
        id: MODEL_TYPES.TTS,
        name: t("modelConfig.option.ttsModel", { defaultValue: "语音合成" }),
      },
      {
        id: MODEL_TYPES.STT,
        name: t("modelConfig.option.sttModel", { defaultValue: "语音识别" }),
      },
    ],
  },
});

const resolveModelType = (
  key: string,
  optionId: string
): ModelType => {
  if (key === "voice") {
    return optionId === MODEL_TYPES.TTS ? MODEL_TYPES.TTS : MODEL_TYPES.STT;
  }
  if (key === "reranker") return MODEL_TYPES.RERANK;
  if (key === "multimodal") return optionId as ModelType;
  if (key === MODEL_TYPES.EMBEDDING) {
    return optionId === MODEL_TYPES.MULTI_EMBEDDING
      ? MODEL_TYPES.MULTI_EMBEDDING
      : MODEL_TYPES.EMBEDDING;
  }
  return key as ModelType;
};

export const DefaultModelDialog = ({
  open,
  models,
  selectedModels,
  errorFields,
  onClose,
  onChange,
  onVerifyModel,
}: DefaultModelDialogProps) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const modelData = useMemo(() => getModelData(t), [t]);

  const handleOk = () => {
    message.success(
      t("modelConfig.message.defaultModelUpdated", {
        defaultValue: "默认模型已更新",
      })
    );
    onClose();
  };

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600 }}>
          {t("modelConfig.button.setDefaultModels", {
            defaultValue: "设置默认模型",
          })}
        </span>
      }
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText={t("common.save", { defaultValue: "保存" })}
      cancelText={t("common.cancel", { defaultValue: "取消" })}
      width={820}
      destroyOnHidden
      styles={{ body: { paddingTop: 16 } }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: LAYOUT_CONFIG.CARD_GAP,
        }}
      >
        {(Object.entries(modelData) as [CardKey, (typeof modelData)[CardKey]][]).map(
          ([key, category]) => {
            const theme =
              CARD_THEMES[key as keyof typeof CARD_THEMES] ??
              CARD_THEMES.default;
            return (
              <Card
                key={key}
                variant="outlined"
                title={
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      margin: "-12px -24px",
                      padding: LAYOUT_CONFIG.CARD_HEADER_PADDING,
                      paddingBottom: 12,
                      backgroundColor: theme.backgroundColor,
                      borderBottom: `1px solid ${theme.borderColor}`,
                      height: LAYOUT_CONFIG.HEADER_HEIGHT - 12,
                    }}
                  >
                    <h5
                      style={{
                        margin: 0,
                        marginLeft: LAYOUT_CONFIG.MODEL_TITLE_MARGIN_LEFT,
                        fontSize: 14,
                        lineHeight: "32px",
                      }}
                    >
                      {category.title}
                    </h5>
                  </div>
                }
                styles={{
                  body: {
                    padding: LAYOUT_CONFIG.CARD_BODY_PADDING,
                  },
                }}
              >
                <Space
                  orientation="vertical"
                  style={{ width: "100%" }}
                  size={12}
                >
                  {category.options.map((option) => (
                    <ModelListCard
                      key={option.id}
                      type={resolveModelType(key, option.id)}
                      modelId={option.id}
                      modelTypeName={option.name}
                      selectedModel={
                        selectedModels[key]?.[option.id] || ""
                      }
                      onModelChange={(modelName) =>
                        onChange(key, option.id, modelName)
                      }
                      models={models}
                      onVerifyModel={onVerifyModel}
                      errorFields={errorFields}
                    />
                  ))}
                </Space>
              </Card>
            );
          }
        )}
      </div>
    </Modal>
  );
};

export default DefaultModelDialog;
