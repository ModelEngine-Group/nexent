"use strict";
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Select, Tooltip, Tag } from 'antd'
import { CloseOutlined } from '@ant-design/icons'

import { MODEL_TYPES, MODEL_STATUS } from '@/const/modelConfig'
import {
  getProviderIconByUrl,
  getOfficialProviderIcon,
} from "@/services/modelService";
import {
  ModelConnectStatus,
  ModelOption,
  ModelType,
} from "@/types/modelConfig";
import log from "@/lib/logger";

// Unified management of model connection status colors
const CONNECT_STATUS_COLORS: Record<ModelConnectStatus | "default", string> = {
  [MODEL_STATUS.AVAILABLE]: "#52c41a",
  [MODEL_STATUS.UNAVAILABLE]: "#ff4d4f",
  [MODEL_STATUS.CHECKING]: "#2980b9",
  [MODEL_STATUS.UNCHECKED]: "#95a5a6",
  default: "#17202a",
};

// Animation definition no longer includes colors, passed through styles
const PULSE_ANIMATION = `
  @keyframes pulse {
    0% {
      transform: scale(0.95);
      box-shadow: 0 0 0 0 rgba(41, 128, 185, 0.7);
    }
    
    70% {
      transform: scale(1);
      box-shadow: 0 0 0 5px rgba(41, 128, 185, 0);
    }
    
    100% {
      transform: scale(0.95);
      box-shadow: 0 0 0 0 rgba(41, 128, 185, 0);
    }
  }
`;

// Only concatenate styles, colors and animations passed through parameters
const getStatusStyle = (status?: ModelConnectStatus): React.CSSProperties => {
  const color =
    (status && CONNECT_STATUS_COLORS[status]) || CONNECT_STATUS_COLORS.default;
  const baseStyle: React.CSSProperties = {
    width: "clamp(8px, 1.5vw, 12px)",
    height: "clamp(8px, 1.5vw, 12px)",
    aspectRatio: "1/1",
    borderRadius: "50%",
    display: "inline-block",
    marginRight: "4px",
    cursor: "pointer",
    transition: "all 0.2s ease",
    position: "relative",
    flexShrink: 0,
    flexGrow: 0,
    backgroundColor: color,
    boxShadow: `0 0 3px ${color}`,
  };
  if (status === "detecting") {
    return {
      ...baseStyle,
      animation: "pulse 1.5s infinite",
      // Pass animation color through CSS variables
      ["--pulse-color" as any]: color,
    };
  }
  return baseStyle;
};

// Get tag styles corresponding to model source
const getSourceTagStyle = (source: string): React.CSSProperties => {
  const baseStyle: React.CSSProperties = {
    marginRight: "4px",
    fontSize: "12px",
    lineHeight: "16px",
    padding: "0 6px",
    borderRadius: "10px",
  };

  if (source === "ModelEngine") {
    return {
      ...baseStyle,
      color: "#1890ff",
      backgroundColor: "#e6f7ff",
      borderColor: "#91d5ff",
    };
  } else if (source === "自定义" || source === "Custom") {
    return {
      ...baseStyle,
      color: "#722ed1",
      backgroundColor: "#f9f0ff",
      borderColor: "#d3adf7",
    };
  } else {
    return {
      ...baseStyle,
      color: "#595959",
      backgroundColor: "#fafafa",
      borderColor: "#d9d9d9",
    };
  }
};

const { Option } = Select;

interface ModelListCardProps {
  type: ModelType;
  modelId: string;
  modelTypeName: string;
  selectedModel: string;
  onModelChange: (value: string) => void;
  models: ModelOption[];
  onVerifyModel?: (modelName: string, modelType: ModelType) => void;
  errorFields?: { [key: string]: boolean };
}

