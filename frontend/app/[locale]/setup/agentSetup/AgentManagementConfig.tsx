"use client"

import { useState, useEffect, useMemo, useCallback, memo } from 'react'
import { Typography, Input, Button, Switch, Modal, message, Select, InputNumber, Tag, Upload } from 'antd'
import { SettingOutlined, UploadOutlined, ThunderboltOutlined, LoadingOutlined, ApiOutlined, ReloadOutlined } from '@ant-design/icons'
import ToolConfigModal from './components/ToolConfigModal'
import McpConfigModal from './components/McpConfigModal'
import AgentInfoInput from './components/AgentInfoInput'
import AgentContextMenu from './components/AgentContextMenu'
import { Tool, BusinessLogicInputProps, SubAgentPoolProps, ToolPoolProps, BusinessLogicConfigProps, Agent, OpenAIModel } from './ConstInterface'
import { ScrollArea } from '@/components/ui/scrollArea'
import { getCreatingSubAgentId, fetchAgentList, updateToolConfig, searchToolConfig, updateAgent, importAgent, exportAgent, deleteAgent, searchAgentInfo, fetchTools } from '@/services/agentConfigService'
import { updateToolList } from '@/services/mcpService'
import {generatePromptStream, savePrompt} from '@/services/promptService'
import { useTranslation } from 'react-i18next'
import { TFunction } from 'i18next'
const { TextArea } = Input

const ModelOptions = () => {
  const { t } = useTranslation('common');
  return [
    { label: t('model.option.main'), value: OpenAIModel.MainModel },
    { label: t('model.option.sub'), value: OpenAIModel.SubModel },
  ]
}

// 提取公共的 handleToolSelect 逻辑
const handleToolSelectCommon = async (
  tool: Tool,
  isSelected: boolean,
  mainAgentId: string | null | undefined,
  t: TFunction,
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

/**
 * Business Logic Input Component
 */
function BusinessLogicInput({ value, onChange, selectedAgents, systemPrompt }: BusinessLogicInputProps) {
  const { t } = useTranslation('common');

  return (
    <div className="flex flex-col h-full">
      <h2 className="text-lg font-medium mb-2">{t('businessLogic.title')}</h2>
      <div className="flex-1 flex flex-col">
        <TextArea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t('businessLogic.placeholder')}
          className="w-full h-full resize-none p-3 text-base"
          style={{ height: '100%' }}
          autoSize={false}
        />
      </div>
    </div>
  )
}

/**
 * Sub Agent Pool Component
 */
