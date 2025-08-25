"use client"

import React, { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, MousePointerClick } from 'lucide-react'
import { fetchAllAgents } from '@/services/agentConfigService'
import { useTranslation } from 'react-i18next'
import { getUrlParam } from '@/lib/utils'

interface Agent {
  agent_id: number
  name: string
  display_name: string
  description: string
  is_available: boolean
}

interface AgentSelectorProps {
  selectedAgentId: number | null
  onAgentSelect: (agentId: number | null) => void
  disabled?: boolean
  isInitialMode?: boolean
}

export function AgentSelector({ selectedAgentId, onAgentSelect, disabled = false, isInitialMode = false }: AgentSelectorProps) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0, direction: 'down' })
  const [isAutoSelectInit, setIsAutoSelectInit] = useState(false)
  const { t } = useTranslation('common')
  const buttonRef = useRef<HTMLDivElement>(null)

  // Customizable dropdown width (unit: px)
  // You can modify this value to adjust the width of the selector as needed
  const dropdownWidth = 550

  const selectedAgent = agents.find(agent => agent.agent_id === selectedAgentId)

  /**
   * Handle URL parameter auto-selection logic for Agent
   */
  const handleAutoSelectAgent = () => {
    if (agents.length === 0 || isAutoSelectInit) return

    // Get agent_id parameter from URL
    const agentId = getUrlParam('agent_id', null as number | null, str => str ? Number(str) : null)
    if (agentId === null) return

    // Check if agentId is a valid agent
    const agent = agents.find(a => a.agent_id === agentId)
    if (agent && agent.is_available) {
      handleAgentSelect(agentId)
      setIsAutoSelectInit(true)
    }
  }

  useEffect(() => {
    loadAgents()
  }, [])

  // Execute auto-selection logic when agents are loaded
  useEffect(() => {
    handleAutoSelectAgent()
  }, [agents])

  // Calculate dropdown position
  useEffect(() => {
    if (isOpen && buttonRef.current) {
      const buttonRect = buttonRef.current.getBoundingClientRect()
      const viewportHeight = window.innerHeight
      const dropdownHeight = 320 // Estimated dropdown height (max-h-80), can be adjusted based on agent count
      
      // Check if there's enough space to display below
      const hasSpaceBelow = buttonRect.bottom + dropdownHeight + 10 < viewportHeight
      // Check if there's enough space to display above
      const hasSpaceAbove = buttonRect.top - dropdownHeight - 10 > 0
      
      let direction = 'down'
      let top = buttonRect.bottom + 4
      
      // Decide direction: prioritize suggested direction, but adjust if space is insufficient
      if (isInitialMode) {
        // Initial mode prioritizes downward
        if (!hasSpaceBelow && hasSpaceAbove) {
          direction = 'up'
          top = buttonRect.top - 4
        }
      } else {
        // Non-initial mode prioritizes upward
        direction = 'up'
        top = buttonRect.top - 4
        if (!hasSpaceAbove && hasSpaceBelow) {
          direction = 'down'
          top = buttonRect.bottom + 4
        }
      }
      
      setDropdownPosition({
        top,
        left: buttonRect.left,
        direction
      })
    }
  }, [isOpen, isInitialMode])

  // Listen for window scroll and resize events, close dropdown
  useEffect(() => {
    if (!isOpen) return

    const handleScroll = (e: Event) => {
      // If scrolling occurs inside the dropdown, don't close it
      const target = e.target as Node
      const dropdownElement = document.querySelector('.agent-selector-dropdown')
      if (dropdownElement && (dropdownElement === target || dropdownElement.contains(target))) {
        return
      }
      
      // If it's page scrolling or other container scrolling, close the dropdown
      setIsOpen(false)
    }

    const handleResize = () => {
      setIsOpen(false)
    }

    // Use event capture phase
    window.addEventListener('scroll', handleScroll, true)
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('scroll', handleScroll, true)
      window.removeEventListener('resize', handleResize)
    }
  }, [isOpen])

  const loadAgents = async () => {
    setIsLoading(true)
    try {
      const result = await fetchAllAgents()
      if (result.success) {
        setAgents(result.data)
      }
    } catch (error) {
      console.error('Failed to load Agent list:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleAgentSelect = (agentId: number | null) => {
    // Only available agents can be selected
    if (agentId !== null) {
      const agent = agents.find(a => a.agent_id === agentId)
      if (agent && !agent.is_available) {
        return // Unavailable agents cannot be selected
      }
    }
    
    onAgentSelect(agentId)
    setIsOpen(false)
    
    // If it's an iframe embedded page, send postMessage to the parent page
    if (window.self !== window.top) {
      try {
        const selectedAgent = agents.find(agent => agent.agent_id === agentId)
        const message = {
          type: 'agent_selected',
          agent_id: agentId,
          agent_name: selectedAgent?.name || null,
          timestamp: Date.now(),
          source: 'agent_selector'
        }
        
        // Send postMessage to the parent page
        window.parent.postMessage(message, '*')
      } catch (error) {
        console.error('Failed to send postMessage:', error)
      }
    }
  }

  // Show all agents, including unavailable ones
  const allAgents = agents

  return (
    <div className="relative">
      <div
        ref={buttonRef}
        className={`
          relative h-8 min-w-[150px] max-w-[250px] px-2
          rounded-lg border border-slate-200
          bg-white hover:bg-slate-50
          flex items-center justify-between
          cursor-pointer select-none
          transition-colors duration-150
          ${disabled || isLoading ? 'opacity-50 cursor-not-allowed' : ''}
          ${isOpen ? 'border-blue-400 ring-2 ring-blue-100' : 'hover:border-slate-300'}
        `}
        onClick={() => !disabled && !isLoading && setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-2 truncate">
          {selectedAgent && (
            <MousePointerClick className="w-4 h-4 text-blue-500 flex-shrink-0" />
          )}
          <span className={`truncate text-sm ${selectedAgent ? 'font-medium text-slate-700' : 'text-slate-500'}`}>
            {isLoading 
              ? (
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin" />
                  <span>{t('agentSelector.loading')}</span>
                </div>
              )
              : selectedAgent 
                ? selectedAgent.display_name 
                : t('agentSelector.selectAgent')
            }
          </span>
        </div>
        <ChevronDown 
          className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} 
        />
      </div>

      {/* Portal renders dropdown to body to avoid being blocked by parent container */}
      {isOpen && typeof window !== 'undefined' && createPortal(
        <>
          {/* Overlay */}
          <div
            className="fixed inset-0 z-[9998]"
            onClick={() => setIsOpen(false)}
            onWheel={(e) => {
              // If scrolling occurs inside the dropdown, don't close it
              const target = e.target as Node
              const dropdownElement = document.querySelector('.agent-selector-dropdown')
              if (dropdownElement && (dropdownElement === target || dropdownElement.contains(target))) {
                return
              }
              setIsOpen(false)
            }}
          />
          
          {/* Dropdown */}
          <div 
            className="agent-selector-dropdown fixed bg-white border border-slate-200 rounded-md shadow-lg z-[9999] max-h-80 overflow-y-auto"
            style={{
              top: dropdownPosition.direction === 'up' 
                ? `${dropdownPosition.top}px` 
                : `${dropdownPosition.top}px`,
              left: `${dropdownPosition.left}px`,
              width: `${dropdownWidth}px`,
              transform: dropdownPosition.direction === 'up' ? 'translateY(-100%)' : 'none'
            }}
            onWheel={(e) => {
              // Prevent scroll event bubbling, but allow normal scrolling
              e.stopPropagation()
            }}
          >
            <div className="py-1">
              {allAgents.length === 0 ? (
                <div className="px-3 py-2.5 text-sm text-slate-500 text-center">
                  {isLoading ? (
                    <div className="flex items-center justify-center gap-2">
                      <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin" />
                      <span>{t('agentSelector.loading')}</span>
                    </div>
                  ) : (
                    t('agentSelector.noAvailableAgents')
                  )}
                </div>
              ) : (
                allAgents.map((agent, idx) => (
                  <div
                    key={agent.agent_id}
                    className={`
                      flex items-start gap-3 px-3.5 py-3 text-sm
                      transition-all duration-150 ease-in-out
                      ${agent.is_available 
                        ? `hover:bg-slate-50 cursor-pointer ${
                            selectedAgentId === agent.agent_id 
                              ? 'bg-blue-50/70 text-blue-600 hover:bg-blue-50/70' 
                              : ''
                          }` 
                        : 'cursor-not-allowed bg-slate-50/50'
                      }
                      ${selectedAgentId === agent.agent_id ? 'shadow-[inset_2px_0_0_0] shadow-blue-500' : ''}
                      ${idx !== 0 ? 'border-t border-slate-100' : ''}
                    `}
                    onClick={() => agent.is_available && handleAgentSelect(agent.agent_id)}
                  >
                    {/* Agent Icon */}
                    <div className="flex-shrink-0 mt-0.5">
                      <MousePointerClick 
                        className={`h-4 w-4 ${
                          agent.is_available 
                            ? selectedAgentId === agent.agent_id 
                              ? 'text-blue-500' 
                              : 'text-slate-500'
                            : 'text-slate-300'
                        }`}
                      />
                    </div>
                    
                    {/* Agent Info */}
                    <div className="flex-1 min-w-0">
                      <div className={`font-medium truncate ${
                        agent.is_available 
                          ? selectedAgentId === agent.agent_id 
                            ? 'text-blue-600' 
                            : 'text-slate-700 hover:text-slate-900'
                          : 'text-slate-400'
                      }`}>
                        {agent.display_name && (
                          <span className="text-base leading-none">{agent.display_name}</span>
                        )}
                        <span className={`text-sm leading-none align-baseline ${agent.display_name ? 'ml-2' : 'text-base'}`}>
                          {agent.name}
                        </span>
                      </div>
                      <div className={`text-xs mt-1 leading-relaxed ${
                        agent.is_available 
                          ? selectedAgentId === agent.agent_id 
                            ? 'text-blue-500' 
                            : 'text-slate-500'
                          : 'text-slate-300'
                      }`}>
                        {agent.description}
                        {!agent.is_available && (
                          <span className="block mt-1 text-red-400">
                            {t('agentSelector.agentUnavailable')}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>,
        document.body
      )}
    </div>
  )
} 