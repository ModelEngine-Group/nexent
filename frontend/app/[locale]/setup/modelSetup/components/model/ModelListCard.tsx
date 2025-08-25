"use strict";
import { Select, Tooltip, Tag } from 'antd'
import { CloseOutlined } from '@ant-design/icons'
import { ModelConnectStatus, ModelOption, ModelSource, ModelType } from '@/types/config'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

// 统一管理模型连接状态颜色
const CONNECT_STATUS_COLORS: Record<ModelConnectStatus | 'default', string> = {
  "available": "#52c41a",
  "unavailable": "#ff4d4f",
  "detecting": "#2980b9",
  "not_detected": "#95a5a6",
  default: "#17202a"
};

// 动画定义不再包含颜色，由样式传递
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

// 只拼接样式，颜色和动画通过参数传递
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
      // 用CSS变量传递动画色
      ['--pulse-color' as any]: color
    };
  }
  return baseStyle;
};

// 获取模型来源对应的标签样式
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
  onVerifyModel?: (modelName: string, modelType: ModelType) => void // 新增验证模型的回调
  errorFields?: {[key: string]: boolean} // 新增错误字段状态
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

  // 添加模型列表状态，用于更新
  const [modelsData, setModelsData] = useState({
    official: [...officialModels],
    custom: [...customModels]
  });

  // 在组件中创建一个style元素，包含动画定义
  useEffect(() => {
    // 创建style元素
    const styleElement = document.createElement('style');
    styleElement.type = 'text/css';
    styleElement.innerHTML = PULSE_ANIMATION;
    document.head.appendChild(styleElement);

    // 清理函数，组件卸载时移除style元素
    return () => {
      document.head.removeChild(styleElement);
    };
  }, []);

  // 获取模型列表时需要考虑具体的选项类型
  const getModelsBySource = (): Record<ModelSource, ModelOption[]> => {
    // 每种类型只显示对应类型的模型
    return {
      official: modelsData.official.filter(model => model.type === type),
      custom: modelsData.custom.filter(model => model.type === type)
    }
  }

  // 获取模型来源
  const getModelSource = (displayName: string): string => {
    if (type === 'tts' || type === 'stt' || type === 'vlm') {
      const modelOfType = modelsData.custom.find((m) => m.type === type && m.displayName === displayName)
      if (modelOfType) return t('model.source.custom')
    }

    const officialModel = modelsData.official.find((m) => m.type === type && m.name === displayName)
    if (officialModel) return t('model.source.modelEngine')

    const customModel = modelsData.custom.find((m) => m.type === type && m.displayName === displayName)
    return customModel ? t('model.source.custom') : t('model.source.unknown')
  }

  const modelsBySource = getModelsBySource()

  // 本地更新模型状态
  const updateLocalModelStatus = (displayName: string, status: ModelConnectStatus) => {
    setModelsData(prevData => {
      // 查找要更新的模型
      const modelToUpdate = prevData.custom.find(m => m.displayName === displayName && m.type === type);
      
      if (!modelToUpdate) {
        console.warn(t('model.warning.updateNotFound', { displayName, type }));
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

  // 当父组件传入的模型列表更新时，更新本地状态
  useEffect(() => {
    // 更新本地状态，但不触发fetchModelsStatus
    setModelsData(prevData => {
      const updatedOfficialModels = officialModels.map(model => {
        // 保留已有的connect_status，如果存在的话
        const existingModel = prevData.official.find(m => m.name === model.name && m.type === model.type);
        return {
          ...model,
          connect_status: existingModel?.connect_status || "available" as ModelConnectStatus
        };
      });
      
      const updatedCustomModels = customModels.map(model => {
        // 优先使用新传入的状态，这样能反映后端的最新状态
        return {
          ...model,
          connect_status: model.connect_status || "not_detected" as ModelConnectStatus
        };
      });
      
      return {
        official: updatedOfficialModels,
        custom: updatedCustomModels
      };
    });
  }, [officialModels, customModels, type, modelId]);

  // 处理状态指示灯点击事件
  const handleStatusClick = (e: React.MouseEvent, displayName: string) => {
    e.stopPropagation(); // 阻止事件冒泡
    e.preventDefault(); // 阻止默认行为
    e.nativeEvent.stopImmediatePropagation(); // 阻止所有同级事件处理程序
    
    if (onVerifyModel && displayName) {
      // 先更新本地状态为"检测中"
      updateLocalModelStatus(displayName, "detecting");
      // 然后调用验证函数
      onVerifyModel(displayName, type);
    }
    
    return false; // 确保不会继续冒泡
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