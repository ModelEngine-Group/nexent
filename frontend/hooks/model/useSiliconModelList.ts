import { useEffect } from 'react'
import { message } from 'antd'
import { useTranslation } from 'react-i18next'
import { modelService } from '@/services/modelService'
import { ModelType } from '@/types/modelConfig'
import log from "@/lib/logger";

interface UseSiliconModelListProps {
  form: {
    type: ModelType
    isBatchImport: boolean
    apiKey: string
    provider: string
    maxTokens: string
    isMultimodal: boolean
  }
  setModelList: (models: any[]) => void
  setSelectedModelIds: (ids: Set<string>) => void
  setShowModelList: (show: boolean) => void
  setLoadingModelList: (loading: boolean) => void
}

export const useSiliconModelList = ({
  form,
  setModelList,
  setSelectedModelIds,
  setShowModelList,
  setLoadingModelList
}: UseSiliconModelListProps) => {
  const { t } = useTranslation()

  const getModelList = async () => {
    setShowModelList(true)
    setLoadingModelList(true)
    const modelType = form.type === "embedding" && form.isMultimodal ? 
        "multi_embedding" as ModelType : 
        form.type
    try {
      const result = await modelService.addProviderModel({
        provider: form.provider,
        type: modelType,
        apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey
      })
      // Ensure each model has a default max_tokens value
      const modelsWithDefaults = result.map((model: any) => ({
        ...model,
        max_tokens: model.max_tokens || parseInt(form.maxTokens) || 4096
      }))
      setModelList(modelsWithDefaults)
      if (!result || result.length === 0) {
        message.error(t('model.dialog.error.noModelsFetched'))
      }
      const selectedModels = await getProviderSelectedModalList() || []
      // Key logic
      if (!selectedModels.length) {
        // Select none
        setSelectedModelIds(new Set())
      } else {
        // Only select selectedModels
        setSelectedModelIds(new Set(selectedModels.map((m: any) => m.id)))
      }
    } catch (error) {
      message.error(t('model.dialog.error.addFailed', { error }))
      log.error(t('model.dialog.error.addFailedLog'), error)
    } finally {
      setLoadingModelList(false)
    }
  }

  const getProviderSelectedModalList = async () => {
    const modelType = form.type === "embedding" && form.isMultimodal ? 
        "multi_embedding" as ModelType : 
        form.type
    const result = await modelService.getProviderSelectedModalList({
      provider: form.provider,
      type: modelType,
      api_key: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey
    })
    return result
  }

  // Auto-fetch model list when batch import is enabled and API key is provided
  useEffect(() => {
    if (form.isBatchImport && form.apiKey.trim() !== "") {
      getModelList()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.type, form.isBatchImport])

  return {
    getModelList,
    getProviderSelectedModalList
  }
}
