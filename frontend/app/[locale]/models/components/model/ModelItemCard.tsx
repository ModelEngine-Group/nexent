"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Card, Tag, Tooltip, Button, Space, Empty } from "antd";
import { PenLine, Trash2 } from "lucide-react";

import { MODEL_TYPES, MODEL_STATUS, MODEL_SOURCES } from "@/const/modelConfig";
import { publicAsset } from "@/lib/publicAsset";
import {
  ModelConnectStatus,
  ModelOption,
  ModelSource,
  ModelType,
} from "@/types/modelConfig";

export interface ModelItemCardProps {
  model: ModelOption;
  isDefaultFor?: string[];
  onVerify: (displayName: string, type: ModelType) => void;
  onEdit: (model: ModelOption) => void;
  onDelete: (model: ModelOption) => void;
  canUpdate?: boolean;
}

/* ---------- Status styles ---------- */
const PULSE_ANIMATION = `
  @keyframes modelCardPulse {
    0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(41, 128, 185, 0.7); }
    70% { transform: scale(1); box-shadow: 0 0 0 5px rgba(41, 128, 185, 0); }
    100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(41, 128, 185, 0); }
  }
`;

const CONNECT_STATUS_COLORS: Record<ModelConnectStatus | "default", string> = {
  [MODEL_STATUS.AVAILABLE]: "#52c41a",
  [MODEL_STATUS.UNAVAILABLE]: "#ff4d4f",
  [MODEL_STATUS.CHECKING]: "#2980b9",
  [MODEL_STATUS.UNCHECKED]: "#95a5a6",
  default: "#17202a",
};

const getStatusDotStyle = (
  status?: ModelConnectStatus
): React.CSSProperties => {
  const color =
    (status && CONNECT_STATUS_COLORS[status]) ||
    CONNECT_STATUS_COLORS.default;
  const base: React.CSSProperties = {
    width: 10,
    height: 10,
    borderRadius: "50%",
    backgroundColor: color,
    boxShadow: `0 0 4px ${color}`,
    display: "inline-block",
    cursor: "pointer",
    flexShrink: 0,
  };
  if (status === MODEL_STATUS.CHECKING) {
    return { ...base, animation: "modelCardPulse 1.5s infinite" };
  }
  return base;
};

/* ---------- Model type colors & icons ---------- */
const getModelMeta = (type: ModelType) => {
  switch (type) {
    case MODEL_TYPES.LLM:
      return { emoji: "🤖", bg: "bg-blue-50", text: "text-blue-600" };
    case MODEL_TYPES.EMBEDDING:
      return { emoji: "🔢", bg: "bg-green-50", text: "text-green-600" };
    case MODEL_TYPES.MULTI_EMBEDDING:
      return { emoji: "🖼️", bg: "bg-teal-50", text: "text-teal-600" };
    case MODEL_TYPES.RERANK:
      return { emoji: "🔍", bg: "bg-purple-50", text: "text-purple-600" };
    case MODEL_TYPES.VLM:
    case MODEL_TYPES.VLM2:
    case MODEL_TYPES.VLM3:
      return { emoji: "👁️", bg: "bg-yellow-50", text: "text-yellow-600" };
    case MODEL_TYPES.STT:
      return { emoji: "🎤", bg: "bg-red-50", text: "text-red-600" };
    case MODEL_TYPES.TTS:
      return { emoji: "🔊", bg: "bg-pink-50", text: "text-pink-600" };
    default:
      return { emoji: "⚙️", bg: "bg-gray-50", text: "text-gray-600" };
  }
};

/* ---------- Source colors & icons ---------- */
const getSourceMeta = (source: ModelSource) => {
  switch (source) {
    case MODEL_SOURCES.SILICON:
      return {
        label: "SiliconFlow",
        bg: "bg-purple-50",
        text: "text-purple-600",
        icon: <img src={publicAsset("/siliconflow.png")} alt="" className="w-5 h-5" />,
      };
    case MODEL_SOURCES.MODELENGINE:
      return {
        label: "ModelEngine",
        bg: "bg-blue-50",
        text: "text-blue-600",
        icon: (
          <img
            src={publicAsset("/modelengine-logo.png")}
            alt=""
            className="w-5 h-5"
          />
        ),
      };
    case MODEL_SOURCES.OPENAI:
      return {
        label: "OpenAI",
        bg: "bg-indigo-50",
        text: "text-indigo-600",
        icon: <span className="text-sm leading-none">🏷️</span>,
      };
    case MODEL_SOURCES.OPENAI_API_COMPATIBLE:
    case MODEL_SOURCES.CUSTOM:
      return {
        label: "Custom",
        bg: "bg-rose-50",
        text: "text-rose-600",
        icon: <span className="text-sm leading-none">🛠️</span>,
      };
    case MODEL_SOURCES.DASHSCOPE:
      return {
        label: "DashScope",
        bg: "bg-orange-50",
        text: "text-orange-600",
        icon: (
          <img src={publicAsset("/aliyuncs.png")} alt="" className="w-5 h-5" />
        ),
      };
    case MODEL_SOURCES.TOKENPONY:
      return {
        label: "TokenPony",
        bg: "bg-cyan-50",
        text: "text-cyan-600",
        icon: (
          <img src={publicAsset("/tokenpony.png")} alt="" className="w-5 h-5" />
        ),
      };
    case MODEL_SOURCES.VOLCENGINE:
      return {
        label: "VolcEngine",
        bg: "bg-pink-50",
        text: "text-pink-600",
        icon: (
          <img src={publicAsset("/volcengine.png")} alt="" className="w-5 h-5" />
        ),
      };
    default:
      return {
        label: "Unknown",
        bg: "bg-gray-50",
        text: "text-gray-600",
        icon: <span className="text-sm leading-none">⚙️</span>,
      };
  }
};

