import {Button, Card, Col, Row, Space, Modal, App} from 'antd'
import {
  PlusOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
  EditOutlined
} from '@ant-design/icons'
import {forwardRef, useEffect, useImperativeHandle, useState, useRef, ReactNode} from 'react'
import {ModelOption, ModelType} from '@/types/config'
import {useConfig} from '@/hooks/useConfig'
import {modelService} from '@/services/modelService'
import {configService} from '@/services/configService'
import {configStore} from '@/lib/config'
import {ModelListCard} from './model/ModelListCard'
import {ModelAddDialog} from './model/ModelAddDialog'
import {ModelDeleteDialog} from './model/ModelDeleteDialog'
import { useTranslation } from 'react-i18next'

// 布局高度常量配置
const LAYOUT_CONFIG = {
  CARD_HEADER_PADDING: "10px 24px",
  CARD_BODY_PADDING: "12px 20px",
  MODEL_TITLE_MARGIN_LEFT: "0px",
  HEADER_HEIGHT: 57, // Card标题高度
  BUTTON_AREA_HEIGHT: 48, // 按钮区域高度
  CARD_GAP: 12, // Row的gutter
}

// 定义每个卡片的主题色
const cardThemes = {
  llm: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  embedding: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  reranker: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  multimodal: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  voice: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
}

// 添加ModelConnectStatus的类型定义
const MODEL_STATUS = {
  AVAILABLE: "可用",
  UNAVAILABLE: "不可用",
  CHECKING: "检测中",
  UNCHECKED: "未检测"
} as const;

type ModelConnectStatus = typeof MODEL_STATUS[keyof typeof MODEL_STATUS];

// 模型数据结构
const getModelData = (t: any) => ({
  llm: {
    title: t('modelConfig.category.llm'),
    options: [
      { id: "main", name: t('modelConfig.option.mainModel') },
      { id: "secondary", name: t('modelConfig.option.secondaryModel') },
    ],
  },
  embedding: {
    title: t('modelConfig.category.embedding'),
    options: [
      { id: "embedding", name: t('modelConfig.option.embeddingModel') },
      { id: "multi_embedding", name: t('modelConfig.option.multiEmbeddingModel') },
    ],
  },
  reranker: {
    title: t('modelConfig.category.reranker'),
    options: [
      { id: "reranker", name: t('modelConfig.option.rerankerModel') },
    ],
  },
  multimodal: {
    title: t('modelConfig.category.multimodal'),
    options: [
      { id: "vlm", name: t('modelConfig.option.vlmModel') },
    ],
  },
  voice: {
    title: t('modelConfig.category.voice'),
    options: [
      { id: "tts", name: t('modelConfig.option.ttsModel') },
      { id: "stt", name: t('modelConfig.option.sttModel') },
    ],
  },
})

// 定义组件对外暴露的方法类型
export interface ModelConfigSectionRef {
  verifyModels: () => Promise<void>;
  getSelectedModels: () => Record<string, Record<string, string>>;
}

interface ModelConfigSectionProps {
  skipVerification?: boolean;
}

