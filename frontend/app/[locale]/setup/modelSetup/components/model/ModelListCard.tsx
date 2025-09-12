"use strict";
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Select, Tooltip, Tag } from 'antd'
import { CloseOutlined } from '@ant-design/icons'

import { MODEL_TYPES, MODEL_STATUS } from '@/const/modelConfig'
import { ModelConnectStatus, ModelOption, ModelSource, ModelType } from '@/types/modelConfig'
import log from "@/lib/logger";

// Unified management of model connection status colors
const CONNECT_STATUS_COLORS: Record<ModelConnectStatus | 'default', string> = {
  [MODEL_STATUS.AVAILABLE]: "#52c41a",
  [MODEL_STATUS.UNAVAILABLE]: "#ff4d4f",
  [MODEL_STATUS.CHECKING]: "#2980b9",
  [MODEL_STATUS.UNCHECKED]: "#95a5a6",
  default: "#17202a"
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
  const color = (status && CONNECT_STATUS_COLORS[status]) || CONNECT_STATUS_COLORS.default;
  const baseStyle: React.CSSProperties = {
    width: 'clamp(8px, 1.5vw, 12px)',
    height: 'clamp(8px, 1.5vw, 12px)',
    aspectRatio: '1/1',
    borderRadius: '50%',
    display: 'inline-block',
    marginRight: '4px',
    cursor: 'pointer',
    transition: 'all 0.2s ease',
    position: 'relative',
    flexShrink: 0,
    flexGrow: 0,
    backgroundColor: color,
    boxShadow: `0 0 3px ${color}`,
  };
  if (status === "detecting") {
    return {
      ...baseStyle,
      animation: 'pulse 1.5s infinite',
      // Pass animation color through CSS variables
      ['--pulse-color' as any]: color
    };
  }
  return baseStyle;
};

// Get tag styles corresponding to model source
const getSourceTagStyle = (source: string): React.CSSProperties => {
  const baseStyle: React.CSSProperties = {
    marginRight: '4px',
    fontSize: '12px',
    lineHeight: '16px',
    padding: '0 6px',
    borderRadius: '10px',
  };
  
  if (source === "ModelEngine") {
    return {
      ...baseStyle,
      color: '#1890ff',
      backgroundColor: '#e6f7ff',
      borderColor: '#91d5ff',
    };
  } else if (source === "自定义" || source === "Custom") {
    return {
      ...baseStyle,
      color: '#722ed1',
      backgroundColor: '#f9f0ff',
      borderColor: '#d3adf7',
    };
  } else {
    return {
      ...baseStyle,
      color: '#595959',
      backgroundColor: '#fafafa',
      borderColor: '#d9d9d9',
    };
  }
};

const { Option } = Select

interface ModelListCardProps {
  type: ModelType
  modelId: string
  modelTypeName: string
  selectedModel: string
  onModelChange: (value: string) => void
  officialModels: ModelOption[]
  customModels: ModelOption[]
  onVerifyModel?: (modelName: string, modelType: ModelType) => void // New callback for verifying models
  errorFields?: {[key: string]: boolean} // New error field state
}