/* ---------- i18n helpers ---------- */
const modelTypeI18n: Record<ModelType, string> = {
  [MODEL_TYPES.LLM]: "model.type.llm",
  [MODEL_TYPES.EMBEDDING]: "model.type.embedding",
  [MODEL_TYPES.MULTI_EMBEDDING]: "model.type.multiEmbedding",
  [MODEL_TYPES.RERANK]: "model.type.rerank",
  [MODEL_TYPES.VLM]: "model.type.imageUnderstanding",
  [MODEL_TYPES.VLM2]: "model.type.imageGeneration",
  [MODEL_TYPES.VLM3]: "model.type.videoUnderstanding",
  [MODEL_TYPES.STT]: "model.type.stt",
  [MODEL_TYPES.TTS]: "model.type.tts",
} as Record<ModelType, string>;

const slotLabelMap: Record<string, string> = {
  "llm.main": "modelConfig.option.mainModel",
  "embedding.embedding": "modelConfig.option.embeddingModel",
  "embedding.multi_embedding": "modelConfig.option.multiEmbeddingModel",
  "reranker.reranker": "modelConfig.option.rerankerModel",
  "multimodal.vlm": "modelConfig.option.imageUnderstandingModel",
  "multimodal.vlm2": "modelConfig.option.imageGenerationModel",
  "multimodal.vlm3": "modelConfig.option.videoUnderstandingModel",
  "voice.tts": "modelConfig.option.ttsModel",
  "voice.stt": "modelConfig.option.sttModel",
};

const statusI18n: Record<ModelConnectStatus | "default", string> = {
  [MODEL_STATUS.AVAILABLE]: "model.status.available",
  [MODEL_STATUS.UNAVAILABLE]: "model.status.unavailable",
  [MODEL_STATUS.CHECKING]: "model.status.detecting",
  [MODEL_STATUS.UNCHECKED]: "model.status.notDetected",
  default: "model.status.notDetected",
};