export const ModelConfigSection = forwardRef<ModelConfigSectionRef, ModelConfigSectionProps>((props, ref): ReactNode => {
  const { t } = useTranslation()
  const { message } = App.useApp();
  const { skipVerification = false } = props;
  const { modelConfig, updateModelConfig } = useConfig()
  const modelData = getModelData(t)

  // 状态管理
  const [officialModels, setOfficialModels] = useState<ModelOption[]>([])
  const [customModels, setCustomModels] = useState<ModelOption[]>([])
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
  const [isSyncing, setIsSyncing] = useState(false)
  const [isVerifying, setIsVerifying] = useState(false)

  // 错误状态管理
  const [errorFields, setErrorFields] = useState<{[key: string]: boolean}>({
    'llm.main': false,
    'embedding.embedding': false,
    'embedding.multi_embedding': false
  })

  // 用于取消API请求的控制器
  const abortControllerRef = useRef<AbortController | null>(null);
  // 节流计时器
  const throttleTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 模型选择状态
  const [selectedModels, setSelectedModels] = useState<Record<string, Record<string, string>>>({
    llm: { main: "", secondary: "" },
    embedding: { embedding: "", multi_embedding: "" },
    reranker: { reranker: "" },
    multimodal: { vlm: "" },
    voice: { tts: "", stt: "" },
  })

  // 初始化加载
  useEffect(() => {
    // 在组件加载时先从后端加载配置，然后再加载模型列表
    const fetchData = async () => {
      const loadConfigResult = await configService.loadConfigToFrontend();

      await configStore.reloadFromStorage();

      await loadModelLists(true);
    };

    fetchData();
  }, [skipVerification])

  // 监听字段错误高亮事件
  useEffect(() => {
    const handleHighlightMissingField = (event: any) => {
      const { field } = event.detail;

      if (field === 'llm.main' || field === 'embedding.embedding') {
        setErrorFields(prev => ({
          ...prev,
          [field]: true
        }));

        // 找到对应的卡片并滚动到视图
        setTimeout(() => {
          const fieldParts = field.split('.');
          const cardType = fieldParts[0];
          const cardId = fieldParts[1];

          const selector = cardType === 'embedding'
            ? '.model-card:nth-child(2)'
            : '.model-card:nth-child(1)';

          const card = document.querySelector(selector);
          if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }, 100);
      }
    };

    window.addEventListener('highlightMissingField', handleHighlightMissingField);
    return () => {
      window.removeEventListener('highlightMissingField', handleHighlightMissingField);
    };
  }, []);

  // 暴露方法给父组件
  useImperativeHandle(ref, () => ({
    verifyModels,
    getSelectedModels: () => selectedModels
  }));

  // 加载模型列表
  const loadModelLists = async (skipVerify: boolean = false) => {
    const modelConfig = configStore.getConfig().models;
    
    try {
      const [official, custom] = await Promise.all([
        modelService.getOfficialModels(),
        modelService.getCustomModels()
      ])

      // 确保所有官方模型状态为"可用"
      const officialWithStatus = official.map(model => ({
        ...model,
        connect_status: MODEL_STATUS.AVAILABLE
      }));

      // 更新状态
      setOfficialModels(officialWithStatus)
      setCustomModels(custom)

      // 合并所有可用模型列表（官方和自定义）
      const allModels = [...officialWithStatus, ...custom]
      
      // 从配置中加载选中的模型，并检查模型是否仍然存在
      const llmMain = modelConfig.llm.displayName
      const llmMainExists = llmMain ? allModels.some(m => m.displayName === llmMain && m.type === 'llm') : true

      const llmSecondary = modelConfig.llmSecondary.displayName
      const llmSecondaryExists = llmSecondary ? allModels.some(m => m.displayName === llmSecondary && m.type === 'llm') : true

      const embedding = modelConfig.embedding.displayName
      const embeddingExists = embedding ? allModels.some(m => m.displayName === embedding && m.type === 'embedding') : true

      const multiEmbedding = modelConfig.multiEmbedding.displayName
      const multiEmbeddingExists = multiEmbedding ? allModels.some(m => m.displayName === multiEmbedding && m.type === 'multi_embedding') : true

      const rerank = modelConfig.rerank.displayName
      const rerankExists = rerank ? allModels.some(m => m.displayName === rerank && m.type === 'rerank') : true

      const vlm = modelConfig.vlm.displayName
      const vlmExists = vlm ? allModels.some(m => m.displayName === vlm && m.type === 'vlm') : true

      const stt = modelConfig.stt.displayName
      const sttExists = stt ? allModels.some(m => m.displayName === stt && m.type === 'stt') : true

      const tts = modelConfig.tts.displayName
      const ttsExists = tts ? allModels.some(m => m.displayName === tts && m.type === 'tts') : true

      // 创建更新后的选中模型对象
      const updatedSelectedModels = {
        llm: {
          main: llmMainExists ? llmMain : "",
          secondary: llmSecondaryExists ? llmSecondary : ""
        },
        embedding: {
          embedding: embeddingExists ? embedding : "",
          multi_embedding: multiEmbeddingExists ? multiEmbedding : ""
        },
        reranker: {
          reranker: rerankExists ? rerank : ""
        },
        multimodal: {
          vlm: vlmExists ? vlm : ""
        },
        voice: {
          tts: ttsExists ? tts : "",
          stt: sttExists ? stt : ""
        },
      }

      // 更新状态
      setSelectedModels(updatedSelectedModels)

      // 如果有模型被删除，同步更新本地存储的配置
      const configUpdates: any = {}

      if (!llmMainExists && llmMain) {
        configUpdates.llm = { modelName: "", displayName: "", apiConfig: { apiKey: "", modelUrl: "" } }
      }

      if (!llmSecondaryExists && llmSecondary) {
        configUpdates.llmSecondary = { modelName: "", displayName: "", apiConfig: { apiKey: "", modelUrl: "" } }
      }

      if (!embeddingExists && embedding) {
        configUpdates.embedding = { modelName: "", displayName: "", apiConfig: { apiKey: "", modelUrl: "" } }
      }

      if (!multiEmbeddingExists && multiEmbedding) {
        configUpdates.multiEmbedding = { modelName: "", displayName: "", apiConfig: { apiKey: "", modelUrl: "" } }
      }

      if (!rerankExists && rerank) {
        configUpdates.rerank = { modelName: "", displayName: "" }
      }

      if (!vlmExists && vlm) {
        configUpdates.vlm = { modelName: "", displayName: "" }
      }

      if (!sttExists && stt) {
        configUpdates.stt = { modelName: "", displayName: "" }
      }

      if (!ttsExists && tts) {
        configUpdates.tts = { modelName: "", displayName: "" }
      }

      // 如果有配置需要更新，则更新localStorage
      if (Object.keys(configUpdates).length > 0) {
        updateModelConfig(configUpdates)
      }

      // 检查是否有已配置的模型需要验证连通性
      const hasConfiguredModels =
        !!modelConfig.llm.modelName ||
        !!modelConfig.llmSecondary.modelName ||
        !!modelConfig.embedding.modelName ||
        !!modelConfig.multiEmbedding.modelName ||
        !!modelConfig.rerank.modelName ||
        !!modelConfig.vlm.modelName ||
        !!modelConfig.tts.modelName ||
        !!modelConfig.stt.modelName;

      // 直接在这里进行验证，而不是使用setTimeout
      // 这样确保我们使用的是当前函数作用域中的模型数据，而不是依赖状态更新
      if (officialWithStatus.length > 0 || custom.length > 0) {
        if (hasConfiguredModels && !skipVerify) {
          // 调用内部验证函数，传入模型数据和最新的选中模型信息
          verifyModelsInternal(officialWithStatus, custom, updatedSelectedModels);
        }
      }
    } catch (error) {
      console.error(t('modelConfig.error.loadList'), error)
      message.error(t('modelConfig.error.loadListFailed'))
    }
  }

  // 内部验证函数，接收模型数据作为参数，不依赖状态
  const verifyModelsInternal = async (
    officialData: ModelOption[],
    customData: ModelOption[],
    modelsToCheck?: Record<string, Record<string, string>> // 可选参数，允许传入最新的选中模型
  ) => {
    // 如果已经在验证中，则不重复执行
    if (isVerifying) {
      return;
    }

    // 确保模型数据已经加载
    if (officialData.length === 0 && customData.length === 0) {
      return;
    }

    // 使用传入的模型选择数据或当前状态
    const currentSelectedModels = modelsToCheck || selectedModels;

    // 检查是否有选中的模型需要验证
    let hasSelectedModels = false;
    for (const category in currentSelectedModels) {
      for (const optionId in currentSelectedModels[category]) {
        if (currentSelectedModels[category][optionId]) {
          hasSelectedModels = true;
          break;
        }
      }
      if (hasSelectedModels) break;
    }

    // 如果状态中没有选中的模型，则尝试从配置中直接获取
    if (!hasSelectedModels) {
      // 直接检查配置中每个模型是否存在
      const hasLlmMain = !!modelConfig.llm.modelName;
      const hasLlmSecondary = !!modelConfig.llmSecondary.modelName;
      const hasEmbedding = !!modelConfig.embedding.modelName;
      const hasReranker = !!modelConfig.rerank.modelName;
      const hasVlm = !!modelConfig.vlm.modelName;
      const hasTts = !!modelConfig.tts.modelName;
      const hasStt = !!modelConfig.stt.modelName;

      hasSelectedModels = hasLlmMain || hasLlmSecondary || hasEmbedding || hasReranker || hasVlm || hasTts || hasStt;

      if (hasSelectedModels) {
        // 使用配置中的模型覆盖当前选中模型
        currentSelectedModels.llm.main = modelConfig.llm.modelName;
        currentSelectedModels.llm.secondary = modelConfig.llmSecondary.modelName;
        currentSelectedModels.embedding.embedding = modelConfig.embedding.modelName;
        currentSelectedModels.embedding.multi_embedding = modelConfig.multiEmbedding.modelName || "";
        currentSelectedModels.reranker.reranker = modelConfig.rerank.modelName;
        currentSelectedModels.multimodal.vlm = modelConfig.vlm.modelName;
        currentSelectedModels.voice.tts = modelConfig.tts.modelName;
        currentSelectedModels.voice.stt = modelConfig.stt.modelName;
      } else {
        return;
      }
    }

    setIsVerifying(true)

    // 准备一个新的AbortController
    const abortController = new AbortController();
    const signal = abortController.signal;

    // 保存引用以便可以取消
    abortControllerRef.current = abortController;

    try {
      // 准备需要验证的模型列表
      const modelsToVerify: Array<{
        category: string,
        optionId: string,
        modelName: string,
        modelType: ModelType,
        isOfficialModel: boolean
      }> = [];

      // 收集所有需要验证的模型，使用传入的选中模型数据
      for (const [category, options] of Object.entries(currentSelectedModels)) {
        for (const [optionId, modelName] of Object.entries(options)) {
          if (!modelName) continue;

          let modelType = category as ModelType;
          if (category === "voice") {
            modelType = optionId === "tts" ? "tts" : "stt";
          } else if (category === "reranker") {
            modelType = "rerank";
          } else if (category === "multimodal") {
            modelType = "vlm";
          } else if (category === "embedding") {
            modelType = optionId === "multi_embedding" ? "multi_embedding" : "embedding";
          }

          // 查找模型在officialData或customData中
          const isOfficialModel = officialData.some(model => model.name === modelName && model.type === modelType);

          // 将模型添加到待验证列表
          modelsToVerify.push({
            category,
            optionId,
            modelName,
            modelType,
            isOfficialModel
          });

          // 只更新自定义模型状态为"检测中"，官方模型始终为"可用"
          if (!isOfficialModel) {
            updateCustomModelStatus(modelName, modelType, MODEL_STATUS.CHECKING);
          }
        }
      }

      // 如果没有模型需要验证，显示提示并返回
      if (modelsToVerify.length === 0) {
        message.info({ content: "没有需要验证的模型", key: "verifying" });
        setIsVerifying(false);
        abortControllerRef.current = null;
        return;
      }

      // 并行验证所有模型
      await Promise.all(
        modelsToVerify.map(async ({ modelName, modelType, isOfficialModel }) => {
          // 根据模型来源调用不同的验证方式
          let isConnected = false;

          if (isOfficialModel) {
            // 官方模型，始终视为"可用"
            isConnected = true;
          } else {
            // 自定义模型，使用modelService验证
            try {
              isConnected = await modelService.verifyCustomModel(modelName, signal);

              // 更新模型状态
              updateCustomModelStatus(modelName, modelType, isConnected ? MODEL_STATUS.AVAILABLE : MODEL_STATUS.UNAVAILABLE);
            } catch (error: any) {
              // 检查是否是因为请求被取消
              if (error.name === 'AbortError') {
                return;
              }

              console.error(`校验自定义模型 ${modelName} 失败:`, error);
              updateCustomModelStatus(modelName, modelType, MODEL_STATUS.UNAVAILABLE);
            }
          }
        })
      );

    } catch (error: any) {
      // 检查是否是因为请求被取消
      if (error.name === 'AbortError') {
        console.log('校验被用户取消');
        return;
      }

      console.error("模型校验失败:", error);
    } finally {
      if (!signal.aborted) {
        setIsVerifying(false);
        abortControllerRef.current = null;
      }
    }
  }

  // 验证所有选中的模型
  const verifyModels = async () => {
    // 如果已经在验证中，则不重复执行
    if (isVerifying) {
      return;
    }

    // 确保模型数据已经加载
    if (officialModels.length === 0 && customModels.length === 0) {
      // 模型数据尚未加载，跳过验证
      return;
    }

    // 调用内部验证函数
    await verifyModelsInternal(officialModels, customModels, selectedModels);
  }

  // 同步模型列表
  const handleSyncModels = async () => {
    setIsSyncing(true)
    try {
      await loadModelLists(true)
      message.success(t('modelConfig.message.syncSuccess'))
    } catch (error) {
      console.error(t('modelConfig.error.syncFailed'), error)
      message.error(t('modelConfig.error.syncFailed'))
    } finally {
      setIsSyncing(false)
    }
  }

  // 验证单个模型连接状态 (添加节流逻辑)
  const verifyOneModel = async (displayName: string, modelType: ModelType) => {
    // 如果是空模型名，直接返回
    if (!displayName) return;

    // 查找模型在officialModels或customModels中
    const isOfficialModel = officialModels.some(model => model.displayName === displayName && model.type === modelType);

    // 官方模型始终视为"可用"
    if (isOfficialModel) return;

    // 如果正在节流中，清除之前的定时器
    if (throttleTimerRef.current) {
      clearTimeout(throttleTimerRef.current);
    }

    // 使用节流，延迟1s再执行验证，避免频繁切换模型时重复验证
    throttleTimerRef.current = setTimeout(async () => {
      // 更新自定义模型状态为"检测中"
      updateCustomModelStatus(displayName, modelType, MODEL_STATUS.CHECKING);

      try {
        // 使用modelService验证自定义模型
        const isConnected = await modelService.verifyCustomModel(displayName);

        // 更新模型状态
        updateCustomModelStatus(
          displayName, 
          modelType, 
          isConnected ? MODEL_STATUS.AVAILABLE : MODEL_STATUS.UNAVAILABLE
        );
      } catch (error: any) {
        console.error(t('modelConfig.error.verifyCustomModel', { model: displayName }), error);
        updateCustomModelStatus(displayName, modelType, MODEL_STATUS.UNAVAILABLE);
      } finally {
        throttleTimerRef.current = null;
      }
    }, 1000);
  }

  // 处理模型变更
  const handleModelChange = async (category: string, option: string, displayName: string) => {
    // 更新选中的模型
    setSelectedModels(prev => ({
      ...prev,
      [category]: {
        ...prev[category],
        [option]: displayName,
      }
    }))

    console.log(`handleModelChange: ${category}, ${option}, ${displayName}`)

    // 如果有值，清除错误状态
    if (displayName) {
      setErrorFields(prev => ({
        ...prev,
        [`${category}.${option}`]: false
      }));
    }

    // 查找模型完整信息以获取API配置
    let modelType = category as ModelType;
    if (category === 'voice') {
      modelType = option === 'tts' ? 'tts' : 'stt';
    } else if (category === 'reranker') {
      modelType = 'rerank';
    } else if (category === 'multimodal') {
      modelType = 'vlm';
    } else if (category === 'embedding') {
      modelType = option === 'multi_embedding' ? 'multi_embedding' : 'embedding';
    }

    const modelInfo = [...officialModels, ...customModels].find(
      m => m.displayName === displayName && m.type === modelType
    );

    // 新选择的模型如果是自定义模型，且之前没有设置状态，则设置为"未检测"
    if (modelInfo && modelInfo.source === "custom" && !modelInfo.connect_status) {
      updateCustomModelStatus(displayName, modelType, MODEL_STATUS.UNCHECKED);
    }

    // 更新配置
    let configKey = category;
    if (category === "llm" && option === "secondary") {
      configKey = "llmSecondary";
    } else if (category === "embedding" && option === "multi_embedding") {
      configKey = "multiEmbedding";
    } else if (category === "multimodal") {
      configKey = "vlm";
    } else if (category === "reranker") {
      configKey = "rerank";
    } else if (category === "voice" && option === "tts") {
      configKey = "tts";
    } else if (category === "voice" && option === "stt") {
      configKey = "stt";
    }

    const apiConfig = modelInfo?.apiKey
      ? {
          apiKey: modelInfo.apiKey,
          modelUrl: modelInfo.apiUrl || "",
        }
      : {
          apiKey: "",
          modelUrl: "",
        };

    let configUpdate: any = {
      [configKey]: {
        modelName: modelInfo?.name,
        displayName: displayName,
        apiConfig,
      },
    };

    // embedding 需要加 dimension 字段
    if (configKey === "embedding" || configKey === "multiEmbedding") {
      configUpdate[configKey].dimension = modelInfo?.maxTokens || undefined;
    }

    // 模型配置更新
    updateModelConfig(configUpdate)

    // 当选择新模型时，自动验证该模型连通性
    if (displayName) {
      await verifyOneModel(displayName, modelType);
    }
  }

  // 只做本地 UI 状态更新，不涉及数据库
  const updateCustomModelStatus = (displayName: string, modelType: string, status: ModelConnectStatus) => {
    setCustomModels(prev => {
      const idx = prev.findIndex(model => model.displayName === displayName && model.type === modelType);
      if (idx === -1) return prev;
      const updated = [...prev];
      updated[idx] = {
        ...updated[idx],
        connect_status: status
      };
      return updated;
    });
  }

  return (
    <>
      <div style={{ width: "100%", margin: "0 auto", height: "100%", display: "flex", flexDirection: "column", gap: "12px" }}>
        <div style={{ display: "flex", justifyContent: "flex-start", paddingRight: 12, marginLeft: "4px", height: LAYOUT_CONFIG.BUTTON_AREA_HEIGHT }}>
          <Space size={10}>
            <Button type="primary" size="middle" onClick={handleSyncModels}>
              <SyncOutlined spin={isSyncing} /> {t('modelConfig.button.syncModelEngine')}
            </Button>
            <Button type="primary" size="middle" icon={<PlusOutlined />} onClick={() => setIsAddModalOpen(true)}>
              {t('modelConfig.button.addCustomModel')}
            </Button>
            <Button type="primary" size="middle" icon={<EditOutlined />} onClick={() => setIsDeleteModalOpen(true)}>
              {t('modelConfig.button.editCustomModel')}
            </Button>
            <Button type="primary" size="middle" icon={<SafetyCertificateOutlined />} onClick={verifyModels} loading={isVerifying}>
              {t('modelConfig.button.checkConnectivity')}
            </Button>
          </Space>
        </div>

        <div style={{ width: "100%", padding: "0 4px", flex: 1, display: "flex", flexDirection: "column" }}>
          <Row gutter={[LAYOUT_CONFIG.CARD_GAP, LAYOUT_CONFIG.CARD_GAP]} style={{ flex: 1 }}>
            {Object.entries(modelData).map(([key, category]) => (
              <Col xs={24} md={8} lg={8} key={key} style={{ height: "calc((100% - 12px) / 2)" }}>
                <Card
                  title={
                    <div style={{ 
                      display: "flex", 
                      alignItems: "center", 
                      margin: "-12px -24px", 
                      padding: LAYOUT_CONFIG.CARD_HEADER_PADDING,
                      paddingBottom: "12px",
                      backgroundColor: cardThemes[key as keyof typeof cardThemes].backgroundColor,
                      borderBottom: `1px solid ${cardThemes[key as keyof typeof cardThemes].borderColor}`,
                      height: `${LAYOUT_CONFIG.HEADER_HEIGHT - 12}px`, // 减去paddingBottom
                    }}>
                      <h5 style={{ 
                        margin: 0, 
                        marginLeft: LAYOUT_CONFIG.MODEL_TITLE_MARGIN_LEFT,
                        fontSize: "14px",
                        lineHeight: "32px"
                      }}>
                        {category.title}
                      </h5>
                    </div>
                  }
                  variant="outlined"
                  className="model-card"
                  styles={{
                    body: { 
                      padding: LAYOUT_CONFIG.CARD_BODY_PADDING,
                      height: `calc(100% - ${LAYOUT_CONFIG.HEADER_HEIGHT}px)`,
                    }
                  }}
                  style={{
                    height: "100%",
                    backgroundColor: "#ffffff",
                    display: "flex",
                    flexDirection: "column"
                  }}
                >
                  <Space 
                    direction="vertical" 
                    style={{ 
                      width: "100%",
                      height: "100%",
                    }} 
                    size={12}
                  >
                    {category.options.map((option) => (
                      <ModelListCard
                        key={option.id}
                        type={
                          key === "voice" 
                            ? (option.id === "tts" ? "tts" : "stt") 
                            : key === "multimodal" 
                              ? "vlm" 
                              : (key === "embedding" && option.id === "multi_embedding") 
                                ? "multi_embedding" 
                                : key as ModelType
                        }
                        modelId={option.id}
                        modelTypeName={option.name}
                        selectedModel={selectedModels[key]?.[option.id] || ""}
                        onModelChange={(modelName) => handleModelChange(key, option.id, modelName)}
                        officialModels={officialModels}
                        customModels={customModels}
                        onVerifyModel={verifyOneModel}
                        errorFields={errorFields}
                      />
                    ))}
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </div>

        <ModelAddDialog
          isOpen={isAddModalOpen}
          onClose={() => setIsAddModalOpen(false)}
          onSuccess={async (newModel) => {
            await loadModelLists(true);
            message.success(t('modelConfig.message.addSuccess'));
            
            if (newModel && newModel.name && newModel.type) {
              setTimeout(() => {
                verifyOneModel(newModel.name, newModel.type);
              }, 100);
            }
          }}
        />

        <ModelDeleteDialog
          isOpen={isDeleteModalOpen}
          onClose={() => setIsDeleteModalOpen(false)}
          onSuccess={async () => {
            await loadModelLists(true);
            return;
          }}
          customModels={customModels}
        />
      </div>
    </>
  )
}) 