function SubAgentPool({ 
  selectedAgents, 
  onSelectAgent, 
  onEditAgent, 
  onCreateNewAgent, 
  onImportAgent,
  onExportAgent,
  onDeleteAgent,
  subAgentList = [],
  loadingAgents = false,
  enabledAgentIds = [],
  isImporting = false
}: SubAgentPoolProps) {
  const { t } = useTranslation('common');

  const [contextMenu, setContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
    agent: Agent | null;
  }>({
    visible: false,
    x: 0,
    y: 0,
    agent: null
  });

  const handleContextMenu = (e: React.MouseEvent, agent: Agent) => {
    e.preventDefault();
    e.stopPropagation();
    
    setContextMenu({
      visible: true,
      x: e.clientX,
      y: e.clientY,
      agent: agent
    });
  };

  const handleCloseContextMenu = () => {
    setContextMenu({
      visible: false,
      x: 0,
      y: 0,
      agent: null
    });
  };

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex justify-between items-center mb-2">
        <h2 className="text-lg font-medium">{t('subAgentPool.title')}</h2>
        {loadingAgents && <span className="text-sm text-gray-500">{t('subAgentPool.loading')}</span>}
      </div>
      <ScrollArea className="flex-1 min-h-0 border-t pt-2 pb-2">
        <div className="grid grid-cols-1 gap-3 pr-2">
          <div className="flex gap-2 mb-2">
            <div 
              className="flex-1 border rounded-md p-3 flex flex-col justify-center items-center cursor-pointer transition-colors duration-200 h-[80px] hover:border-blue-300 hover:bg-blue-50"
              onClick={onCreateNewAgent}
            >
              <div className="flex items-center justify-center h-full text-blue-500">
                <span className="text-lg mr-2">+</span>
                <span className="text-sm">{t('subAgentPool.button.create')}</span>
              </div>
            </div>

            <div
              className={`flex-1 border rounded-md p-3 flex flex-col justify-center items-center transition-colors duration-200 h-[80px] ${
                isImporting
                  ? 'opacity-50 cursor-not-allowed border-gray-300'
                  : 'cursor-pointer hover:border-green-300 hover:bg-green-50'
              }`}
              onClick={isImporting ? undefined : onImportAgent}
            >
              <div className={`flex items-center justify-center h-full ${isImporting ? 'text-gray-400' : 'text-green-500'}`}>
                <UploadOutlined className="text-lg mr-2" />
                <span className="text-sm">{isImporting ? t('subAgentPool.button.importing') : t('subAgentPool.button.import')}</span>
              </div>
            </div>
          </div>

          {subAgentList.map((agent) => {
            const isEnabled = enabledAgentIds.includes(Number(agent.id));
            const isAvailable = agent.is_available !== false; // 默认为true，只有明确为false时才不可用
            return (
              <div 
                key={agent.id} 
                className={`border rounded-md p-3 flex flex-col justify-center transition-colors duration-200 h-[80px] ${
                  !isAvailable
                    ? isEnabled
                      ? 'bg-blue-100 border-blue-400 opacity-60'
                      : 'bg-gray-50 border-gray-200 opacity-60 cursor-not-allowed'
                    : isEnabled 
                      ? 'bg-blue-100 border-blue-400' 
                      : 'hover:border-blue-300'
                }`}
                title={!isAvailable 
                  ? isEnabled 
                    ? t('subAgentPool.tooltip.disabledAgent')
                    : t('subAgentPool.tooltip.unavailableAgent')
                  : undefined}
                onClick={() => {
                  if (!isAvailable && !isEnabled) {
                    message.warning(t('subAgentPool.message.unavailable'));
                    return;
                  }
                  // 如果Agent不可用但已启用，允许禁用它
                  if (!isAvailable && isEnabled) {
                    onSelectAgent(agent, false);
                    return;
                  }
                  onSelectAgent(agent, !isEnabled);
                }}
                onContextMenu={(e) => handleContextMenu(e, agent)}
              >
                <div className="flex items-center h-full">
                  <div className="flex-1 overflow-hidden">
                    <div className={`font-medium text-sm truncate ${!isAvailable && !isEnabled ? 'text-gray-400' : ''}`} 
                         title={!isAvailable 
                           ? isEnabled 
                             ? t('subAgentPool.tooltip.disabledAgent')
                             : t('subAgentPool.tooltip.unavailableAgent')
                           : agent.name}>
                      {agent.name}
                    </div>
                    <div 
                      className={`text-xs line-clamp-2 ${!isAvailable && !isEnabled ? 'text-gray-400' : 'text-gray-500'}`}
                      title={agent.description}
                    >
                      {agent.description}
                    </div>
                  </div>
                  <button 
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onEditAgent(agent);
                    }}
                    className={`ml-2 flex-shrink-0 flex items-center justify-center bg-transparent ${
                      !isAvailable ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-blue-500'
                    }`}
                    style={{ border: "none", padding: "4px" }}
                  >
                    <SettingOutlined style={{ fontSize: '16px' }} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>

      {/* Context Menu */}
      <AgentContextMenu
        visible={contextMenu.visible}
        x={contextMenu.x}
        y={contextMenu.y}
        agent={contextMenu.agent}
        onEdit={onEditAgent}
        onExport={onExportAgent}
        onDelete={onDeleteAgent}
        onClose={handleCloseContextMenu}
      />
    </div>
  )
}

/**
 * Tool Pool Component
 */
function ToolPool({ 
  selectedTools, 
  onSelectTool, 
  isCreatingNewAgent, 
  tools = [], 
  loadingTools = false,
  mainAgentId,
  localIsGenerating,
  onToolsRefresh
}: ToolPoolProps) {
  const { t } = useTranslation('common');

  const [isToolModalOpen, setIsToolModalOpen] = useState(false);
  const [currentTool, setCurrentTool] = useState<Tool | null>(null);
  const [pendingToolSelection, setPendingToolSelection] = useState<{tool: Tool, isSelected: boolean} | null>(null);
  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  // Use useMemo to cache the tool list to avoid unnecessary recalculations
  const displayTools = useMemo(() => {
    return tools || [];
  }, [tools]);

  // Use useMemo to cache the selected tool ID set to improve lookup efficiency
  const selectedToolIds = useMemo(() => {
    return new Set(selectedTools.map(tool => tool.id));
  }, [selectedTools]);

  // Use useCallback to cache the tool selection processing function
  const handleToolSelect = useCallback(async (tool: Tool, isSelected: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    
    const { shouldProceed, params } = await handleToolSelectCommon(
      tool,
      isSelected,
      mainAgentId,
      t,
      (tool, isSelected) => onSelectTool(tool, isSelected)
    );

    if (!shouldProceed && params) {
      setCurrentTool({
        ...tool,
        initParams: tool.initParams.map(param => ({
          ...param,
          value: params[param.name] || param.value
        }))
      });
      setPendingToolSelection({ tool, isSelected });
      setIsToolModalOpen(true);
    }
  }, [mainAgentId, onSelectTool, t]);

  // Use useCallback to cache the tool configuration click processing function
  const handleConfigClick = useCallback((tool: Tool, e: React.MouseEvent) => {
    e.stopPropagation();
    setCurrentTool(tool);
    setIsToolModalOpen(true);
  }, []);

  // Use useCallback to cache the tool save processing function
  const handleToolSave = useCallback((updatedTool: Tool) => {
    if (pendingToolSelection) {
      const { tool, isSelected } = pendingToolSelection;
      const missingRequiredFields = updatedTool.initParams
        .filter(param => param.required && (param.value === undefined || param.value === '' || param.value === null))
        .map(param => param.name);

      if (missingRequiredFields.length > 0) {
        message.error(t('toolPool.error.requiredFields', { fields: missingRequiredFields.join(', ') }));
        return;
      }

      const mockEvent = {
        stopPropagation: () => {},
        preventDefault: () => {},
        nativeEvent: new MouseEvent('click'),
        isDefaultPrevented: () => false,
        isPropagationStopped: () => false,
        persist: () => {}
      } as React.MouseEvent;
      
      handleToolSelect(updatedTool, isSelected, mockEvent);
    }
    
    setIsToolModalOpen(false);
    setPendingToolSelection(null);
  }, [pendingToolSelection, handleToolSelect, t]);

  // Use useCallback to cache the modal close processing function
  const handleModalClose = useCallback(() => {
    setIsToolModalOpen(false);
    setPendingToolSelection(null);
  }, []);

  // 刷新工具列表的处理函数
  const handleRefreshTools = useCallback(async () => {
    if (isRefreshing || localIsGenerating) return;

    setIsRefreshing(true);
    try {
      // 第一步：更新后端工具状态，重新扫描MCP和本地工具
      const updateResult = await updateToolList();
      if (!updateResult.success) {
        message.warning('更新工具状态失败，但仍会尝试获取工具列表');
      }

      // 第二步：获取最新的工具列表
      const fetchResult = await fetchTools();
      if (fetchResult.success) {
        message.success('工具列表已刷新');
        // 调用父组件的刷新回调，更新工具列表状态
        if (onToolsRefresh) {
          onToolsRefresh();
        }
      } else {
        message.error(fetchResult.message || '刷新工具列表失败');
      }
    } catch (error) {
      console.error('刷新工具列表失败:', error);
      message.error('刷新工具列表失败，请稍后重试');
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing, localIsGenerating, onToolsRefresh]);



  // 监听工具更新事件
  useEffect(() => {
    const handleToolsUpdate = () => {
      if (onToolsRefresh) {
        onToolsRefresh();
      }
    };

    window.addEventListener('toolsUpdated', handleToolsUpdate);
    return () => {
      window.removeEventListener('toolsUpdated', handleToolsUpdate);
    };
  }, [onToolsRefresh]);

  // Use memo to optimize the rendering of tool items
  const ToolItem = memo(({ tool }: { tool: Tool }) => {
    const isSelected = selectedToolIds.has(tool.id);
    const isAvailable = tool.is_available !== false; // 默认为true，只有明确为false时才不可用
    
    return (
      <div 
        className={`border rounded-md p-2 flex items-center transition-colors duration-200 min-h-[45px] ${
          !isAvailable
            ? isSelected
              ? 'bg-blue-100 border-blue-400 opacity-60'
              : 'bg-gray-50 border-gray-200 opacity-60 cursor-not-allowed'
            : isSelected 
              ? 'bg-blue-100 border-blue-400' 
              : 'hover:border-blue-300'
        } ${localIsGenerating ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        title={!isAvailable 
          ? isSelected 
            ? t('toolPool.tooltip.disabledTool')
            : t('toolPool.tooltip.unavailableTool')
          : tool.name}
        onClick={(e) => {
          if (localIsGenerating) return;
          if (!isAvailable && !isSelected) {
            message.warning(t('toolPool.message.unavailable'));
            return;
          }
          handleToolSelect(tool, !isSelected, e);
        }}
      >
        {/* Tool name left */}
        <div className="flex-1 overflow-hidden">
          <div className={`font-medium text-sm truncate ${!isAvailable && !isSelected ? 'text-gray-400' : ''}`} 
               title={!isAvailable 
                 ? isSelected 
                   ? t('toolPool.tooltip.disabledTool')
                   : t('toolPool.tooltip.unavailableTool')
                 : tool.name}>
            {tool.name}
          </div>
        </div>
        {/* Tag and settings button right */}
        <div className="flex items-center gap-2 ml-2">
          <div className="flex items-center justify-start min-w-[90px] w-[90px]">
            <Tag color={tool?.source === 'mcp' ? 'blue' : 'green'} 
                 className={`w-full text-center ${!isAvailable && !isSelected ? 'opacity-50' : ''}`}>
              {tool?.source === 'mcp' ? t('toolPool.tag.mcp') : t('toolPool.tag.local')}
            </Tag>
          </div>
          <button 
            type="button"
            onClick={(e) => {
              e.stopPropagation();  // 防止触发父元素的点击事件
              if (localIsGenerating) return;
              if (!isAvailable) {
                if (isSelected) {
                  handleToolSelect(tool, false, e);
                } else {
                  message.warning(t('toolPool.message.unavailable'));
                }
                return;
              }
              handleConfigClick(tool, e);
            }}
            disabled={localIsGenerating}
            className={`flex-shrink-0 flex items-center justify-center bg-transparent ${
              localIsGenerating ? 'text-gray-300 cursor-not-allowed' : 'text-gray-500 hover:text-blue-500'
            }`}
            style={{ border: "none", padding: "4px" }}
          >
            <SettingOutlined style={{ fontSize: '16px' }} />
          </button>
        </div>
      </div>
    );
  });

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex justify-between items-center mb-2">
        <h2 className="text-lg font-medium">{t('toolPool.title')}</h2>
        <div className="flex items-center gap-2">
          <Button
            type="text"
            size="small"
            icon={isRefreshing ? <LoadingOutlined /> : <ReloadOutlined />}
            onClick={handleRefreshTools}
            disabled={localIsGenerating || isRefreshing}
            className="text-green-500 hover:text-green-600 hover:bg-green-50"
            title="刷新工具列表"
          >
            {isRefreshing ? '刷新中' : '刷新工具'}
          </Button>
          <Button
            type="text"
            size="small"
            icon={<ApiOutlined />}
            onClick={() => setIsMcpModalOpen(true)}
            disabled={localIsGenerating}
            className="text-blue-500 hover:text-blue-600 hover:bg-blue-50"
            title="配置MCP服务器"
          >
            MCP配置
          </Button>
          {loadingTools && <span className="text-sm text-gray-500">{t('toolPool.loading')}</span>}
        </div>
      </div>
      <ScrollArea className="flex-1 min-h-0 border-t pt-2 pb-2">
        {loadingTools ? (
          <div className="flex items-center justify-center h-full">
            <span className="text-gray-500">{t('toolPool.loadingTools')}</span>
          </div>
        ) : (
          <div className="flex flex-col gap-3 pr-2">
            {displayTools.map((tool) => (
              <ToolItem key={tool.id} tool={tool} />
            ))}
          </div>
        )}
      </ScrollArea>

      <ToolConfigModal
        isOpen={isToolModalOpen}
        onCancel={handleModalClose}
        onSave={handleToolSave}
        tool={currentTool}
        mainAgentId={parseInt(mainAgentId || '0')}
        selectedTools={selectedTools}
      />

      <McpConfigModal
        visible={isMcpModalOpen}
        onCancel={() => setIsMcpModalOpen(false)}
      />
    </div>
  );
}

// Use memo to optimize the rendering of ToolPool component
export const MemoizedToolPool = memo(ToolPool);

/**
 * Business Logic Configuration Main Component
 */
export default function BusinessLogicConfig({
  businessLogic,
  setBusinessLogic,
  selectedAgents,
  setSelectedAgents,
  selectedTools,
  setSelectedTools,
  systemPrompt,
  setSystemPrompt,
  isCreatingNewAgent,
  setIsCreatingNewAgent,
  mainAgentModel,
  setMainAgentModel,
  mainAgentMaxStep,
  setMainAgentMaxStep,
  tools,
  subAgentList = [],
  loadingAgents = false,
  mainAgentId,
  setMainAgentId,
  setSubAgentList,
  enabledAgentIds,
  setEnabledAgentIds,
  newAgentName,
  newAgentDescription,
  newAgentProvideSummary,
  setNewAgentName,
  setNewAgentDescription,
  setNewAgentProvideSummary,
  isNewAgentInfoValid,
  setIsNewAgentInfoValid,
  onEditingStateChange,
  onToolsRefresh
}: BusinessLogicConfigProps) {
  const [enabledToolIds, setEnabledToolIds] = useState<number[]>([]);
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [fileList, setFileList] = useState<any[]>([]);
  const [isImporting, setIsImporting] = useState(false);
  const [isPromptGenerating, setIsPromptGenerating] = useState(false);
  const [isPromptSaving, setIsPromptSaving] = useState(false);
  const [localIsGenerating, setLocalIsGenerating] = useState(false);
  
  // Delete confirmation popup status
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [agentToDelete, setAgentToDelete] = useState<Agent | null>(null);

  // Edit agent related status
  const [isEditingAgent, setIsEditingAgent] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);

  const { t } = useTranslation('common');

  // Common refresh agent list function, moved to the front to avoid hoisting issues
  const refreshAgentList = async (t: TFunction) => {
    if (!mainAgentId) return;
    
    setIsLoadingTools(true);
    // Clear the tool selection status when loading starts
    setSelectedTools([]);
    setEnabledToolIds([]);
    
    try {
      const result = await fetchAgentList();
      if (result.success) {
        // Update all related states
        setSubAgentList(result.data.subAgentList);
        setMainAgentId(result.data.mainAgentId);
        const newEnabledToolIds = result.data.enabledToolIds || [];
        setEnabledToolIds(newEnabledToolIds);
        
        // Update the status of the newly added fields
        if (result.data.modelName) {
          setMainAgentModel(result.data.modelName as OpenAIModel);
        }
        if (result.data.maxSteps) {
          setMainAgentMaxStep(result.data.maxSteps);
        }
        if (result.data.businessDescription) {
          setBusinessLogic(result.data.businessDescription);
        }
        if (result.data.prompt) {
          setSystemPrompt(result.data.prompt);
        }
        
        // Update the selected tools
        if (tools && tools.length > 0) {
          const enabledTools = tools.filter(tool => 
            newEnabledToolIds.includes(Number(tool.id))
          );
          setSelectedTools(enabledTools);
        }
      } else {
        message.error(result.message || t('businessLogic.config.error.agentListFailed'));
      }
    } catch (error) {
      console.error('获取 Agent 列表失败:', error);
      message.error(t('businessLogic.config.error.agentListFailed'));
    } finally {
      setIsLoadingTools(false);
    }
  };

  const fetchSubAgentIdAndEnableToolList = async (t: TFunction) => {
    setIsLoadingTools(true);
    // Clear the tool selection status when loading starts
    setSelectedTools([]);
    setEnabledToolIds([]);
    
    try {
      const result = await getCreatingSubAgentId(mainAgentId);
      if (result.success && result.data) {
        const { agentId, enabledToolIds, modelName, maxSteps, businessDescription, prompt } = result.data;
        
        // Update the main agent ID
        setMainAgentId(agentId);
        // Update the enabled tool ID list
        setEnabledToolIds(enabledToolIds);
        // Update the model
        if (modelName) {
          setMainAgentModel(modelName as OpenAIModel);
        }
        // Update the maximum number of steps
        if (maxSteps) {
          setMainAgentMaxStep(maxSteps);
        }
        // Update the business description
        if (businessDescription) {
          setBusinessLogic(businessDescription);
        }
        // Update the system prompt
        if (prompt) {
          setSystemPrompt(prompt);
        }
      } else {
        message.error(result.message || t('businessLogic.config.error.agentIdFailed'));
      }
    } catch (error) {
      console.error('创建新Agent失败:', error);
      message.error(t('businessLogic.config.error.agentIdFailed'));
    } finally {
      setIsLoadingTools(false);
    }
  };

  // Listen for changes in the creation of a new Agent
  useEffect(() => {
    if (isCreatingNewAgent) {
      // When switching to the creation of a new Agent, clear the relevant status
      setSelectedAgents([]);
      
      if (!isEditingAgent) {
        // Only clear and get new Agent configuration in creating mode
        setBusinessLogic('');
        setSystemPrompt(''); // Also clear the system prompt
        fetchSubAgentIdAndEnableToolList(t);
        // Reset new agent info states when entering creating mode
        setNewAgentName('');
        setNewAgentDescription('');
        setNewAgentProvideSummary(true);
        setIsNewAgentInfoValid(false);
      } else {
        // In edit mode, data is loaded in handleEditAgent, here validate the form
        setIsNewAgentInfoValid(true); // Assume data is valid when editing
        console.log('Edit mode useEffect - Do not clear data'); // Debug information
      }
    } else {
      // When exiting the creation of a new Agent, reset the main Agent configuration and refresh the list
      if (!isEditingAgent) {
        setBusinessLogic('');
        setSystemPrompt(''); // Also clear the system prompt
        setMainAgentModel(OpenAIModel.MainModel);
        setMainAgentMaxStep(5);
        refreshAgentList(t);
      }
    }
  }, [isCreatingNewAgent, isEditingAgent]);

  // Listen for changes in the tool status, update the selected tool
  useEffect(() => {
    if (!tools || !enabledToolIds || isLoadingTools) return;

    const enabledTools = tools.filter(tool => 
      enabledToolIds.includes(Number(tool.id))
    );

    setSelectedTools(prevTools => {
      // Only update when the tool list is确实不同时
      if (JSON.stringify(prevTools) !== JSON.stringify(enabledTools)) {
        return enabledTools;
      }
      return prevTools;
    });
  }, [tools, enabledToolIds, isLoadingTools]);

  // Handle the creation of a new Agent
  const handleCreateNewAgent = async () => {
    // Set to create mode
    setIsEditingAgent(false);
    setEditingAgent(null);
    setIsCreatingNewAgent(true);
    onEditingStateChange?.(false, null);
  };

  // Reset the status when the user cancels the creation of an Agent
  const handleCancelCreating = async () => {
    setIsCreatingNewAgent(false);
    setIsEditingAgent(false);
    setEditingAgent(null);
    // Reset agent info states
    setNewAgentName('');
    setNewAgentDescription('');
    setNewAgentProvideSummary(true);
    setIsNewAgentInfoValid(false);
    // 通知外部编辑状态变化
    onEditingStateChange?.(false, null);
  };

  // Handle the creation of a new Agent
  const handleSaveNewAgent = async (name: string, description: string, model: string, max_step: number, provide_run_summary: boolean, prompt: string, business_description: string) => {
    if (name.trim() && mainAgentId) {
      try {
        let result;
        
        if (isEditingAgent && editingAgent) {
          result = await updateAgent(
            Number(editingAgent.id),
            name,
            description,
            model,
            max_step,
            provide_run_summary,
            prompt,
            undefined,
            business_description
          );
        } else {
          result = await updateAgent(
            Number(mainAgentId),
            name,
            description,
            model,
            max_step,
            provide_run_summary,
            prompt,
            undefined,
            business_description
          );
        }

        if (result.success) {
          const actionText = isEditingAgent ? t('agent.action.modify') : t('agent.action.create');
          message.success(t('businessLogic.config.message.agentCreated', { name, action: actionText }));

          setIsCreatingNewAgent(false);
          setIsEditingAgent(false);
          setEditingAgent(null);
          onEditingStateChange?.(false, null);

          setBusinessLogic('');
          setSelectedTools([]);
          setNewAgentName('');
          setNewAgentDescription('');
          setNewAgentProvideSummary(true);
          setSystemPrompt('');
          
          refreshAgentList(t);
        } else {
          message.error(result.message || t('businessLogic.config.error.saveFailed'));
        }
      } catch (error) {
        console.error('Error saving agent:', error);
        message.error(t('businessLogic.config.error.saveRetry'));
      }
    } else {
      if (!name.trim()) {
        message.error(t('businessLogic.config.error.nameEmpty'));
      }
      if (!mainAgentId) {
        message.error(t('businessLogic.config.error.noAgentId'));
      }
    }
  };

  const handleSaveAsAgent = () => {
    if (!isNewAgentInfoValid) {
      message.warning(t('businessLogic.config.message.completeAgentInfo'));
      return;
    }
    if (systemPrompt.trim().length === 0) {
      message.warning(t('businessLogic.config.message.generatePromptFirst'));
      return;
    }
    handleSaveNewAgent(
      newAgentName, 
      newAgentDescription, 
      mainAgentModel, 
      mainAgentMaxStep, 
      newAgentProvideSummary, 
      systemPrompt, 
      businessLogic
    );
  };

  const handleEditAgent = async (agent: Agent, t: TFunction) => {
    try {
      // 首先设置为编辑模式，避免useEffect清空数据
      setIsEditingAgent(true);
      setEditingAgent(agent); // 先用传入的agent，稍后会用详细数据替换
      setIsCreatingNewAgent(true);
      // 通知外部编辑状态变化
      onEditingStateChange?.(true, agent);
      
      // 调用查询接口获取完整的Agent信息
      const result = await searchAgentInfo(Number(agent.id));
      
      if (!result.success || !result.data) {
        message.error(result.message || t('businessLogic.config.error.agentDetailFailed'));
        // 如果获取失败，重置编辑状态
        setIsEditingAgent(false);
        setEditingAgent(null);
        setIsCreatingNewAgent(false);
        onEditingStateChange?.(false, null);
        return;
      }
      
      const agentDetail = result.data;
      
      console.log('加载的Agent详情:', agentDetail); // 调试信息
      
      // 更新为完整的Agent数据
      setEditingAgent(agentDetail);
      // 通知外部编辑状态变化（使用完整数据）
      onEditingStateChange?.(true, agentDetail);
      
      // 加载Agent数据到界面
      setNewAgentName(agentDetail.name);
      setNewAgentDescription(agentDetail.description);
      setNewAgentProvideSummary(agentDetail.provide_run_summary);
      setMainAgentModel(agentDetail.model as OpenAIModel);
      setMainAgentMaxStep(agentDetail.max_step);
      setBusinessLogic(agentDetail.business_description || '');
      setSystemPrompt(agentDetail.prompt || '');
      
      console.log('设置的业务描述:', agentDetail.business_description); // 调试信息
      console.log('设置的系统提示词:', agentDetail.prompt); // 调试信息
      
      // 加载Agent的工具
      if (agentDetail.tools && agentDetail.tools.length > 0) {
        setSelectedTools(agentDetail.tools);
        // 设置已启用的工具ID
        const toolIds = agentDetail.tools.map((tool: any) => Number(tool.id));
        setEnabledToolIds(toolIds);
        console.log('加载的工具:', agentDetail.tools); // 调试信息
      } else {
        setSelectedTools([]);
        setEnabledToolIds([]);
      }
      
      message.success(t('businessLogic.config.message.agentInfoLoaded'));
    } catch (error) {
      console.error('加载Agent详情失败:', error);
      message.error(t('businessLogic.config.error.agentDetailFailed'));
      // 如果出错，重置编辑状态
      setIsEditingAgent(false);
      setEditingAgent(null);
      setIsCreatingNewAgent(false);
      onEditingStateChange?.(false, null);
    }
  };

  // Handle the update of the Agent selection status
  const handleAgentSelect = async (agent: Agent, isSelected: boolean) => {
    if (agent.is_available === false && isSelected) {
      message.error(t('agent.error.disabledAgent'));
      return;
    }

    try {
      const result = await updateAgent(
        Number(agent.id),
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        isSelected
      );

      if (result.success) {
        if (isSelected) {
          setSelectedAgents([...selectedAgents, agent]);
          setEnabledAgentIds([...enabledAgentIds, Number(agent.id)]);
        } else {
          setSelectedAgents(selectedAgents.filter((a) => a.id !== agent.id));
          setEnabledAgentIds(enabledAgentIds.filter(id => id !== Number(agent.id)));
        }
        message.success(t('businessLogic.config.message.agentStatusUpdated', {
          name: agent.name,
          status: isSelected ? t('common.enabled') : t('common.disabled')
        }));
      } else {
        message.error(result.message || t('agent.error.statusUpdateFailed'));
      }
    } catch (error) {
      console.error('更新 Agent 状态失败:', error);
      message.error(t('agent.error.statusUpdateRetry'));
    }
  };

  // Handle the update of the model
  const handleModelChange = async (value: OpenAIModel) => {
    const targetAgentId = isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;
    
    if (!targetAgentId) {
      message.error(t('businessLogic.config.error.noAgentId'));
      return;
    }

    try {
      const result = await updateAgent(
        Number(targetAgentId),
        undefined,
        undefined,
        value,
        undefined,
        undefined,
        undefined,
        undefined
      );

      if (result.success) {
        setMainAgentModel(value);
        message.success(t('businessLogic.config.message.modelUpdateSuccess'));
      } else {
        message.error(result.message || t('businessLogic.config.error.modelUpdateFailed'));
      }
    } catch (error) {
      console.error('更新模型失败:', error);
      message.error(t('businessLogic.config.error.modelUpdateRetry'));
    }
  };

  // Handle the update of the maximum number of steps
  const handleMaxStepChange = async (value: number | null) => {
    const targetAgentId = isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;
    
    if (!targetAgentId) {
      message.error(t('businessLogic.config.error.noAgentId'));
      return;
    }

    const newValue = value ?? 5;
    
    try {
      const result = await updateAgent(
        Number(targetAgentId),
        undefined,
        undefined,
        undefined,
        newValue,
        undefined,
        undefined,
        undefined
      );

      if (result.success) {
        setMainAgentMaxStep(newValue);
        message.success(t('businessLogic.config.message.maxStepsUpdateSuccess'));
      } else {
        message.error(result.message || t('businessLogic.config.error.maxStepsUpdateFailed'));
      }
    } catch (error) {
      console.error('更新最大步骤数失败:', error);
      message.error(t('businessLogic.config.error.maxStepsUpdateRetry'));
    }
  };

  // Handle importing agent
  const handleImportAgent = (t: TFunction) => {
    if (!mainAgentId) {
      message.error(t('businessLogic.config.error.noAgentId'));
      return;
    }

    // Create a hidden file input element
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.json';
    fileInput.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;

      // Check file type
      if (!file.name.endsWith('.json')) {
        message.error(t('businessLogic.config.error.invalidFileType'));
        return;
      }

      setIsImporting(true);
      try {
        // Read file content
        const fileContent = await file.text();
        let agentInfo;

        try {
          agentInfo = JSON.parse(fileContent);
        } catch (parseError) {
          message.error(t('businessLogic.config.error.invalidFileType'));
          setIsImporting(false);
          return;
        }

        // Call import API
        const result = await importAgent(mainAgentId, agentInfo);

        if (result.success) {
          message.success(t('businessLogic.config.error.agentImportSuccess'));
          // Refresh agent list
          refreshAgentList(t);
        } else {
          message.error(result.message || t('businessLogic.config.error.agentImportFailed'));
        }
      } catch (error) {
        console.error('导入Agent失败:', error);
        message.error(t('businessLogic.config.error.agentImportFailed'));
      } finally {
        setIsImporting(false);
      }
    };

    fileInput.click();
  };

  // Handle exporting agent
  const handleExportAgent = async (agent: Agent, t: TFunction) => {
    try {
      const result = await exportAgent(Number(agent.id));
      if (result.success) {
        // 处理后端返回的字符串或对象
        let exportData = result.data;
        if (typeof exportData === 'string') {
          try {
            exportData = JSON.parse(exportData);
          } catch (e) {
            // 如果解析失败，说明本身就是字符串，直接导出
          }
        }
        const blob = new Blob([JSON.stringify(exportData, null, 2)], {
          type: 'application/json'
        });

        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${agent.name}_config.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        message.success(t('businessLogic.config.message.agentExportSuccess'));
      } else {
        message.error(result.message || t('businessLogic.config.error.agentExportFailed'));
      }
    } catch (error) {
      console.error('导出Agent失败:', error);
      message.error(t('businessLogic.config.error.agentExportFailed'));
    }
  };

  // Handle deleting agent
  const handleDeleteAgent = async (agent: Agent) => {
    // Show confirmation dialog
    setAgentToDelete(agent);
    setIsDeleteConfirmOpen(true);
  };

  // Handle confirmed deletion
  const handleConfirmDelete = async (t: TFunction) => {
    if (!agentToDelete) return;

    try {
      const result = await deleteAgent(Number(agentToDelete.id));
      if (result.success) {
        message.success(t('businessLogic.config.error.agentDeleteSuccess', { name: agentToDelete.name }));
        // Refresh agent list
        refreshAgentList(t);
      } else {
        message.error(result.message || t('businessLogic.config.error.agentDeleteFailed'));
      }
    } catch (error) {
      console.error('删除Agent失败:', error);
      message.error(t('businessLogic.config.error.agentDeleteFailed'));
    } finally {
      setIsDeleteConfirmOpen(false);
      setAgentToDelete(null);
    }
  };

  // Generate system prompt
  const handleGenerateSystemPrompt = async (t: TFunction) => {
    if (!businessLogic || businessLogic.trim() === '') {
      message.warning(t('businessLogic.config.error.businessDescriptionRequired'));
      return;
    }

    const targetAgentId = isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;
    
    if (!targetAgentId) {
      message.warning(t('businessLogic.config.error.noAgentIdForPrompt'));
      return;
    }
    
    try {
      setIsPromptGenerating(true);
      setLocalIsGenerating(true);
      setSystemPrompt('');
      await generatePromptStream(
        {
          agent_id: Number(targetAgentId),
          task_description: businessLogic
        },
        (streamedText) => {
          setSystemPrompt(streamedText);
        },
        (err) => {
          message.error(t('businessLogic.config.error.promptGenerateFailed', {
            error: err instanceof Error ? err.message : t('common.unknownError')
          }));
          setIsPromptGenerating(false);
          setLocalIsGenerating(false);
        },
        () => {
          setIsPromptGenerating(false);
          setLocalIsGenerating(false);
          message.success(t('businessLogic.config.message.promptGenerateSuccess'));
        }
      );
    } catch (error) {
      console.error('生成提示词失败:', error);
      message.error(t('businessLogic.config.error.promptGenerateFailed', {
        error: error instanceof Error ? error.message : t('common.unknownError')
      }));
      setIsPromptGenerating(false);
      setLocalIsGenerating(false);
    }
  };

  // Save system prompt
  const handleSaveSystemPrompt = async () => {
    const targetAgentId = isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;
    
    if (!targetAgentId) {
      message.warning(t('businessLogic.config.error.noAgentIdForPrompt'));
      return;
    }
    if (!systemPrompt || systemPrompt.trim() === '') {
      message.warning(t('businessLogic.config.message.promptEmpty'));
      return;
    }
    
    try {
      setIsPromptSaving(true);
      await savePrompt({ agent_id: Number(targetAgentId), prompt: systemPrompt });
      message.success(t('businessLogic.config.message.promptSaved'));
    } catch (error) {
      console.error('保存提示词失败:', error);
      message.error(t('businessLogic.config.error.promptSaveFailed'));
    } finally {
      setIsPromptSaving(false);
    }
  };

  // 刷新工具列表
  const handleToolsRefresh = useCallback(async () => {
    if (onToolsRefresh) {
      await onToolsRefresh();
    }
  }, [onToolsRefresh]);

  const canSaveAsAgent = selectedAgents.length === 0 && systemPrompt.trim().length > 0 && isNewAgentInfoValid;

  // Generate more intelligent prompt information according to conditions
  const getButtonTitle = () => {
    if (selectedAgents.length > 0) {
      return t('businessLogic.config.message.noAgentSelected');
    }
    if (systemPrompt.trim().length === 0) {
      return t('businessLogic.config.message.generatePromptFirst');
    }
    if (!isNewAgentInfoValid) {
      return t('businessLogic.config.message.completeAgentInfo');
    }
    return "";
  };

  return (
    <div className="flex flex-col h-full w-full gap-0 justify-between">
      {/* Upper part: Agent pool + Tool pool */}
      <div className="flex gap-4 flex-1 min-h-0 pb-4 pr-4 pl-4">
        {!isCreatingNewAgent && (
          <div className="w-[360px] h-full">
            <SubAgentPool
              selectedAgents={selectedAgents}
              onSelectAgent={handleAgentSelect}
              onEditAgent={(agent) => handleEditAgent(agent, t)}
              onCreateNewAgent={handleCreateNewAgent}
              onImportAgent={() => handleImportAgent(t)}
              onExportAgent={(agent) => handleExportAgent(agent, t)}
              onDeleteAgent={handleDeleteAgent}
              subAgentList={subAgentList}
              loadingAgents={loadingAgents}
              enabledAgentIds={enabledAgentIds}
              isImporting={isImporting}
            />
          </div>
        )}
        
        {isCreatingNewAgent && (
          <div className="w-[360px] h-full">
            <AgentInfoInput
              name={newAgentName}
              description={newAgentDescription}
              provideSummary={newAgentProvideSummary}
              onNameChange={setNewAgentName}
              onDescriptionChange={setNewAgentDescription}
              onProvideSummaryChange={setNewAgentProvideSummary}
              onValidationChange={setIsNewAgentInfoValid}
            />
          </div>
        )}
        
        <div className="flex-1 h-full">
          <MemoizedToolPool
            selectedTools={isLoadingTools ? [] : selectedTools}
            onSelectTool={(tool, isSelected) => {
              if (isLoadingTools) return;
              setSelectedTools(prevTools => {
                if (isSelected) {
                  return [...prevTools, tool];
                } else {
                  return prevTools.filter(t => t.id !== tool.id);
                }
              });
            }}
            isCreatingNewAgent={isCreatingNewAgent}
            tools={tools}
            loadingTools={isLoadingTools}
            mainAgentId={isEditingAgent && editingAgent ? editingAgent.id : mainAgentId}
            localIsGenerating={localIsGenerating}
            onToolsRefresh={handleToolsRefresh}
          />
        </div>
      </div>

      {/* The second half: business logic description */}
      <div className="flex gap-4 h-[240px] pb-4 pr-4 pl-4 items-start">
        <div className="flex-1 h-full">
          <BusinessLogicInput 
            value={businessLogic} 
            onChange={setBusinessLogic} 
            selectedAgents={selectedAgents}
            systemPrompt={systemPrompt}
          />
        </div>
        <div className="w-[280px] h-[200px] flex flex-col self-start">
          <div className="flex flex-col gap-5 flex-1">
            <div>
              <span className="block text-lg font-medium mb-2">{t('businessLogic.config.model')}</span>
              <Select
                value={mainAgentModel}
                onChange={handleModelChange}
                className="w-full"
                options={ModelOptions()}
              />
            </div>
            <div>
              <span className="block text-lg font-medium mb-2">{t('businessLogic.config.maxSteps')}</span>
              <InputNumber
                min={1}
                max={20}
                value={mainAgentMaxStep}
                onChange={handleMaxStepChange}
                className="w-full"
              />
            </div>
            <div className="flex justify-start gap-2 w-full mt-4">
              <button
                onClick={() => handleGenerateSystemPrompt(t)}
                disabled={isPromptGenerating || isPromptSaving}
                className="px-3.5 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ border: 'none' }}
              >
                {isPromptGenerating ? (
                  <>
                    <LoadingOutlined spin className="mr-1" />
                    {t('businessLogic.config.button.generating')}
                  </>
                ) : (
                  <>
                    <ThunderboltOutlined className="mr-1" />
                    {t('businessLogic.config.button.generatePrompt')}
                  </>
                )}
              </button>
              {isCreatingNewAgent && (
                <>
                  <button
                    onClick={handleSaveAsAgent}
                    disabled={!canSaveAsAgent}
                    title={getButtonTitle()}
                    className="px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-green-500 text-white hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ border: "none" }}
                  >
                    {isPromptSaving ? t('businessLogic.config.button.saving') : t('businessLogic.config.button.save')}
                  </button>
                  <button
                    onClick={handleCancelCreating}
                    disabled={isPromptGenerating || isPromptSaving}
                    className="px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ border: 'none' }}
                  >
                    {t('businessLogic.config.button.cancel')}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Delete confirmation popup */}
      <Modal
        title={t('businessLogic.config.modal.deleteTitle')}
        open={isDeleteConfirmOpen}
        onCancel={() => setIsDeleteConfirmOpen(false)}
        footer={
          <div className="flex justify-end gap-2">
            <button 
              onClick={() => setIsDeleteConfirmOpen(false)}
              className="px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-gray-100 text-gray-700 hover:bg-gray-200"
              style={{ border: "none" }}
            >
              {t('businessLogic.config.modal.button.cancel')}
            </button>
            <button 
              onClick={() => handleConfirmDelete(t)}
              className="px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-red-500 text-white hover:bg-red-600"
              style={{ border: "none" }}
            >
              {t('businessLogic.config.modal.button.confirm')}
            </button>
          </div>
        }
        width={400}
      >
        <div className="py-4">
          <Typography.Text>
            {t('businessLogic.config.modal.deleteContent', { name: agentToDelete?.name })}
          </Typography.Text>
        </div>
      </Modal>
    </div>
  )
}