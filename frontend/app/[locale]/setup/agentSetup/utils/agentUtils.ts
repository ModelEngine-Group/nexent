import { TFunction } from 'i18next'
import { Tool } from '@/types/agent'
import { updateToolConfig, searchToolConfig } from '@/services/agentConfigService'

// 提取公共的 handleToolSelect 逻辑
export const handleToolSelectCommon = async (
  tool: Tool,
  isSelected: boolean,
  mainAgentId: string | null | undefined,
  t: TFunction,
  message: any,
  onSuccess?: (tool: Tool, isSelected: boolean) => void
) => {

  // Only block the action when attempting to select an unavailable tool.
  if (tool.is_available === false && isSelected) {
    message.error(t('tool.message.unavailable'));
    return { shouldProceed: false, params: {} };
  }

  if (!mainAgentId) {
    message.error(t('tool.error.noMainAgentId'));
    return { shouldProceed: false, params: {} };
  }

  try {
    // step 1: get tool config from database
    const searchResult = await searchToolConfig(parseInt(tool.id), parseInt(mainAgentId));
    if (!searchResult.success) {
      message.error(t('tool.error.configFetchFailed'));
      return { shouldProceed: false, params: {} };
    }

    let params: Record<string, any> = {};

    // use config from database or default config
    if (searchResult.data?.params) {
      params = searchResult.data.params || {};
    } else {
      // if there is no saved config, use default value
      params = (tool.initParams || []).reduce((acc, param) => {
        if (param && param.name) {
          acc[param.name] = param.value;
        }
        return acc;
      }, {} as Record<string, any>);
    }

    // step 2: if the tool is enabled, check required fields
    if (isSelected && tool.initParams && tool.initParams.length > 0) {
      const missingRequiredFields = tool.initParams
        .filter(param => param && param.required && (params[param.name] === undefined || params[param.name] === '' || params[param.name] === null))
        .map(param => param.name);

      if (missingRequiredFields.length > 0) {
        return { shouldProceed: false, params };
      }
    }

    // step 3: if all checks pass, update tool config
    const updateResult = await updateToolConfig(
      parseInt(tool.id),
      parseInt(mainAgentId),
      params,
      isSelected
    );

    if (updateResult.success) {
      if (onSuccess) {
        onSuccess(tool, isSelected);
      }
      message.success(t('tool.message.statusUpdated', { name: tool.name, status: isSelected ? t('common.enabled') : t('common.disabled') }));
      return { shouldProceed: true, params };
    } else {
      message.error(updateResult.message || t('tool.error.updateFailed'));
      return { shouldProceed: false, params };
    }
  } catch (error) {
    message.error(t('tool.error.updateRetry'));
    return { shouldProceed: false, params: {} };
  }
}; 
