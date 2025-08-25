"use client"

import { useState, useEffect, useMemo, useCallback, memo } from 'react'
import { Button, App, Tabs } from 'antd'
import { SettingOutlined, LoadingOutlined, ApiOutlined, ReloadOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

import { Tooltip as CustomTooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import ToolConfigModal from './ToolConfigModal'
import McpConfigModal from './McpConfigModal'
import { Tool } from '@/types/agent'
import { fetchTools } from '@/services/agentConfigService'
import { updateToolList } from '@/services/mcpService'
import { handleToolSelectCommon } from '../utils/agentUtils'

interface ToolPoolProps {
  selectedTools: Tool[];
  onSelectTool: (tool: Tool, isSelected: boolean) => void;
  tools?: Tool[];
  loadingTools?: boolean;
  mainAgentId?: string | null;
  localIsGenerating?: boolean;
  onToolsRefresh?: () => void;
  isEditingMode?: boolean; // 新增：控制是否处于编辑模式
  isGeneratingAgent?: boolean; // 新增：生成智能体状态
}

// 工具分组接口
interface ToolGroup {
  key: string;
  label: string;
  tools: Tool[];
}

/**
 * Tool Pool Component
 */
function ToolPool({ 
  selectedTools, 
  onSelectTool, 
  tools = [], 
  loadingTools = false,
  mainAgentId,
  localIsGenerating = false,
  onToolsRefresh,
  isEditingMode = false, // 新增：默认不处于编辑模式
  isGeneratingAgent = false // 新增：默认不在生成状态
}: ToolPoolProps) {
  const { t } = useTranslation('common');
  const { message } = App.useApp();

  const [isToolModalOpen, setIsToolModalOpen] = useState(false);
  const [currentTool, setCurrentTool] = useState<Tool | null>(null);
  const [pendingToolSelection, setPendingToolSelection] = useState<{tool: Tool, isSelected: boolean} | null>(null);
  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeTabKey, setActiveTabKey] = useState<string>('');
  
  // 使用 useMemo 缓存工具分组
  const toolGroups = useMemo(() => {
    const groups: ToolGroup[] = [];
    const groupMap = new Map<string, Tool[]>();
    
    // 按 source 和 usage 分组
    tools.forEach(tool => {
      let groupKey: string;
      let groupLabel: string;
      
      if (tool.source === 'mcp') {
        // MCP 工具按 usage 分组
        const usage = tool.usage || 'other';
        groupKey = `mcp-${usage}`;
        groupLabel = usage;
      } else if (tool.source === 'local') {
        groupKey = 'local';
        groupLabel = t('toolPool.group.local');
      } else if (tool.source === 'langchain') {
        groupKey = 'langchain';
        groupLabel = t('toolPool.group.langchain');
      } else {
        // 其他类型
        groupKey = tool.source || 'other';
        groupLabel = tool.source || t('toolPool.group.other');
      }
      
      if (!groupMap.has(groupKey)) {
        groupMap.set(groupKey, []);
      }
      groupMap.get(groupKey)!.push(tool);
    });
    
    // 转换为数组并排序
    groupMap.forEach((tools, key) => {
      const sortedTools = tools.sort((a, b) => {
        // 按创建时间排序
        if (!a.create_time && !b.create_time) return 0;
        if (!a.create_time) return 1;
        if (!b.create_time) return -1;
        return a.create_time.localeCompare(b.create_time);
      });
      
      groups.push({
        key,
        label: key.startsWith('mcp-') ? key.replace('mcp-', '') : (
          key === 'local' ? t('toolPool.group.local') :
          key === 'langchain' ? t('toolPool.group.langchain') :
          key
        ),
        tools: sortedTools
      });
    });
    
    // 按优先级排序：local > langchain > mcp groups
    return groups.sort((a, b) => {
      const getPriority = (key: string) => {
        if (key === 'local') return 1;
        if (key === 'langchain') return 2;
        if (key.startsWith('mcp-')) return 3;
        return 4;
      };
      return getPriority(a.key) - getPriority(b.key);
    });
  }, [tools, t]);

  // 设置默认激活的标签
  useEffect(() => {
    if (toolGroups.length > 0 && !activeTabKey) {
      setActiveTabKey(toolGroups[0].key);
    }
  }, [toolGroups, activeTabKey]);

  // Use useMemo to cache the selected tool ID set to improve lookup efficiency
  const selectedToolIds = useMemo(() => {
    return new Set(selectedTools.map(tool => tool.id));
  }, [selectedTools]);

  // Use useCallback to cache the tool selection processing function
  const handleToolSelect = useCallback(async (tool: Tool, isSelected: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    
    // 在生成过程中禁止选择工具
    if (isGeneratingAgent) {
      return;
    }
    
    const { shouldProceed, params } = await handleToolSelectCommon(
      tool,
      isSelected,
      mainAgentId,
      t,
      message,
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
  }, [mainAgentId, onSelectTool, t, isGeneratingAgent, message]);

  // Use useCallback to cache the tool configuration click processing function
  const handleConfigClick = useCallback((tool: Tool, e: React.MouseEvent) => {
    e.stopPropagation();
    
    // 在生成过程中禁止配置工具
    if (isGeneratingAgent) {
      return;
    }
    
    setCurrentTool(tool);
    setIsToolModalOpen(true);
  }, [isGeneratingAgent]);

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
        message.warning(t('toolManagement.message.updateStatusFailed'));
      }

      // 第二步：获取最新的工具列表
      const fetchResult = await fetchTools();
      if (fetchResult.success) {
        // 调用父组件的刷新回调，更新工具列表状态
        if (onToolsRefresh) {
          onToolsRefresh();
        }
      } else {
        message.error(fetchResult.message || t('toolManagement.message.refreshFailed'));
      }
    } catch (error) {
      console.error(t('debug.console.refreshToolsFailed'), error);
      message.error(t('toolManagement.message.refreshFailedRetry'));
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing, localIsGenerating, onToolsRefresh, t]);

  // 监听工具更新事件
  useEffect(() => {
    const handleToolsUpdate = async () => {
      try {
        // 重新获取最新的工具列表，确保包含新添加的MCP工具
        const fetchResult = await fetchTools();
        if (fetchResult.success) {
          // 调用父组件的刷新回调，更新工具列表状态
          if (onToolsRefresh) {
            onToolsRefresh();
          }
        } else {
          console.error('MCP配置后自动刷新工具列表失败:', fetchResult.message);
        }
      } catch (error) {
        console.error('MCP配置后自动刷新工具列表出错:', error);
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
    const isDisabled = localIsGenerating || !isEditingMode || isGeneratingAgent; // 在非编辑模式或生成过程中禁用选择
    
    return (
      <div 
        className={`border-2 rounded-md p-2 flex items-center transition-all duration-300 ease-in-out min-h-[45px] shadow-sm ${
          !isAvailable
            ? isSelected
              ? 'bg-blue-100 border-blue-400 opacity-60'
              : 'bg-gray-50 border-gray-200 opacity-60 cursor-not-allowed'
            : isSelected 
              ? 'bg-blue-100 border-blue-400 shadow-md' 
              : 'border-gray-200 hover:border-blue-300 hover:shadow-md'
        } ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        title={!isAvailable 
          ? isSelected 
            ? t('toolPool.tooltip.disabledTool')
            : t('toolPool.tooltip.unavailableTool')
          : !isEditingMode
            ? t('toolPool.tooltip.viewOnlyMode')
            : tool.name}
        onClick={(e) => {
          if (isDisabled) return;
          if (!isAvailable && !isSelected) {
            message.warning(t('toolPool.message.unavailable'));
            return;
          }
          handleToolSelect(tool, !isSelected, e);
        }}
      >
        {/* Tool name left */}
        <div className="flex-1 overflow-hidden">
          <CustomTooltip>
            <TooltipTrigger asChild>
              <div
                className={`font-medium text-sm truncate transition-colors duration-300 ${!isAvailable && !isSelected ? 'text-gray-400' : ''}`}
                style={{
                  maxWidth: '300px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  display: 'inline-block',
                  verticalAlign: 'middle'
                }}
              >
                {tool.name}
              </div>
            </TooltipTrigger>
            <TooltipContent side="top">
              {tool.name}
            </TooltipContent>
          </CustomTooltip>
        </div>
        {/* Settings button right - 移除了Tag标签 */}
        <div className="flex items-center gap-2 ml-2">
          <button 
            type="button"
            onClick={(e) => {
              e.stopPropagation();  // 防止触发父元素的点击事件
              if (localIsGenerating || isGeneratingAgent) return;
              if (!isAvailable) {
                if (isSelected && isEditingMode) {
                  handleToolSelect(tool, false, e);
                } else if (!isEditingMode) {
                  message.warning(t('toolPool.message.viewOnlyMode'));
                  return;
                } else {
                  message.warning(t('toolPool.message.unavailable'));
                }
                return;
              }
              handleConfigClick(tool, e);
            }}
            disabled={localIsGenerating || isGeneratingAgent}
            className={`flex-shrink-0 flex items-center justify-center bg-transparent ${
              localIsGenerating || isGeneratingAgent ? 'text-gray-300 cursor-not-allowed' : 'text-gray-500 hover:text-blue-500'
            }`}
            style={{ border: "none", padding: "4px" }}
          >
            <SettingOutlined style={{ fontSize: '16px' }} />
          </button>
        </div>
      </div>
    );
  });

  // 生成 Tabs 配置
  const tabItems = toolGroups.map(group => {
    // 限制标签显示最多7个字符
    const displayLabel = group.label.length > 7 ? `${group.label.substring(0, 7)}...` : group.label;
    
    return {
      key: group.key,
      label: (
        <span style={{ 
          display: 'block',
          maxWidth: '70px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}>
          {displayLabel}
        </span>
      ),
      children: (
        <div 
          className="flex flex-col gap-3 pr-2" 
          style={{ 
            height: '100%', 
            overflowY: 'auto', 
            padding: '8px 0',
            maxHeight: '100%'
          }}
        >
          {group.tools.map((tool) => (
            <ToolItem key={tool.id} tool={tool} />
          ))}
        </div>
      )
    };
  });

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex justify-between items-center mb-2 flex-shrink-0">
        <div className="flex items-center">
          <h4 className="text-md font-medium text-gray-700">{t('toolPool.title')}</h4>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="text"
            size="small"
            icon={isRefreshing ? <LoadingOutlined /> : <ReloadOutlined />}
            onClick={handleRefreshTools}
            disabled={localIsGenerating || isRefreshing || isGeneratingAgent}
            className="text-green-500 hover:text-green-600 hover:bg-green-50"
            title={t('toolManagement.refresh.title')}
          >
            {isRefreshing ? t('toolManagement.refresh.button.refreshing') : t('toolManagement.refresh.button.refresh')}
          </Button>
          <Button
            type="text"
            size="small"
            icon={<ApiOutlined />}
            onClick={() => setIsMcpModalOpen(true)}
            disabled={localIsGenerating || isGeneratingAgent}
            className="text-blue-500 hover:text-blue-600 hover:bg-blue-50"
            title={t('toolManagement.mcp.title')}
          >
            {t('toolManagement.mcp.button')}
          </Button>
          {loadingTools && <span className="text-sm text-gray-500">{t('toolPool.loading')}</span>}
        </div>
      </div>
      <div className="flex-1 min-h-0 border-t pt-2 pb-2 overflow-hidden">
        {loadingTools ? (
          <div className="flex items-center justify-center h-full">
            <span className="text-gray-500">{t('toolPool.loadingTools')}</span>
          </div>
        ) : toolGroups.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <span className="text-gray-500">{t('toolPool.noTools')}</span>
          </div>
        ) : (
          <div style={{ height: '100%' }}>
            <Tabs
              tabPosition="left"
              activeKey={activeTabKey}
              onChange={setActiveTabKey}
              items={tabItems}
              className="h-full tool-pool-tabs"
              style={{
                height: '100%'
              }}
              tabBarStyle={{
                minWidth: '80px',
                maxWidth: '100px',
                padding: '4px 0',
                margin: 0
              }}
            />
          </div>
        )}
      </div>

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