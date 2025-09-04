import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { Modal, Select, Input, Button, Switch, Tooltip, App } from 'antd'
import { InfoCircleFilled, LoadingOutlined, RightOutlined, DownOutlined, SettingOutlined } from '@ant-design/icons'

import { useConfig } from '@/hooks/useConfig'
import { getConnectivityIcon, getConnectivityColor, getConnectivityMeta, ConnectivityStatusType } from '@/lib/utils'
import { modelService } from '@/services/modelService'
import { ModelType, SingleModelConfig } from '@/types/config'
import { useSiliconModelList } from '@/hooks/model/useSiliconModelList'

const { Option } = Select

// Define the return type after adding a model
export interface AddedModel {
  name: string;
  type: ModelType;
}

interface ModelAddDialogProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: (model?: AddedModel) => Promise<void>
}

// Connectivity status type comes from utils

export const ModelAddDialog = ({ isOpen, onClose, onSuccess }: ModelAddDialogProps) => {
  const { t } = useTranslation()
  const { message } = App.useApp()
  const { updateModelConfig } = useConfig()
  const [form, setForm] = useState({
    type: "llm" as ModelType,
    name: "",
    displayName: "",
    url: "",
    apiKey: "",
    maxTokens: "4096",
    isMultimodal: false,
    // Whether to import multiple models at once
    isBatchImport: false,
    provider: "silicon",
    vectorDimension: "1024"
  })
  const [loading, setLoading] = useState(false)
  const [verifyingConnectivity, setVerifyingConnectivity] = useState(false)
  const [connectivityStatus, setConnectivityStatus] = useState<{
    status: ConnectivityStatusType
    message: string
  }>({
    status: null,
    message: ""
  })

  const [modelList, setModelList] = useState<any[]>([])
  const [selectedModelIds, setSelectedModelIds] = useState<Set<string>>(new Set())
  const [showModelList, setShowModelList] = useState(false)
  const [loadingModelList, setLoadingModelList] = useState(false)

  // Settings modal state
  const [settingsModalVisible, setSettingsModalVisible] = useState(false)
  const [selectedModelForSettings, setSelectedModelForSettings] = useState<any>(null)
  const [modelMaxTokens, setModelMaxTokens] = useState("4096")

  // Use the silicon model list hook
  const { getModelList, getProviderSelectedModalList } = useSiliconModelList({
    form,
    setModelList,
    setSelectedModelIds,
    setShowModelList,
    setLoadingModelList
  })

  // Debug: log model list when it updates
  // useEffect(() => {
  //   console.log('modelList', modelList)
  //   // whenever modelList changes, select all by default
  //   setSelectedModelIds(new Set(modelList.map((m: any) => m.id)))
  // }, [modelList])

  const parseModelName = (name: string): string => {
    if (!name) return ""
    const parts = name.split('/')
    if (parts.length <= 2) {
      return parts[parts.length - 1]
    } else {
      return `${parts[0]}/${parts[parts.length - 1]}`
    }
  }

  // Handle model name change, automatically update the display name
  const handleModelNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value
    setForm(prev => ({
      ...prev,
      name,
      // If the display name is the same as the parsed result of the model name, it means the user has not manually modified the display name
      // At this time, the display name should be automatically updated
      displayName: prev.displayName === parseModelName(prev.name) ? parseModelName(name) : prev.displayName
    }))
    // Clear the previous verification status
    setConnectivityStatus({ status: null, message: "" })
  }

  // Handle form change
  const handleFormChange = (field: string, value: string | boolean) => {
    setForm(prev => ({
      ...prev,
      [field]: value
    }))
    // If the key configuration item changes, clear the verification status
    if (['type', 'url', 'apiKey', 'maxTokens', 'vectorDimension'].includes(field)) {
      setConnectivityStatus({ status: null, message: "" })
    }
  }

  // Verify if the vector dimension is valid
  const isValidVectorDimension = (value: string): boolean => {
    const dimension = parseInt(value);
    return !isNaN(dimension) && dimension > 0;
  }

  // Check if the form is valid
  const isFormValid = () => {
    if (form.isBatchImport) {
      return form.provider.trim() !== "" && 
             form.apiKey.trim() !== ""
    }
    if (form.type === "embedding") {
      return form.name.trim() !== "" && 
             form.url.trim() !== "" && 
             isValidVectorDimension(form.vectorDimension);
    }
    return form.name.trim() !== "" && 
           form.url.trim() !== "" && 
           form.maxTokens.trim() !== ""
  }

  // Verify model connectivity
  const handleVerifyConnectivity = async () => {
    if (!isFormValid()) {
      message.warning(t('model.dialog.warning.incompleteForm'))
      return
    }

    setVerifyingConnectivity(true)
    setConnectivityStatus({ status: "checking", message: t('model.dialog.status.verifying') })

    try {
      const modelType = form.type === "embedding" && form.isMultimodal ? 
        "multi_embedding" as ModelType : 
        form.type;

      const config = {
        modelName: form.name,
        modelType: modelType,
        baseUrl: form.url,
        apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
        maxTokens: form.type === "embedding" ? parseInt(form.vectorDimension) : parseInt(form.maxTokens),
        embeddingDim: form.type === "embedding" ? parseInt(form.vectorDimension) : undefined
      }

      const result = await modelService.verifyModelConfigConnectivity(config)
      
      // Set connectivity status
      let connectivityMessage = ''
      if (result.connectivity) {
        connectivityMessage = t('model.dialog.connectivity.status.available')
      } else {
        connectivityMessage = t('model.dialog.connectivity.status.unavailable')
      }
      setConnectivityStatus({
        status: result.connectivity ? "available" : "unavailable",
        message: connectivityMessage
      })

    } catch (error) {
      setConnectivityStatus({
        status: "unavailable",
        message: t('model.dialog.connectivity.status.unavailable')
      })
    } finally {
      setVerifyingConnectivity(false)
    }
  }

  // Handle batch adding models 
  const handleBatchAddModel = async () => {
    // Only include models whose id is in selectedModelIds (i.e., switch is ON)
    const enabledModels = modelList.filter((model: any) => selectedModelIds.has(model.id));
    const modelType = form.type === "embedding" && form.isMultimodal ? 
        "multi_embedding" as ModelType : 
        form.type;
    try {
      const result = await modelService.addBatchCustomModel({
        api_key: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
        provider: form.provider,
        type: modelType,
        models: enabledModels.map((model: any) => ({
          ...model,
          max_tokens: model.max_tokens || parseInt(form.maxTokens) || 4096
        }))
      })
      if (result === 200) {
        onSuccess()
      }
    } catch (error: any) {
      message.error(error?.message || '添加模型失败');
    }

    setForm(prev => ({
      ...prev,
      isBatchImport: false
    }))
   
    onClose()
  }



  // Handle settings button click
  const handleSettingsClick = (model: any) => {
    setSelectedModelForSettings(model)
    setModelMaxTokens(model.max_tokens?.toString() || "4096")
    setSettingsModalVisible(true)
  }

  // Handle settings save
  const handleSettingsSave = () => {
    if (selectedModelForSettings) {
      // Update the model in the list with new max_tokens
      setModelList(prev => prev.map(model => 
        model.id === selectedModelForSettings.id 
          ? { ...model, max_tokens: parseInt(modelMaxTokens) || 4096 }
          : model
      ))
    }
    setSettingsModalVisible(false)
    setSelectedModelForSettings(null)
  }

  // Handle adding a model
  const handleAddModel = async () => {
    setLoading(true)
    if (form.isBatchImport) {
      await handleBatchAddModel()
      setLoading(false)
      return
    }
    try {
      const modelType = form.type === "embedding" && form.isMultimodal ? 
        "multi_embedding" as ModelType : 
        form.type;
      
      // Determine the maximum tokens value
      let maxTokensValue = parseInt(form.maxTokens);
      if (form.type === "embedding" || form.type === "multi_embedding") {
        // For embedding models, use the vector dimension as maxTokens
        maxTokensValue = 0;
      }
      
      // Add to the backend service
      await modelService.addCustomModel({
        name: form.name,
        type: modelType,
        url: form.url,
        apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
        maxTokens: maxTokensValue,
        displayName: form.displayName || form.name
      })
      
      // Create the model configuration object
      const modelConfig: SingleModelConfig = {
        modelName: form.name,
        displayName: form.displayName || form.name,
        apiConfig: {
          apiKey: form.apiKey,
          modelUrl: form.url,
        }
      }
      
      // Add the dimension field for embedding models
      if (form.type === "embedding") {
        modelConfig.dimension = parseInt(form.vectorDimension);
      }
      
      // Update the local storage according to the model type
      let configUpdate: any = {}
      
      switch(modelType) {
        case "llm":
          configUpdate = { llm: modelConfig }
          break;
        case "embedding":
          configUpdate = { embedding: modelConfig }
          break;
        case "multi_embedding":
          configUpdate = { multiEmbedding: modelConfig }
          break;
        case "vlm":
          configUpdate = { vlm: modelConfig }
          break;
        case "rerank":
          configUpdate = { rerank: modelConfig }
          break;
        case "tts":
          configUpdate = { tts: modelConfig }
          break;
        case "stt":
          configUpdate = { stt: modelConfig }
          break;
      }
      
      // Save to localStorage
      updateModelConfig(configUpdate)
      
      // Create the returned model information
      const addedModel: AddedModel = {
        name: form.displayName,
        type: modelType
      }
      
      // Reset the form
      setForm({
        type: form.type,
        name: "",
        displayName: "",
        url: "",
        apiKey: "",
        maxTokens: "4096",
        isMultimodal: false,
        isBatchImport: false,
        provider: "silicon",
        vectorDimension: "1024"
      })
      
      // Reset the connectivity status
      setConnectivityStatus({ status: null, message: "" })
      
      // Call the success callback, pass the new added model information
      await onSuccess(addedModel)
      
      // Close the dialog
      onClose()
    } catch (error) {
      message.error(t('model.dialog.error.addFailed', { error }))
      console.error(t('model.dialog.error.addFailedLog'), error)
    } finally {
      setLoading(false)
    }
  }

  const isEmbeddingModel = form.type === "embedding"



  return (
    <Modal
      title={t('model.dialog.title')}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      destroyOnClose
    >
      <div className="space-y-4">
        {/* Batch Import Switch */}
        <div>
          <div className="flex justify-between items-center">
            <label className="block text-sm font-medium text-gray-700">
              {t('model.dialog.label.batchImport')}
            </label>
            <Switch
              checked={form.isBatchImport}
              onChange={(checked) => handleFormChange("isBatchImport", checked)}
            />
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {form.isBatchImport ? t('model.dialog.hint.batchImportEnabled') : t('model.dialog.hint.batchImportDisabled')}
          </div>
        </div>

        {/* Model Provider (shown only when batch import is enabled) */}
        {form.isBatchImport && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.provider')}<span className="text-red-500">*</span>
            </label>
            <Select
              style={{ width: '100%' }}
              value={form.provider}
              onChange={(value) => handleFormChange('provider', value)}
            >
              <Option value="silicon">{t('model.provider.silicon')}</Option>
            </Select>
          </div>
        )}

        {/* Model Type */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t('model.dialog.label.type')} <span className="text-red-500">*</span>
          </label>
          <Select
            style={{ width: "100%" }}
            value={form.type}
            onChange={(value) => handleFormChange("type", value)}
          >
            <Option value="llm">{t('model.type.llm')}</Option>
            <Option value="embedding">{t('model.type.embedding')}</Option>
            <Option value="vlm">{t('model.type.vlm')}</Option>
            <Option value="rerank" disabled>{t('model.type.rerank')}</Option>
            <Option value="stt" disabled>{t('model.type.stt')}</Option>
            <Option value="tts" disabled>{t('model.type.tts')}</Option>
          </Select>
        </div>

        {/* Multimodal Switch */}
        {isEmbeddingModel && !form.isBatchImport && (
          <div>
            <div className="flex justify-between items-center">
              <label className="block text-sm font-medium text-gray-700">
                {t('model.dialog.label.multimodal')}
              </label>
              <Switch 
                checked={form.isMultimodal}
                onChange={(checked) => handleFormChange("isMultimodal", checked)}
              />
            </div>
            <div className="text-xs text-gray-500 mt-1">
              {form.isMultimodal ? t('model.dialog.hint.multimodalEnabled') : t('model.dialog.hint.multimodalDisabled')}
            </div>
          </div>
        )}

        {/* Model Name */}
        {!form.isBatchImport && (
          <div>
            <label htmlFor="name" className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.name')} <span className="text-red-500">*</span>
            </label>
            <Input
              id="name"
              placeholder={t('model.dialog.placeholder.name')}
              value={form.name}
              onChange={handleModelNameChange}
            />
          </div>
        )}

        {/* Display Name */}
        {!form.isBatchImport && (
          <div>
            <label htmlFor="displayName" className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.displayName')}
            </label>
            <Input
              id="displayName"
              placeholder={t('model.dialog.placeholder.displayName')}
              value={form.displayName}
              onChange={(e) => handleFormChange("displayName", e.target.value)}
            />
          </div>
        )}

        {/* Model URL */}
        {!form.isBatchImport && (
          <div>
            <label htmlFor="url" className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.url')} <span className="text-red-500">*</span>
            </label>
            <Input
              id="url"
              placeholder={
                form.type === "embedding"
                  ? t('model.dialog.placeholder.url.embedding')
                  : t('model.dialog.placeholder.url')
              }
              value={form.url}
              onChange={(e) => handleFormChange("url", e.target.value)}
            />
          </div>
        )}

        {/* API Key */}
        <div>
          <label htmlFor="apiKey" className="block mb-1 text-sm font-medium text-gray-700">
            {t('model.dialog.label.apiKey')}
          </label>
          <Input.Password
            id="apiKey"
            placeholder={t('model.dialog.placeholder.apiKey')}
            value={form.apiKey}
            onChange={(e) => handleFormChange("apiKey", e.target.value)}
          />
        </div>

        {/* Vector dimension */}
        {isEmbeddingModel && (
          <div>
            <label htmlFor="vectorDimension" className="block mb-1 text-sm font-medium text-gray-700">
            </label>
          </div>
        )}

        {/* Max Tokens */}
        {!isEmbeddingModel && !form.isBatchImport && (
          <div>
            <label htmlFor="maxTokens" className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.maxTokens')}
            </label>
            <Input
              id="maxTokens"
              placeholder={t('model.dialog.placeholder.maxTokens')}
              value={form.maxTokens}
              onChange={(e) => handleFormChange("maxTokens", e.target.value)}
            />
          </div>
        )}

        {/* Connectivity verification area */}
        {!form.isBatchImport && (
        <div className="p-3 bg-gray-50 border border-gray-200 rounded-md">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center">
              <span className="text-sm font-medium text-gray-700">{t('model.dialog.connectivity.title')}</span>
              {connectivityStatus.status && (
                <div className="ml-2 flex items-center">
                  {getConnectivityMeta(connectivityStatus.status).icon}
                  <span 
                    className="ml-1 text-xs"
                    style={{ color: getConnectivityMeta(connectivityStatus.status).color }}
                  >
                    {connectivityStatus.status === 'available' && t('model.dialog.connectivity.status.available')}
                    {connectivityStatus.status === 'unavailable' && t('model.dialog.connectivity.status.unavailable')}
                    {connectivityStatus.status === 'checking' && t('model.dialog.status.verifying')}
                  </span>
                </div>
              )}
            </div>
            <Button
              size="small"
              type="default"
              onClick={handleVerifyConnectivity}
              loading={verifyingConnectivity}
              disabled={!isFormValid() || verifyingConnectivity}
            >
              {verifyingConnectivity ? t('model.dialog.button.verifying') : t('model.dialog.button.verify')}
            </Button>
          </div>
        </div>
        )}

        {/* Model List */}
        {form.isBatchImport && (
        <div className="p-3 bg-gray-50 border border-gray-200 rounded-md">
          <div className="flex items-center justify-between mb-1">
            <button
              type="button"
              onClick={() => setShowModelList(!showModelList)}
              className="flex items-center focus:outline-none"
            >
              {showModelList ? (
                <DownOutlined className="text-sm text-gray-700 mr-1" />
              ) : (
                <RightOutlined className="text-sm text-gray-700 mr-1" />
              )}
              <span className="text-sm font-medium text-gray-700">
                {t('model.dialog.modelList.title')}
              </span>
            </button>
            <Button
              size="small"
              type="default"
              onClick={getModelList}
              disabled={!isFormValid() || loadingModelList}
            >
              {loadingModelList ? t('common.loading') : t('model.dialog.button.modelList')}
            </Button>
          </div>
          {showModelList && (
            <div className="mt-2 space-y-1 max-h-60 overflow-y-auto">
              {loadingModelList ? (
                <div className="flex flex-col items-center justify-center py-4 text-xs text-gray-500">
                  <LoadingOutlined spin style={{ fontSize: 18, color: '#1890ff', marginBottom: 4 }} />
                  <span>{t('common.loading') || '获取中...'}</span>
                </div>
              ) : modelList.length === 0 ? (
                <div className="text-xs text-gray-500 text-center">{t('model.dialog.message.noModels') || '请先获取模型'}</div>
              ) : (
                
                modelList.map((model: any) => {
                  const checked = selectedModelIds.has(model.id)
                  const toggleSelect = (value: boolean) => {
                    setSelectedModelIds(prev => {
                      const next = new Set(prev)
                      if (value) {
                        next.add(model.id)
                      } else {
                        next.delete(model.id)
                      }
                      return next
                    })
                  }
                  return (
                    <div key={model.id} className="p-2 flex justify-between items-center rounded hover:bg-gray-100 text-sm border border-transparent">
                      <div className="flex items-center min-w-0">
                        <span className="truncate" title={model.id}>
                          {model.id}
                        </span>
                        {model.model_type && (
                          <span className="ml-2 px-1.5 py-0.5 text-xs rounded bg-gray-200 text-gray-600 uppercase">
                            {String(model.model_tag)}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center space-x-2">
                        {!isEmbeddingModel && (
                          <Tooltip title={t('model.dialog.modelList.tooltip.settings')}>
                            <Button
                              type="text"
                              icon={<SettingOutlined />}
                              size="small"
                              onClick={(e) => {
                                e.stopPropagation(); // Prevent switch toggle
                                handleSettingsClick(model);
                              }}
                            />
                          </Tooltip>
                        )}
                        <Switch size="small" checked={checked} onChange={toggleSelect} />
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          )}
          {connectivityStatus.message && !showModelList && (
            <div className="text-xs text-gray-600">
              {connectivityStatus.message}
            </div>
          )}
          </div>
        )}

        {/* Help Text */}
        <div className="p-3 bg-blue-50 border border-blue-100 rounded-md text-xs text-blue-700">
          <div>
            <div className="flex items-center mb-1">
              <InfoCircleFilled className="text-md text-blue-500 mr-3" />
              <p className="font-bold text-medium">{t('model.dialog.help.title')}</p>
            </div>
            <p className="mt-0.5 ml-6">
              {form.isBatchImport ? t('model.dialog.help.content.batchImport') : t('model.dialog.help.content')}
            </p>
            <div className="mt-2 ml-6 flex items-center">
              <span>{t('model.dialog.label.currentlySupported')}</span>
              {form.isBatchImport && (
                <Tooltip title="SiliconCloud">
                  <img src="/siliconcloud-color.png" alt="SiliconCloud" className="h-4 ml-1.5" />
                </Tooltip>
              )}
              {form.type === 'llm' && !form.isBatchImport && (
                <>
                  <Tooltip title="OpenAI">
                    <img src="/openai.png" alt="OpenAI" className="h-4 ml-1.5" />
                  </Tooltip>
                  <Tooltip title="Kimi">
                    <img src="/kimi-color.png" alt="Kimi" className="h-4 ml-1.5" />
                  </Tooltip>
                  <Tooltip title="Deepseek">
                    <img src="/deepseek-color.png" alt="Deepseek" className="h-4 ml-1.5" />
                  </Tooltip>
                  <Tooltip title="Qwen">
                    <img src="/qwen-color.png" alt="Qwen" className="h-4 ml-1.5" />
                  </Tooltip>
                  <span className="ml-1.5">...</span>
                </>
              )}
              {form.type === 'embedding' && !form.isBatchImport && (
                <>
                  <Tooltip title="OpenAI">
                    <img src="/openai.png" alt="OpenAI" className="h-4 ml-1.5" />
                  </Tooltip>
                  <Tooltip title="Qwen">
                    <img src="/qwen-color.png" alt="Qwen" className="h-4 ml-1.5" />
                  </Tooltip>
                  <Tooltip title="Jina">
                    <img src="/jina.png" alt="Jina" className="h-4 ml-1.5" />
                  </Tooltip>
                  <Tooltip title="Baai">
                    <img src="/baai.png" alt="Baai" className="h-4 ml-1.5" />
                  </Tooltip>
                  <span className="ml-1.5">...</span>
                </>
              )}
              {form.type === 'vlm' && !form.isBatchImport && (
                <>
                  <Tooltip title="Qwen">
                    <img src="/qwen-color.png" alt="Qwen" className="h-4 ml-1.5" />
                  </Tooltip>
                  <Tooltip title="Deepseek">
                    <img src="/deepseek-color.png" alt="Deepseek" className="h-4 ml-1.5" />
                  </Tooltip>
                  <span className="ml-1.5">...</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Footer Buttons */}
        <div className="flex justify-end space-x-3">
          <Button onClick={onClose}>
            {t('common.button.cancel')}
          </Button>
          <Button
            type="primary"
            onClick={handleAddModel}
            disabled={!isFormValid()}
            loading={loading}
          >
            {t('model.dialog.button.add')}
          </Button>
        </div>
      </div>

      {/* Settings Modal */}
      <Modal
        title={t('model.dialog.settings.title')}
        open={settingsModalVisible}
        onCancel={() => setSettingsModalVisible(false)}
        onOk={handleSettingsSave}
        destroyOnClose
      >
        <div className="space-y-3">
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.settings.label.maxTokens')}
            </label>
            <Input
              type="number"
              value={modelMaxTokens}
              onChange={(e) => setModelMaxTokens(e.target.value)}
              placeholder={t('model.dialog.placeholder.maxTokens')}
            />
          </div>
        </div>
      </Modal>
    </Modal>
  )
} 