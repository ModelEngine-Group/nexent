import { Modal, Input, Button, App } from 'antd'
import { useState, useEffect } from 'react'
import { ModelOption, ModelType } from '@/types/config'
import { modelService } from '@/services/modelService'
import { useConfig } from '@/hooks/useConfig'
import { useTranslation } from 'react-i18next'


interface ModelEditDialogProps {
  isOpen: boolean
  model: ModelOption | null
  onClose: () => void
  onSuccess: () => Promise<void>
}

export const ModelEditDialog = ({ isOpen, model, onClose, onSuccess }: ModelEditDialogProps) => {
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
    vectorDimension: "1024"
  })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (model) {
      setForm({
        type: model.type,
        name: model.name,
        displayName: model.displayName || model.name,
        url: model.apiUrl || "",
        apiKey: model.apiKey || "",
        maxTokens: model.maxTokens?.toString() || "4096",
        vectorDimension: model.maxTokens?.toString() || "1024"
      })
    }
  }, [model])

  const handleFormChange = (field: string, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }))
  }

  const isEmbeddingModel = form.type === "embedding" || form.type === "multi_embedding"

  const isFormValid = () => {
    return form.name.trim() !== "" && form.url.trim() !== ""
  }

  const handleSave = async () => {
    if (!model) return
    setLoading(true)
    try {
      // 使用更新接口而不是删除 + 新增
      const modelType = form.type as ModelType
      // Determine max tokens
      let maxTokensValue = parseInt(form.maxTokens)
      if (isEmbeddingModel) maxTokensValue = 0
      
      await modelService.updateSingleModel({
        model_id: model.id, // 使用模型名称作为ID
        name: form.name,
        url: form.url,
        apiKey: form.apiKey.trim() === "" ? "sk-no-api-key" : form.apiKey,
        maxTokens: maxTokensValue,
        source: model.source
      })

      // 更新本地配置（仅当当前编辑模型在配置中被选中时）
      const modelConfigKeyMap: Record<ModelType, string> = {
        llm: "llm",
        embedding: "embedding",
        multi_embedding: "multiEmbedding",
        vlm: "vlm",
        rerank: "rerank",
        tts: "tts",
        stt: "stt"
      }
      const configKey = modelConfigKeyMap[modelType]
      updateModelConfig({
        [configKey]: {
          modelName: form.name,
          displayName: form.displayName || form.name,
          apiConfig: {
            apiKey: form.apiKey,
            modelUrl: form.url
          },
          ...(isEmbeddingModel ? { dimension: parseInt(form.vectorDimension) } : {})
        }
      })

      await onSuccess()
      message.success(t('model.dialog.editSuccess'))
      onClose()
    } catch (error: any) {
      if (error.code === 409) {
        message.error(t('model.dialog.error.nameConflict', { name: form.displayName || form.name }))
      } else if (error.code === 404) {
        message.error(t('model.dialog.error.modelNotFound'))
      } else if (error.code === 500) {
        message.error(t('model.dialog.error.serverError'))
      } else {
        message.error(t('model.dialog.error.editFailed'))
      }
    } finally {
      setLoading(false)
    }
  }

  if (!model) return null

  return (
    <Modal
      title={t('model.dialog.editTitle')}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      destroyOnClose
    >
      <div className="space-y-4">
        {/* Model Name */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t('model.dialog.label.name')}
          </label>
          <Input
            value={form.name}
            onChange={(e) => handleFormChange('name', e.target.value)}
          />
        </div>

        {/* URL */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t('model.dialog.label.url')}
          </label>
          <Input
            value={form.url}
            onChange={(e) => handleFormChange('url', e.target.value)}
          />
        </div>

        {/* API Key */}
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t('model.dialog.label.apiKey')}
          </label>
          <Input.Password
            value={form.apiKey}
            onChange={(e) => handleFormChange('apiKey', e.target.value)}
          />
        </div>

        {/* maxTokens */}
        {!isEmbeddingModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.maxTokens')}
            </label>
            <Input
              value={form.maxTokens}
              onChange={(e) => handleFormChange('maxTokens', e.target.value)}
            />
          </div>
        )}

        <div className="flex justify-end space-x-3">
          <Button onClick={onClose}>{t('common.button.cancel')}</Button>
          <Button type="primary" onClick={handleSave} loading={loading} disabled={!isFormValid()}>
            {t('common.button.save')}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

// New: provider config edit dialog (only apiKey and maxTokens)
interface ProviderConfigEditDialogProps {
  isOpen: boolean
  initialApiKey?: string
  initialMaxTokens?: string
  modelType?: ModelType
  onClose: () => void
  onSave: (config: { apiKey: string; maxTokens: number }) => Promise<void> | void
}

export const ProviderConfigEditDialog = ({
  isOpen,
  initialApiKey = '',
  initialMaxTokens = '4096',
  modelType,
  onClose,
  onSave,
}: ProviderConfigEditDialogProps) => {
  const { t } = useTranslation()
  const [apiKey, setApiKey] = useState<string>(initialApiKey)
  const [maxTokens, setMaxTokens] = useState<string>(initialMaxTokens)
  const [saving, setSaving] = useState<boolean>(false)

  useEffect(() => {
    setApiKey(initialApiKey)
    setMaxTokens(initialMaxTokens)
  }, [initialApiKey, initialMaxTokens])

  const valid = () => {
    const parsed = parseInt(maxTokens)
    return !Number.isNaN(parsed) && parsed >= 0
  }

  const handleSave = async () => {
    if (!valid()) return
    try {
      setSaving(true)
      await onSave({ apiKey: apiKey.trim() === '' ? 'sk-no-api-key' : apiKey, maxTokens: parseInt(maxTokens) })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const isEmbeddingModel = modelType === "embedding" || modelType === "multi_embedding"

  return (
    <Modal
      title={t('common.button.editConfig')}
      open={isOpen}
      onCancel={onClose}
      footer={null}
      destroyOnClose
    >
      <div className="space-y-4">
        <div>
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t('model.dialog.label.apiKey')}
          </label>
          <Input.Password value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </div>
        {!isEmbeddingModel && (
          <div>
            <label className="block mb-1 text-sm font-medium text-gray-700">
              {t('model.dialog.label.maxTokens')}
            </label>
            <Input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} />
          </div>
        )}
        <div className="flex justify-end space-x-3">
          <Button onClick={onClose}>{t('common.button.cancel')}</Button>
          <Button type="primary" onClick={handleSave} loading={saving} disabled={!valid()}>
            {t('common.button.save')}
          </Button>
        </div>
      </div>
    </Modal>
  )
} 