const fmtNum = (n?: number | null): string => {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1000 === 0 ? 0 : 1)}K`;
  return String(n);
};

/* ---------- Component ---------- */
export const ModelItemCard = ({
  model,
  isDefaultFor = [],
  onVerify,
  onEdit,
  onDelete,
  canUpdate = true,
}: ModelItemCardProps) => {
  const { t } = useTranslation();

  const modelMeta = useMemo(() => getModelMeta(model.type), [model.type]);
  const sourceMeta = useMemo(() => getSourceMeta(model.source), [model.source]);
  const status = (model.connect_status ||
    MODEL_STATUS.UNCHECKED) as ModelConnectStatus;
  const statusColor =
    CONNECT_STATUS_COLORS[status] || CONNECT_STATUS_COLORS.default;

  const contextWindow = model.contextWindowTokens ?? model.maxTokens;
  const maxOut = model.maxOutputTokens;
  const maxIn = model.maxInputTokens;
  const reserve = model.defaultOutputReserveTokens;

  const statusTooltip = t("model.status.clickToVerify", {
    defaultValue: "点击重新校验连通性",
  });
  const statusText = t(statusI18n[status] ?? statusI18n.default, {
    defaultValue: status,
  });
  const typeLabel = t(modelTypeI18n[model.type] ?? "model.type.unknown", {
    defaultValue: model.type,
  });

  // Ensure @keyframes is injected once
  const pulseStyle = (
    <style dangerouslySetInnerHTML={{ __html: PULSE_ANIMATION }} />
  );

  return (
    <Card
      variant="outlined"
      styles={{ body: { padding: 12 } }}
      style={{ height: "100%", display: "flex", flexDirection: "column" }}
      hoverable
    >
      {pulseStyle}

      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 18, lineHeight: 1 }}>{modelMeta.emoji}</span>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            minWidth: 0,
            flex: 1,
          }}
        >
          <div
            style={{
              fontWeight: 600,
              fontSize: 14,
              color: "#1f2937",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              maxWidth: "100%",
            }}
            title={model.displayName || model.name}
          >
            {model.displayName || model.name}
          </div>
        </div>
        {isDefaultFor.length > 0 && (
          <Tooltip
            title={isDefaultFor
              .map((s) => t(slotLabelMap[s] ?? s, { defaultValue: s }))
              .join(" / ")}
          >
            <Tag color="blue" style={{ margin: 0, whiteSpace: "nowrap" }}>
              {t("modelConfig.tag.default", { defaultValue: "默认" })}
            </Tag>
          </Tooltip>
        )}
        <Tooltip title={statusTooltip}>
          <span
            onClick={() => onVerify(model.displayName || model.name, model.type)}
            style={getStatusDotStyle(status)}
          />
        </Tooltip>
      </div>

      {/* Sub line: real model name + source icon */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 10,
          minWidth: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center" }}>
          {sourceMeta.icon}
        </div>
        <div
          style={{
            fontSize: 12,
            color: "#8892a6",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            flex: 1,
            minWidth: 0,
          }}
          title={model.name}
        >
          {model.name}
        </div>
      </div>

      {/* Tags: model type + source */}
      <div style={{ marginBottom: 10, display: "flex", flexWrap: "wrap", gap: 4 }}>
        <Tag
          color={
            MODEL_TYPES.LLM === model.type
              ? "blue"
              : MODEL_TYPES.EMBEDDING === model.type
                ? "green"
                : MODEL_TYPES.MULTI_EMBEDDING === model.type
                  ? "teal"
                  : MODEL_TYPES.RERANK === model.type
                    ? "purple"
                    : MODEL_TYPES.VLM === model.type ||
                        MODEL_TYPES.VLM2 === model.type ||
                        MODEL_TYPES.VLM3 === model.type
                      ? "gold"
                      : MODEL_TYPES.STT === model.type
                        ? "red"
                        : MODEL_TYPES.TTS === model.type
                          ? "magenta"
                          : "default"
          }
          style={{ margin: 0 }}
        >
          {typeLabel}
        </Tag>
        <Tag style={{ margin: 0 }}>{sourceMeta.label}</Tag>
      </div>

      {/* Specs */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "4px 8px",
          marginBottom: 10,
          fontSize: 12,
          color: "#64748b",
          flex: 1,
        }}
      >
        <div>
          <span style={{ color: "#94a3b8", marginRight: 4 }}>
            {t("modelConfig.spec.contextWindow", { defaultValue: "上下文" })}
          </span>
          <strong style={{ color: "#0f172a" }}>{fmtNum(contextWindow)}</strong>
        </div>
        <div>
          <span style={{ color: "#94a3b8", marginRight: 4 }}>
            {t("modelConfig.spec.maxOutput", { defaultValue: "最大输出" })}
          </span>
          <strong style={{ color: "#0f172a" }}>{fmtNum(maxOut)}</strong>
        </div>
        {maxIn != null && maxIn > 0 && (
          <div>
            <span style={{ color: "#94a3b8", marginRight: 4 }}>
              {t("modelConfig.spec.maxInput", { defaultValue: "最大输入" })}
            </span>
            <strong style={{ color: "#0f172a" }}>{fmtNum(maxIn)}</strong>
          </div>
        )}
        {reserve != null && reserve > 0 && (
          <div>
            <span style={{ color: "#94a3b8", marginRight: 4 }}>
              {t("modelConfig.spec.outputReserve", {
                defaultValue: "输出预留",
              })}
            </span>
            <strong style={{ color: "#0f172a" }}>{fmtNum(reserve)}</strong>
          </div>
        )}
      </div>

      {/* Footer: status text + actions */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingTop: 8,
          borderTop: "1px dashed #e5e7eb",
        }}
      >
        <span style={{ fontSize: 12, color: statusColor, fontWeight: 500 }}>
          ● {statusText}
        </span>
        {canUpdate ? (
          <Space size={4}>
            <Tooltip
              title={t("modelConfig.button.editModel", { defaultValue: "编辑" })}
            >
              <Button
                type="text"
                size="small"
                icon={<PenLine size={14} />}
                onClick={() => onEdit(model)}
              />
            </Tooltip>
            <Tooltip
              title={t("modelConfig.button.deleteModel", {
                defaultValue: "删除",
              })}
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<Trash2 size={14} />}
                onClick={() => onDelete(model)}
              />
            </Tooltip>
          </Space>
        ) : (
          <div style={{ width: 56 }} />
        )}
      </div>
    </Card>
  );
};

export default ModelItemCard;