export const ModelListCard = ({
  type,
  modelId,
  modelTypeName,
  selectedModel,
  onModelChange,
  models,
  onVerifyModel,
  errorFields,
}: ModelListCardProps) => {
  const { t } = useTranslation();

  // Add model list state for updates
  const [modelsData, setModelsData] = useState<ModelOption[]>([...models]);

  // Create a style element in the component containing animation definitions
  useEffect(() => {
    // Create style element
    const styleElement = document.createElement("style");
    styleElement.type = "text/css";
    styleElement.innerHTML = PULSE_ANIMATION;
    document.head.appendChild(styleElement);

    // Cleanup function, remove style element when component unmounts
    return () => {
      document.head.removeChild(styleElement);
    };
  }, []);

  // Get filtered models by type
  const getFilteredModels = (): ModelOption[] => {
    return modelsData.filter((model) => model.type === type);
  };

  // Get model source label based on source field
  const getModelSource = (displayName: string): string => {
    const model = modelsData.find(
      (m) => m.type === type && m.displayName === displayName
    );
    
    if (!model) return t("model.source.unknown");
    
    // Return source label based on model.source
    if (model.source === "modelengine") {
      return t("model.source.modelEngine");
    } else if (model.source === "silicon") {
      return t("model.source.silicon");
    } else if (model.source === "OpenAI-API-Compatible") {
      return t("model.source.custom");
    }
    
    return t("model.source.unknown");
  };

  const filteredModels = getFilteredModels();
  
  // Group models by source for display
  const groupedModels = {
    modelengine: filteredModels.filter((m) => m.source === "modelengine"),
    silicon: filteredModels.filter((m) => m.source === "silicon"),
    custom: filteredModels.filter((m) => m.source === "OpenAI-API-Compatible"),
  };

  // When parent component's model list updates, update local state
  useEffect(() => {
    setModelsData(models);
  }, [models]);

  // Handle status indicator click event
  const handleStatusClick = (e: React.MouseEvent, displayName: string) => {
    e.stopPropagation(); // Prevent event bubbling
    e.preventDefault(); // Prevent default behavior
    e.nativeEvent.stopImmediatePropagation(); // Prevent all sibling event handlers

    if (onVerifyModel && displayName) {
      // Call verification function (parent component will update status)
      onVerifyModel(displayName, type);
    }

    return false; // Ensure no further bubbling
  };

  return (
    <div>
      <div className="font-medium mb-1.5 flex items-center justify-between">
        <div className="flex items-center">
          {modelTypeName}
          {modelTypeName === t("model.type.main") && (
            <span className="text-red-500 ml-1">*</span>
          )}
        </div>
        {selectedModel && (
          <div className="flex items-center">
            <Tag style={getSourceTagStyle(getModelSource(selectedModel))}>
              {getModelSource(selectedModel)}
            </Tag>
          </div>
        )}
      </div>
      <Select
        style={{
          width: "100%",
        }}
        placeholder={t("model.select.placeholder")}
        value={selectedModel || undefined}
        onChange={(value) => {
          // Prevent duplicate onChange calls by checking if value actually changed
          if (value !== selectedModel) {
            onModelChange(value || "");
          }
        }}
        allowClear={{
          clearIcon: <CloseOutlined />,
        }}
        size="middle"
        onClick={(e) => e.stopPropagation()}
        getPopupContainer={(triggerNode) =>
          triggerNode.parentNode as HTMLElement
        }
        status={errorFields && errorFields[`${type}.${modelId}`] ? "error" : ""}
        className={
          errorFields && errorFields[`${type}.${modelId}`] ? "error-select" : ""
        }
      >
        {groupedModels.modelengine.length > 0 && (
          <Select.OptGroup label={t("model.group.modelEngine")}>
            {groupedModels.modelengine.map((model) => (
              <Option
                key={`${type}-${model.name}-modelengine`}
                value={model.displayName}
              >
                <div
                  className="flex items-center justify-between"
                  style={{ minWidth: 0 }}
                >
                  <div
                    className="flex items-center font-medium truncate"
                    style={{ flex: "1 1 auto", minWidth: 0 }}
                    title={model.displayName}
                  >
                    <img
                      src={getOfficialProviderIcon()}
                      alt="provider"
                      className="w-4 h-4 rounded mr-2 flex-shrink-0"
                    />
                    <span className="truncate">{model.displayName}</span>
                  </div>
                  <div
                    style={{
                      flex: "0 0 auto",
                      display: "flex",
                      alignItems: "center",
                      marginLeft: "8px",
                    }}
                  >
                    <Tooltip title={t("model.status.tooltip")}>
                      <span
                        onClick={(e) => handleStatusClick(e, model.displayName)}
                        onMouseDown={(e: React.MouseEvent) => {
                          e.stopPropagation();
                          e.preventDefault();
                        }}
                        style={getStatusStyle(model.connect_status)}
                        className="status-indicator"
                      />
                    </Tooltip>
                  </div>
                </div>
              </Option>
            ))}
          </Select.OptGroup>
        )}
        {groupedModels.silicon.length > 0 && (
          <Select.OptGroup label={t("model.group.silicon")}>
            {groupedModels.silicon.map((model) => (
              <Option
                key={`${type}-${model.displayName}-silicon`}
                value={model.displayName}
              >
                <div
                  className="flex items-center justify-between"
                  style={{ minWidth: 0 }}
                >
                  <div
                    className="flex items-center font-medium truncate"
                    style={{ flex: "1 1 auto", minWidth: 0 }}
                    title={model.displayName}
                  >
                    <img
                      src={getProviderIconByUrl(model.apiUrl)}
                      alt="provider"
                      className="w-4 h-4 rounded mr-2 flex-shrink-0"
                    />
                    <span className="truncate">{model.displayName}</span>
                  </div>
                  <div
                    style={{
                      flex: "0 0 auto",
                      display: "flex",
                      alignItems: "center",
                      marginLeft: "8px",
                    }}
                  >
                    <Tooltip title={t("model.status.tooltip")}>
                      <span
                        onClick={(e) => handleStatusClick(e, model.displayName)}
                        onMouseDown={(e: React.MouseEvent) => {
                          e.stopPropagation();
                          e.preventDefault();
                        }}
                        style={getStatusStyle(model.connect_status)}
                        className="status-indicator"
                      />
                    </Tooltip>
                  </div>
                </div>
              </Option>
            ))}
          </Select.OptGroup>
        )}
        {groupedModels.custom.length > 0 && (
          <Select.OptGroup label={t("model.group.custom")}>
            {groupedModels.custom.map((model) => (
              <Option
                key={`${type}-${model.displayName}-custom`}
                value={model.displayName}
              >
                <div
                  className="flex items-center justify-between"
                  style={{ minWidth: 0 }}
                >
                  <div
                    className="flex items-center font-medium truncate"
                    style={{ flex: "1 1 auto", minWidth: 0 }}
                    title={model.displayName}
                  >
                    <img
                      src={getProviderIconByUrl(model.apiUrl)}
                      alt="provider"
                      className="w-4 h-4 rounded mr-2 flex-shrink-0"
                    />
                    <span className="truncate">{model.displayName}</span>
                  </div>
                  <div
                    style={{
                      flex: "0 0 auto",
                      display: "flex",
                      alignItems: "center",
                      marginLeft: "8px",
                    }}
                  >
                    <Tooltip title={t("model.status.tooltip")}>
                      <span
                        onClick={(e) => handleStatusClick(e, model.displayName)}
                        onMouseDown={(e: React.MouseEvent) => {
                          e.stopPropagation();
                          e.preventDefault();
                        }}
                        style={getStatusStyle(model.connect_status)}
                        className="status-indicator"
                      />
                    </Tooltip>
                  </div>
                </div>
              </Option>
            ))}
          </Select.OptGroup>
        )}
      </Select>
    </div>
  );
}; 