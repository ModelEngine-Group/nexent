"use client"

import { useState } from 'react'
import { App, Button, Tooltip } from 'antd'
import { SettingOutlined, UploadOutlined, LinkOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { ScrollArea } from '@/components/ui/scrollArea'
import { Agent } from '@/types/agent'
import AgentCallRelationshipModal from './AgentCallRelationshipModal'


interface SubAgentPoolProps {
  onEditAgent: (agent: Agent) => void;
  onCreateNewAgent: () => void;
  onImportAgent: () => void;
  onExitEditMode?: () => void; // 退出编辑模式的回调
  subAgentList?: Agent[];
  loadingAgents?: boolean;
  isImporting?: boolean;
  isGeneratingAgent?: boolean; // 生成智能体状态
  editingAgent?: Agent | null; // 当前正在编辑的Agent
  isCreatingNewAgent?: boolean; // 是否处于创建模式
}

/**
 * Sub Agent Pool Component
 */
export default function SubAgentPool({ 
  onEditAgent, 
  onCreateNewAgent, 
  onImportAgent,
  onExitEditMode,
  subAgentList = [],
  loadingAgents = false,
  isImporting = false,
  isGeneratingAgent = false,
  editingAgent = null,
  isCreatingNewAgent = false
}: SubAgentPoolProps) {
  const { t } = useTranslation('common');
  const { message } = App.useApp();

  // 查看调用关系相关状态
  const [callRelationshipModalVisible, setCallRelationshipModalVisible] = useState(false);
  const [selectedAgentForRelationship, setSelectedAgentForRelationship] = useState<Agent | null>(null);

  // 打开查看调用关系弹窗
  const handleViewCallRelationship = (agent: Agent) => {
    setSelectedAgentForRelationship(agent);
    setCallRelationshipModalVisible(true);
  };

  // 关闭查看调用关系弹窗
  const handleCloseCallRelationshipModal = () => {
    setCallRelationshipModalVisible(false);
    setSelectedAgentForRelationship(null);
  };


  return (
    <div className="flex flex-col h-full min-h-[300px] lg:min-h-0 overflow-hidden">
      <div className="flex justify-between items-center mb-2">
        <div className="flex items-center">
          <div className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-sm font-medium mr-2">
            1
          </div>
          <h2 className="text-lg font-medium">{t('subAgentPool.management')}</h2>
        </div>
        <div className="flex items-center gap-2">
          {loadingAgents && <span className="text-sm text-gray-500">{t('subAgentPool.loading')}</span>}
        </div>
      </div>
      <ScrollArea className="flex-1 min-h-0 border-t pt-2 pb-2">
        <div className="flex flex-col pr-2">
          {/* 功能操作区块 */}
          <div className="mb-4">
              <div className="flex gap-3">
                <div 
                  className={`flex-1 rounded-md p-2 flex items-center cursor-pointer transition-all duration-200 min-h-[70px] ${
                    isCreatingNewAgent
                      ? 'bg-blue-100 border border-blue-200 shadow-sm' // 创建模式下高亮显示
                      : 'bg-white hover:bg-blue-50 hover:shadow-sm'
                  }`}
                  title={isCreatingNewAgent ? t('subAgentPool.tooltip.exitCreateMode') : t('subAgentPool.tooltip.createNewAgent')}
                  onClick={() => {
                    if (isCreatingNewAgent) {
                      // 如果当前处于创建模式，点击退出创建模式
                      onExitEditMode?.();
                    } else {
                      // 否则进入创建模式
                      onCreateNewAgent();
                    }
                  }}
                >
                  <div className={`flex items-center w-full ${
                    isCreatingNewAgent ? 'text-blue-700' : 'text-blue-600'
                  }`}>
                    <div className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-100 mr-3 flex-shrink-0">
                      <span className="text-sm font-medium">+</span>
                    </div>
                    <div className="flex-1">
                      <div className="font-medium text-sm">
                        {isCreatingNewAgent ? t('subAgentPool.button.exitCreate') : t('subAgentPool.button.create')}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {isCreatingNewAgent ? t('subAgentPool.description.exitCreate') : t('subAgentPool.description.createAgent')}
                      </div>
                    </div>
                  </div>
                </div>

                <div
                  className={`flex-1 rounded-md p-2 flex items-center transition-all duration-200 min-h-[70px] ${
                    isImporting
                      ? 'bg-gray-100 cursor-not-allowed' // 导入中：禁用状态
                      : 'bg-white cursor-pointer hover:bg-green-50 hover:shadow-sm' // 正常状态：可点击
                  }`}
                  onClick={isImporting ? undefined : onImportAgent}
                >
                  <div className={`flex items-center w-full ${
                    isImporting ? 'text-gray-400' : 'text-green-600' // 导入中使用灰色
                  }`}>
                    <div className={`flex items-center justify-center w-8 h-8 rounded-full mr-3 flex-shrink-0 ${
                      isImporting ? 'bg-gray-100' : 'bg-green-100'
                    }`}>
                      <UploadOutlined className="text-sm" />
                    </div>
                    <div className="flex-1">
                      <div className="font-medium text-sm">
                        {isImporting ? t('subAgentPool.button.importing') : t('subAgentPool.button.import')}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {isImporting ? t('subAgentPool.description.importing') : t('subAgentPool.description.importAgent')}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
          </div>

          {/* Agent列表区块 */}
          <div>
            <div className="text-sm font-medium text-gray-600 mb-2 px-1">
              {t('subAgentPool.section.agentList')} ({subAgentList.length})
            </div>
            <div className="space-y-0">
              {subAgentList.map((agent) => {
            const isAvailable = agent.is_available !== false; // 默认为true，只有明确为false时才不可用
            const isCurrentlyEditing = editingAgent && String(editingAgent.id) === String(agent.id); // 确保类型匹配
            
            return (
              <div 
                key={agent.id} 
                className={`py-2 px-2 flex flex-col justify-center transition-colors border-t border-gray-200 ${
                  isCurrentlyEditing
                    ? 'bg-blue-50 border-l-4 border-l-blue-500' // 编辑中的agent高亮显示，添加左侧竖线
                    : !isAvailable
                      ? 'bg-gray-50 opacity-60 cursor-not-allowed'
                      : 'hover:bg-gray-50 cursor-pointer'
                }`}
                title={!isAvailable 
                  ? t('subAgentPool.tooltip.unavailableAgent')
                  : isCurrentlyEditing
                    ? t('subAgentPool.tooltip.exitEditMode')
                  : `${t('subAgentPool.tooltip.editAgent')} ${agent.display_name || agent.name}`}
                onClick={async (e) => {
                  // 阻止事件冒泡
                  e.preventDefault();
                  e.stopPropagation();
                  
                  if (!isGeneratingAgent && isAvailable) {
                    if (isCurrentlyEditing) {
                      // 如果当前正在编辑这个Agent，点击退出编辑模式
                      onExitEditMode?.();
                    } else {
                      // 否则进入编辑模式（或切换到这个Agent）
                    onEditAgent(agent);
                    }
                  } else if (!isAvailable) {
                    message.warning(t('subAgentPool.message.unavailable'));
                  }
                }}
              >
                <div className="flex items-center h-full">
                  <div className="flex-1 overflow-hidden">
                    <div className={`font-medium text-base truncate transition-colors duration-300 ${
                      !isAvailable ? 'text-gray-500' : ''
                    }`} 
                         title={!isAvailable 
                           ? t('subAgentPool.tooltip.unavailableAgent')
                           : `${t('subAgentPool.tooltip.editAgent')} ${agent.display_name || agent.name}`}>
                      <span className="flex items-baseline">
                        {agent.display_name && (
                          <span className="text-base leading-normal">{agent.display_name}</span>
                        )}
                        <span className={`leading-normal ${agent.display_name ? 'ml-2 text-sm' : 'text-base'}`}>
                          {agent.name}
                        </span>
                      </span>
                    </div>
                    <div 
                      className={`text-xs line-clamp-2 transition-colors duration-300 ${
                        !isAvailable ? 'text-gray-400' : 'text-gray-500'
                      }`}
                      title={agent.description}
                    >
                      {agent.description}
                    </div>
                  </div>

                  {/* 操作按钮区域 */}
                  <div className="flex items-center gap-1 ml-2">
                    {/* 查看调用关系按钮 */}
                    <Tooltip title={t('agent.action.viewCallRelationship')}>
                      <Button
                        type="text"
                        size="small"
                        icon={<LinkOutlined />}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          if (isAvailable) {
                            handleViewCallRelationship(agent);
                          }
                        }}
                        disabled={!isAvailable}
                        className="text-blue-500 hover:text-blue-600 hover:bg-blue-50"
                      />
                    </Tooltip>
                  </div>
                </div>
              </div>
              );
            })}
            </div>
          </div>
        </div>
      </ScrollArea>

      {/* Agent调用关系弹窗 */}
      {selectedAgentForRelationship && (
        <AgentCallRelationshipModal
          visible={callRelationshipModalVisible}
          onClose={handleCloseCallRelationshipModal}
          agentId={Number(selectedAgentForRelationship.id)}
          agentName={selectedAgentForRelationship.display_name || selectedAgentForRelationship.name}
        />
      )}
    </div>
  )
} 