export const ModelListCard = ({
  type,
  modelId,
  modelTypeName,
  selectedModel,
  onModelChange,
  officialModels,
  customModels,
  onVerifyModel,
  errorFields
}: ModelListCardProps) => {
  const { t } = useTranslation()

  // Add model list state for updates
  const [modelsData, setModelsData] = useState({
    official: [...officialModels],
    custom: [...customModels]
  });

  // Create a style element in the component containing animation definitions
  useEffect(() => {
    // Create style element
    const styleElement = document.createElement('style');
    styleElement.type = 'text/css';
    styleElement.innerHTML = PULSE_ANIMATION;
    document.head.appendChild(styleElement);

    // Cleanup function, remove style element when component unmounts
    return () => {
      document.head.removeChild(styleElement);
    };
  }, []);

  // When getting model list, need to consider specific option type
  const getModelsBySource = (): { official: ModelOption[]; custom: ModelOption[] } => {
    // Each type only shows models of corresponding type
    return {
      official: modelsData.official.filter(model => model.type === type),
      custom: modelsData.custom.filter(model => model.type === type)
    }
  }

  // Get model source
  const getModelSource = (displayName: string): string => {
    if (type === MODEL_TYPES.TTS || type === MODEL_TYPES.STT || type === MODEL_TYPES.VLM) {
      const modelOfType = modelsData.custom.find((m) => m.type === type && m.displayName === displayName)
      if (modelOfType) return t('model.source.custom')
    }

    const officialModel = modelsData.official.find((m) => m.type === type && m.name === displayName)
    if (officialModel) return t('model.source.modelEngine')

    const customModel = modelsData.custom.find((m) => m.type === type && m.displayName === displayName)
    return customModel ? t('model.source.custom') : t('model.source.unknown')
  }

  const modelsBySource = getModelsBySource()

  // Local update model status
  const updateLocalModelStatus = (displayName: string, status: ModelConnectStatus) => {
    setModelsData(prevData => {
      // Find model to update
      const modelToUpdate = prevData.custom.find(m => m.displayName === displayName && m.type === type);
      
      if (!modelToUpdate) {
        log.warn(t('model.warning.updateNotFound', { displayName, type }));
        return prevData;
      }
      
      const updatedCustomModels = prevData.custom.map(model => {
        if (model.displayName === displayName && model.type === type) {
          return {
            ...model,
            connect_status: status
          };
        }
        return model;
      });
      
      return {
        official: prevData.official,
        custom: updatedCustomModels
      };
    });
  };

  // When parent component's model list updates, update local state
  useEffect(() => {
    // Update local state but don't trigger fetchModelsStatus
    setModelsData(prevData => {
      const updatedOfficialModels = officialModels.map(model => {
        // Preserve existing connect_status if it exists
        const existingModel = prevData.official.find(m => m.name === model.name && m.type === model.type);
        return {
          ...model,
          connect_status: existingModel?.connect_status || MODEL_STATUS.AVAILABLE as ModelConnectStatus
        };
      });
      
      const updatedCustomModels = customModels.map(model => {
        // Prioritize using newly passed status to reflect latest backend state
        return {
          ...model,
          connect_status: model.connect_status || MODEL_STATUS.UNCHECKED as ModelConnectStatus
        };
      });
      
      return {
        official: updatedOfficialModels,
        custom: updatedCustomModels
      };
    });
  }, [officialModels, customModels, type, modelId]);

  // Handle status indicator click event
  const handleStatusClick = (e: React.MouseEvent, displayName: string) => {
    e.stopPropagation(); // Prevent event bubbling
    e.preventDefault(); // Prevent default behavior
    e.nativeEvent.stopImmediatePropagation(); // Prevent all sibling event handlers
    
    if (onVerifyModel && displayName) {
      // First update local state to "checking"
      updateLocalModelStatus(displayName, MODEL_STATUS.CHECKING);
      // Then call verification function
      onVerifyModel(displayName, type);
    }
    
    return false; // Ensure no further bubbling
  };

  return (
    <div>
      <div className="font-medium mb-1.5 flex items-center justify-between">
        <div className="flex items-center">
          {modelTypeName}
          {(modelTypeName === t('model.type.main')) && (
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
        placeholder={t('model.select.placeholder')}
        value={selectedModel || undefined}
        onChange={onModelChange}
        allowClear={{ 
          clearIcon: <CloseOutlined />,
        }}
        onClear={() => onModelChange("")}
        size="middle"
        onClick={(e) => e.stopPropagation()}
        getPopupContainer={(triggerNode) => triggerNode.parentNode as HTMLElement}
        status={errorFields && errorFields[`${type}.${modelId}`] ? "error" : ""}
        className={errorFields && errorFields[`${type}.${modelId}`] ? "error-select" : ""}
      >
        {modelsBySource.official.length > 0 && (
          <Select.OptGroup label={t('model.group.modelEngine')}>
            {modelsBySource.official.map((model) => (
              <Option key={`${type}-${model.name}-official`} value={model.displayName}>
                <div className="flex items-center justify-between">
                  <div className="font-medium truncate" title={model.name}>
                    {model.displayName}
                  </div>
                </div>
              </Option>
            ))}
          </Select.OptGroup>
        )}
        {modelsBySource.custom.length > 0 && (
          <Select.OptGroup label={t('model.group.custom')}>
            {modelsBySource.custom.map((model) => (
              <Option key={`${type}-${model.displayName}-custom`} value={model.displayName}>
                <div className="flex items-center justify-between" style={{ minWidth: 0 }}>
                  <div className="font-medium truncate" style={{ flex: '1 1 auto', minWidth: 0 }} title={model.displayName}>
                    {model.displayName}
                  </div>
                  <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', marginLeft: '8px' }}>
                    <Tooltip title={t('model.status.tooltip')}>
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
  )
} 