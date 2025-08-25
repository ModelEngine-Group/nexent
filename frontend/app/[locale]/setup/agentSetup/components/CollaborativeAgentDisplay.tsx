"use client"

import { useState, useEffect } from 'react'
import { Tag, App } from 'antd'
import { PlusOutlined, CloseOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { Agent } from '@/types/agent'
import { addRelatedAgent, deleteRelatedAgent } from '@/services/agentConfigService'

interface CollaborativeAgentDisplayProps {
  availableAgents: Agent[]
  selectedAgentIds: number[]
  parentAgentId?: number
  onAgentIdsChange: (newAgentIds: number[]) => void
  isEditingMode: boolean
  isGeneratingAgent: boolean
  className?: string
  style?: React.CSSProperties
}

export default function CollaborativeAgentDisplay({
  availableAgents,
  selectedAgentIds,
  parentAgentId,
  onAgentIdsChange,
  isEditingMode,
  isGeneratingAgent,
  className,
  style
}: CollaborativeAgentDisplayProps) {
  const { t } = useTranslation('common')
  const { message } = App.useApp()
  const [isDropdownVisible, setIsDropdownVisible] = useState(false)
  const [selectedAgentToAdd, setSelectedAgentToAdd] = useState<string | null>(null)
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0 })

  // Click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Element
      // Check if the clicked element is inside the dropdown
      if (isDropdownVisible && !target.closest('.collaborative-dropdown')) {
        setIsDropdownVisible(false)
      }
    }

    if (isDropdownVisible) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isDropdownVisible])

  // Get detailed information of selected agents
  const selectedAgents = availableAgents.filter(agent => 
    selectedAgentIds.includes(Number(agent.id))
  )

  // Get selectable agents (excluding already selected and self)
  const availableAgentsToSelect = availableAgents.filter(agent => 
    !selectedAgentIds.includes(Number(agent.id)) && 
    agent.is_available !== false &&
    Number(agent.id) !== parentAgentId
  )



  // Handle adding collaborative agent
  const handleAddCollaborativeAgent = async (agentIdToAdd?: string) => {
    const targetAgentId = agentIdToAdd || selectedAgentToAdd
    
    if (!targetAgentId) {
      message.warning(t('collaborativeAgent.message.selectAgentFirst'))
      return
    }
    
    if (!parentAgentId) {
      message.warning(t('collaborativeAgent.message.noParentAgent'))
      return
    }

    try {
      const result = await addRelatedAgent(parentAgentId, Number(targetAgentId))
      if (result.success) {
        // Update local state after successful addition
        const newSelectedAgentIds = [...selectedAgentIds, Number(targetAgentId)]
        onAgentIdsChange(newSelectedAgentIds)
        message.success(t('collaborativeAgent.message.addSuccess'))
        setIsDropdownVisible(false)
        setSelectedAgentToAdd(null)
      } else {
        if (result.status === 500) {
          message.error(t('collaborativeAgent.message.circularDependency'))
        } else {
          message.error(result.message || t('collaborativeAgent.message.addFailed'))
        }
      }
    } catch (error) {
      console.error('Failed to add collaborative agent:', error)
      message.error(t('collaborativeAgent.message.addFailed'))
    }
  }

  // Handle removing collaborative agent
  const handleRemoveCollaborativeAgent = async (agentId: number) => {
    if (!parentAgentId) {
      message.error(t('collaborativeAgent.message.noParentAgent'))
      return
    }

    try {
      const result = await deleteRelatedAgent(parentAgentId, agentId)
      if (result.success) {
        // Update local state after successful deletion
        const newSelectedAgentIds = selectedAgentIds.filter(id => id !== agentId)
        onAgentIdsChange(newSelectedAgentIds)
        message.success(t('collaborativeAgent.message.removeSuccess'))
      } else {
        message.error(result.message || t('collaborativeAgent.message.removeFailed'))
      }
    } catch (error) {
      console.error('Failed to delete collaborative agent:', error)
      message.error(t('collaborativeAgent.message.removeFailed'))
    }
  }

  // Handle add button click
  const handleAddButtonClick = (event: React.MouseEvent) => {
    if (!isEditingMode) {
      message.warning(t('collaborativeAgent.message.notInEditMode'))
      return
    }
    if (isGeneratingAgent) {
      message.warning(t('collaborativeAgent.message.generatingInProgress'))
      return
    }
    
    if (!isDropdownVisible) {
      // Calculate dropdown position
      const rect = event.currentTarget.getBoundingClientRect()
      setDropdownPosition({
        top: rect.bottom + window.scrollY + 4,
        left: rect.left + window.scrollX
      })
    }
    
    setIsDropdownVisible(!isDropdownVisible)
  }

  // Render dropdown component
  const renderDropdown = () => {
    if (!isDropdownVisible) return null
    
    return (
      <div 
        className="fixed z-50 bg-white border border-gray-200 rounded-md shadow-lg min-w-[200px] max-h-[300px] overflow-y-auto collaborative-dropdown"
        style={{
          top: `${dropdownPosition.top}px`,
          left: `${dropdownPosition.left}px`
        }}
      >
        {availableAgentsToSelect.length === 0 ? (
          <div className="text-sm text-gray-500 text-center py-2 px-3">
            {t('collaborativeAgent.select.noOptions')}
          </div>
        ) : (
          <div className="py-1">
            {availableAgentsToSelect.map((agent) => (
              <div
                key={agent.id}
                className="px-3 py-2 hover:bg-blue-50 cursor-pointer text-sm"
                onClick={() => {
                  handleAddCollaborativeAgent(agent.id)
                }}
              >
                <span>{agent.display_name || agent.name}</span>
                {agent.display_name && (
                  <span className="ml-2 text-xs text-gray-400">
                    ({agent.name})
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={`flex flex-col w-full max-w-[calc(100%-1rem)] ${className}`} style={style}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-md font-medium text-gray-700">{t('collaborativeAgent.title')}</h4>
      </div>
      
      {/* Tag display area - fixed height to avoid layout jumping */}
      <div className="bg-gray-50 rounded-md border-2 border-gray-200 p-4 overflow-y-auto relative shadow-sm h-[100px] lg:h-[120px] w-[98%]">
        <div className={`flex flex-wrap gap-2 min-h-[32px] transition-opacity duration-300 ${
          isEditingMode ? 'opacity-100' : 'opacity-0'
        }`}>
          {/* Add button always exists, just invisible in non-editing mode */}
          <div className="relative">
            <button
              type="button"
              onClick={handleAddButtonClick}
              disabled={isGeneratingAgent || !isEditingMode}
              className={`flex items-center justify-center w-8 h-8 border-2 border-dashed transition-colors duration-200 ${
                isGeneratingAgent || !isEditingMode
                  ? 'border-gray-300 text-gray-400 cursor-not-allowed'
                  : 'border-blue-400 text-blue-500 hover:border-blue-500 hover:text-blue-600 hover:bg-blue-50'
              }`}
              title={isEditingMode ? t('collaborativeAgent.button.add') : ''}
            >
              <PlusOutlined className="text-sm" />
            </button>
            {/* Dropdown only renders in editing mode */}
            {isEditingMode && renderDropdown()}
          </div>
          {selectedAgents.map((agent) => (
            <Tag
              key={agent.id}
              color="blue"
              className="px-3 py-1 text-sm"
              closable={isEditingMode && !isGeneratingAgent}
              onClose={() => handleRemoveCollaborativeAgent(Number(agent.id))}
              closeIcon={<CloseOutlined className="text-xs" />}
            >
              <span className="text-base leading-none">
                {agent.display_name || agent.name}
              </span>
            </Tag>
          ))}
        </div>
      </div>
    </div>
  )
} 