import React, { useRef, useState, useEffect } from 'react';
import { Input, Radio, ColorPicker, Button, Typography, Card, Col, Row, App } from 'antd';
import { useConfig } from '@/hooks/useConfig';
import { PlusOutlined } from '@ant-design/icons';
import { Pencil } from 'lucide-react';
import 'bootstrap-icons/font/bootstrap-icons.css';
import { useTranslation } from 'react-i18next';

import { generateAvatarUri } from '@/lib/avatar';
import { presetIcons, colorOptions } from "@/types/avatar"

import dynamic from 'next/dynamic';

const { TextArea } = Input;
const { Text } = Typography;

// 动态导入 Modal 组件以避免 SSR 水合错误
const DynamicModal = dynamic(() => import('antd/es/modal'), { ssr: false });

// 布局高度常量配置
const LAYOUT_CONFIG = {
  CARD_BODY_PADDING: "8px 20px",
}

// 卡片主题
const cardTheme = {
  borderColor: "#e6e6e6",
  backgroundColor: "#ffffff",
};

export const AppConfigSection: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { appConfig, updateAppConfig, getAppAvatarUrl } = useConfig();
  
  // 添加本地状态管理输入值
  const [localAppName, setLocalAppName] = useState(appConfig.appName);
  const [localAppDescription, setLocalAppDescription] = useState(appConfig.appDescription);
  
  // 添加错误状态管理
  const [appNameError, setAppNameError] = useState(false);

  // 添加用户输入状态跟踪
  const isUserTypingAppName = useRef(false);
  const isUserTypingDescription = useRef(false);
  const appNameUpdateTimer = useRef<NodeJS.Timeout | null>(null);
  const descriptionUpdateTimer = useRef<NodeJS.Timeout | null>(null);

  // 头像相关状态
  const [isAvatarModalOpen, setIsAvatarModalOpen] = useState(false);
  const [selectedIconKey, setSelectedIconKey] = useState<string>(presetIcons[0].key);
  const [tempIconKey, setTempIconKey] = useState<string>(presetIcons[0].key);
  const [tempColor, setTempColor] = useState<string>("#2689cb");
  const [avatarType, setAvatarType] = useState<"preset" | "custom">(appConfig.iconType);
  const [tempAvatarType, setTempAvatarType] = useState<"preset" | "custom">(appConfig.iconType);
  const [customAvatarUrl, setCustomAvatarUrl] = useState<string | null>(appConfig.customIconUrl);
  const [tempCustomAvatarUrl, setTempCustomAvatarUrl] = useState<string | null>(appConfig.customIconUrl);
  
  // 获取当前头像URL
  const avatarUrl = getAppAvatarUrl(60);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // 添加配置变化监听，当配置从后端加载后同步更新本地状态
  useEffect(() => {
    const handleConfigChanged = (event: any) => {
      const { config } = event.detail;
      if (config?.app) {
        // 只有在用户未正在输入时才更新状态
        if (!isUserTypingAppName.current) {
          setLocalAppName(config.app.appName || "");
        }
        if (!isUserTypingDescription.current) {
          setLocalAppDescription(config.app.appDescription || "");
        }
        setAvatarType(config.app.iconType || "preset");
        setCustomAvatarUrl(config.app.customIconUrl || null);
        
        // 重置错误状态
        if (config.app.appName && config.app.appName.trim()) {
          setAppNameError(false);
        }
      }
    };

    window.addEventListener('configChanged', handleConfigChanged);
    return () => {
      window.removeEventListener('configChanged', handleConfigChanged);
    };
  }, []);

  // 监听appConfig变化，同步更新本地状态
  useEffect(() => {
    // 只有在用户未正在输入时才更新状态
    if (!isUserTypingAppName.current) {
      setLocalAppName(appConfig.appName);
    }
    if (!isUserTypingDescription.current) {
      setLocalAppDescription(appConfig.appDescription);
    }
    setAvatarType(appConfig.iconType);
    setCustomAvatarUrl(appConfig.customIconUrl);
  }, [appConfig.appName, appConfig.appDescription, appConfig.iconType, appConfig.customIconUrl]);
  
  // 监听高亮缺失字段事件
  useEffect(() => {
    const handleHighlightMissingField = (event: any) => {
      const { field } = event.detail;
      if (field === 'appName') {
        setAppNameError(true);
        // 滚动到应用名称输入框
        const appNameInput = document.querySelector('.app-name-input');
        if (appNameInput) {
          appNameInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    };
    
    window.addEventListener('highlightMissingField', handleHighlightMissingField);
    return () => {
      window.removeEventListener('highlightMissingField', handleHighlightMissingField);
    };
  }, []);

  // 清理定时器
  useEffect(() => {
    return () => {
      if (appNameUpdateTimer.current) {
        clearTimeout(appNameUpdateTimer.current);
      }
      if (descriptionUpdateTimer.current) {
        clearTimeout(descriptionUpdateTimer.current);
      }
    };
  }, []);

  // Handle basic app config changes
  const handleAppNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newAppName = e.target.value;
    isUserTypingAppName.current = true;
    setLocalAppName(newAppName);
    
    // 如果输入了值，清除错误状态
    if (newAppName.trim()) {
      setAppNameError(false);
    }

    // 清除之前的定时器
    if (appNameUpdateTimer.current) {
      clearTimeout(appNameUpdateTimer.current);
    }

    // 设置防抖更新
    appNameUpdateTimer.current = setTimeout(() => {
      updateAppConfig({ appName: newAppName });
      isUserTypingAppName.current = false;
    }, 500);
  };

  const handleAppNameBlur = () => {
    // 清除定时器，立即更新
    if (appNameUpdateTimer.current) {
      clearTimeout(appNameUpdateTimer.current);
    }
    updateAppConfig({ appName: localAppName });
    isUserTypingAppName.current = false;
  };

  const handleDescriptionChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newDescription = e.target.value;
    isUserTypingDescription.current = true;
    setLocalAppDescription(newDescription);

    // 清除之前的定时器
    if (descriptionUpdateTimer.current) {
      clearTimeout(descriptionUpdateTimer.current);
    }

    // 设置防抖更新
    descriptionUpdateTimer.current = setTimeout(() => {
      updateAppConfig({ appDescription: newDescription });
      isUserTypingDescription.current = false;
    }, 500);
  };

  const handleDescriptionBlur = () => {
    // 清除定时器，立即更新
    if (descriptionUpdateTimer.current) {
      clearTimeout(descriptionUpdateTimer.current);
    }
    updateAppConfig({ appDescription: localAppDescription });
    isUserTypingDescription.current = false;
  };

  // 打开头像选择模态框
  const handleAvatarClick = () => {
    setTempIconKey(selectedIconKey);
    setTempAvatarType(avatarType);
    setTempCustomAvatarUrl(customAvatarUrl);
    setIsAvatarModalOpen(true);
  };

  // 处理图标选择
  const handleIconSelect = (iconKey: string) => {
    setTempIconKey(iconKey);
    setTempAvatarType("preset");
  };

  // 处理颜色选择
  const handleColorSelect = (color: string) => {
    setTempColor(color);
  };

  // 处理自定义图片上传
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.startsWith("image/")) {
        message.error(t('appConfig.upload.imageOnly'));
        return;
      }

      if (file.size > 2 * 1024 * 1024) {
        message.error(t('appConfig.upload.sizeLimit'));
        return;
      }

      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          setTempCustomAvatarUrl(event.target.result as string);
          setTempAvatarType("custom");
        }
      };
      reader.readAsDataURL(file);
    }
  };

  // 触发文件选择对话框
  const triggerFileUpload = () => {
    fileInputRef.current?.click();
  };

  // 确认头像选择
  const confirmAvatarSelection = async () => {
    try {
      setSelectedIconKey(tempIconKey);
      setAvatarType(tempAvatarType);
      setCustomAvatarUrl(tempAvatarType === "custom" ? tempCustomAvatarUrl : null);
      setIsAvatarModalOpen(false);

      if (tempAvatarType === "preset") {
        // 生成头像 URI 并保存
        const avatarUri = generateAvatarUri(tempIconKey, tempColor);
        
        updateAppConfig({
          iconType: "preset",
          customIconUrl: null,
          avatarUri: avatarUri
        });
      } else {
        updateAppConfig({
          iconType: "custom",
          customIconUrl: tempCustomAvatarUrl,
          avatarUri: tempCustomAvatarUrl || null
        });
      }
    } catch (error) {
      message.error(t('appConfig.icon.saveError'));
      console.error(t('appConfig.icon.saveErrorLog'), error);
    }
  };

  // 取消头像选择
  const cancelAvatarSelection = () => {
    setIsAvatarModalOpen(false);
    setTempCustomAvatarUrl(customAvatarUrl);
  };

  // 重构：风格被嵌入在组件内
  return (
    <div style={{ width: "100%", height: "85%" }}>
      <style>{`
        .color-picker-rounded [class*="ant-color-picker"] {
          border-radius: 10px !important;
        }
        .color-picker-rounded .ant-color-picker-presets-color {
          border-radius: 10px !important;
        }
        .bi {
          display: inline-block;
          font-size: 1.8rem;
        }
      `}</style>

      <Row gutter={[12, 12]} justify="center" style={{ height: "100%", marginLeft: "-30px" }}>
        <Col xs={24} md={24} lg={24} xl={24}>
          <Card
            variant="outlined"
            className="app-config-card"
            styles={{
              body: { padding: LAYOUT_CONFIG.CARD_BODY_PADDING}
            }}
            style={{
              minHeight: "300px",
              height: "100%",
              width: "calc(100% - 8px)",
              margin: "0 4px",
              backgroundColor: "#ffffff",
              border: `0px solid ${cardTheme.borderColor}`,
            }}
          >
            <div className="flex items-start justify-center mx-auto my-2" style={{ maxWidth: "95%" }}>
              <div className="mr-6 mt-1 relative group">
                <div 
                  className="h-[60px] w-[60px] rounded-full overflow-hidden cursor-pointer"
                  style={{ boxShadow: "0 4px 12px rgba(0,0,0,0.2)" }}
                  onClick={handleAvatarClick}
                >
                  <img 
                    src={avatarUrl} 
                    alt={appConfig.appName}
                    className="h-full w-full object-cover"
                  />
                </div>
                <div className="absolute -right-1 -bottom-1 bg-white rounded-full p-1 shadow-md opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer" onClick={handleAvatarClick}>
                  <Pencil className="h-3 w-3 text-gray-500" />
                </div>
              </div>
              <div className="flex-1">
                <div className="mb-4">
                  <div className="flex items-center mb-2 min-h-[24px]">
                    <Text className="text-base text-gray-700 font-bold">{t('appConfig.appName.label')}</Text>
                  </div>
                  <Input
                    placeholder={t('appConfig.appName.placeholder')}
                    value={localAppName}
                    onChange={handleAppNameChange}
                    onBlur={handleAppNameBlur}
                    className="h-10 text-md rounded-md app-name-input"
                    size="large"
                    status={appNameError ? "error" : ""}
                    style={appNameError ? { borderColor: "#ff4d4f" } : {}}
                  />
                </div>
                <div className="mb-1">
                  <div className="flex items-center mb-2 min-h-[24px]">
                    <Text className="text-base text-gray-700 font-bold">{t('appConfig.description.label')}</Text>
                  </div>
                  <TextArea
                    placeholder={t('appConfig.description.placeholder')}
                    value={localAppDescription}
                    onChange={handleDescriptionChange}
                    onBlur={handleDescriptionBlur}
                    className="text-md rounded-md"
                    autoSize={{ minRows: 15 }}
                    size="large"
                  />
                </div>
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      {isAvatarModalOpen && (
        <DynamicModal
          title={t('appConfig.icon.modalTitle')}
          open={isAvatarModalOpen}
          onCancel={cancelAvatarSelection}
          footer={[
            <Button key="submit" type="primary" onClick={confirmAvatarSelection}>
              {t('common.confirm')}
            </Button>,
          ]}
          destroyOnClose={true}
          width={520}
          centered
        >
          <div className="mb-4">
            <Radio.Group
              value={tempAvatarType}
              onChange={(e) => setTempAvatarType(e.target.value)}
              className="mb-4"
            >
              <Radio.Button value="preset">{t('appConfig.icon.preset')}</Radio.Button>
              <Radio.Button value="custom">{t('appConfig.icon.custom')}</Radio.Button>
            </Radio.Group>
          </div>

          {tempAvatarType === "preset" && (
            <div>
              <div className="mb-3">
                <div className="text-sm font-medium text-gray-500 mb-2">
                  <Text>{t('appConfig.icon.selectIcon')}</Text>
                </div>
                <div className="grid grid-cols-5 gap-3">
                  {presetIcons.map((iconOption) => (
                    <div
                      key={iconOption.key}
                      className={`p-3 flex justify-center items-center rounded-md cursor-pointer ${
                        tempIconKey === iconOption.key
                          ? "bg-blue-50 border border-blue-300"
                          : "border border-gray-200 hover:border-gray-300"
                      }`}
                      onClick={() => handleIconSelect(iconOption.key)}
                    >
                      <i className={`bi bi-${iconOption.icon}`} style={{ color: "#273746" }}></i>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-sm font-medium text-gray-500 mb-2">
                  <Text>{t('appConfig.icon.selectColor')}</Text>
                </div>
                <div className="flex items-center w-full">
                  <ColorPicker
                    value={tempColor}
                    onChange={(color) => handleColorSelect(color.toHexString())}
                    showText
                    disabledAlpha={true}
                    presets={[
                      {
                        label: t('appConfig.icon.presetColors'),
                        colors: colorOptions as any,
                      }
                    ]}
                    panelRender={(panel) => (
                      <div className="color-picker-rounded">
                        {panel}
                      </div>
                    )}
                    styles={{
                      popupOverlayInner: {
                        width: 'auto',
                      }
                    }}
                    className="color-picker-rounded"
                  />
                </div>
              </div>

              <div>
                <div className="text-sm font-medium text-gray-500 mb-2 mt-4">
                  <Text>{t('appConfig.icon.preview')}</Text>
                </div>
                <div className="mt-4 flex justify-center">
                  <div 
                    className="h-[60px] w-[60px] rounded-full overflow-hidden"
                    style={{ boxShadow: "0 4px 12px rgba(0,0,0,0.2)" }}
                  >
                    {tempAvatarType === "preset" ? (
                      <img 
                        src={generateAvatarUri(tempIconKey, tempColor)} 
                        alt={t('appConfig.icon.previewAlt')}
                        className="h-full w-full object-cover"
                      />
                    ) : tempCustomAvatarUrl && (
                      <img 
                        src={tempCustomAvatarUrl} 
                        alt={t('appConfig.icon.previewAlt')}
                        className="h-full w-full object-cover"
                      />
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {tempAvatarType === "custom" && (
            <div className="flex flex-col items-center">
              {tempCustomAvatarUrl ? (
                <div className="mb-4 text-center flex flex-col items-center">
                  <div 
                    className="h-[120px] w-[120px] rounded-full overflow-hidden"
                    style={{ boxShadow: "0 4px 12px rgba(0,0,0,0.2)" }}
                  >
                    <img 
                      src={tempCustomAvatarUrl}
                      alt={t('appConfig.icon.customAlt')}
                      className="h-full w-full object-cover"
                    />
                  </div>
                  <Button 
                    type="text" 
                    danger 
                    className="mt-4"
                    onClick={() => setTempCustomAvatarUrl(null)}
                  >
                    {t('appConfig.icon.removeImage')}
                  </Button>
                </div>
              ) : (
                <div 
                  className="w-32 h-32 border-2 border-dashed border-gray-300 rounded-md flex items-center justify-center cursor-pointer hover:border-blue-500"
                  onClick={triggerFileUpload}
                >
                  <div className="text-center">
                    <PlusOutlined style={{ fontSize: '24px', color: '#8c8c8c' }} />
                    <p className="mt-2 text-gray-500">{t('appConfig.icon.uploadHint')}</p>
                  </div>
                </div>
              )}
              
              <input
                type="file"
                ref={fileInputRef}
                style={{ display: "none" }}
                accept="image/*"
                onChange={handleFileUpload}
              />
              
              <div className="text-xs text-gray-500 mt-2">
                <Text>{t('appConfig.icon.uploadTip')}</Text>
              </div>
            </div>
          )}
        </DynamicModal>
      )}
    </div>
  );
}; 