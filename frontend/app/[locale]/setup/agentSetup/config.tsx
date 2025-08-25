"use client"

import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import BusinessLogicConfig from './components/AgentManagementConfig'
import DebugConfig from './components/DebugConfig'

import { Drawer, App } from 'antd'
import { fetchTools, fetchAgentList, exportAgent, deleteAgent } from '@/services/agentConfigService'
import { generatePromptStream } from '@/services/promptService'
import { OpenAIModel } from '@/types/agent'
import { updateToolList } from '@/services/mcpService'
import { 
  SETUP_PAGE_CONTAINER, 
  STANDARD_CARD,
} from '@/lib/layoutConstants'
import '../../i18n'

// Layout Height Constant Configuration
const LAYOUT_CONFIG = {
  CARD_HEADER_PADDING: "10px 24px",
  CARD_BODY_PADDING: "12px 20px",
  DRAWER_WIDTH: "40%",
}

/**
 * Agent configuration main component
 * Provides a full-width interface for agent business logic configuration
 * Follows SETUP_PAGE_CONTAINER layout standards for consistent height and spacing
 */
export default function AgentConfig() {
  const { t } = useTranslation('common')
  const { message } = App.useApp()
  const [businessLogic, setBusinessLogic] = useState("")
  const [selectedTools, setSelectedTools] = useState<any[]>([])
  const [isDebugDrawerOpen, setIsDebugDrawerOpen] = useState(false)
  const [isCreatingNewAgent, setIsCreatingNewAgent] = useState(false)
  const [mainAgentModel, setMainAgentModel] = useState(OpenAIModel.MainModel)
  const [mainAgentMaxStep, setMainAgentMaxStep] = useState(5)
  const [tools, setTools] = useState<any[]>([])
  const [mainAgentId, setMainAgentId] = useState<string | null>(null)
  const [subAgentList, setSubAgentList] = useState<any[]>([])
  const [loadingAgents, setLoadingAgents] = useState(false)

  const [enabledAgentIds, setEnabledAgentIds] = useState<number[]>([])

  const [isEditingAgent, setIsEditingAgent] = useState(false)
  const [editingAgent, setEditingAgent] = useState<any>(null)
  
  // Add state for three segmented content sections
  const [dutyContent, setDutyContent] = useState("")
  const [constraintContent, setConstraintContent] = useState("")
  const [fewShotsContent, setFewShotsContent] = useState("")

  // Add state for agent name and description
  const [agentName, setAgentName] = useState("")
  const [agentDescription, setAgentDescription] = useState("")
  const [agentDisplayName, setAgentDisplayName] = useState("")

  // Add cache for new agent creation to preserve content when switching controllers
  const [newAgentCache, setNewAgentCache] = useState({
    businessLogic: "",
    dutyContent: "",
    constraintContent: "",
    fewShotsContent: "",
    agentName: "",
    agentDescription: "",
    agentDisplayName: ""
  })

  // Add state for business logic and action buttons
  const [isGeneratingAgent, setIsGeneratingAgent] = useState(false)

  // Only auto scan once flag
  const hasAutoScanned = useRef(false)

  // Handle generate agent
  const handleGenerateAgent = async () => {
    if (!businessLogic || businessLogic.trim() === '') {
      message.warning(t('businessLogic.config.error.businessDescriptionRequired'))
      return
    }

    const currentAgentId = getCurrentAgentId()
    if (!currentAgentId) {
      message.error(t('businessLogic.config.error.noAgentId'))
      return
    }

    setIsGeneratingAgent(true)
    try {
      const currentAgentName = agentName
      const currentAgentDisplayName = agentDisplayName

      // Call backend API to generate agent prompt
      await generatePromptStream(
        {
          agent_id: Number(currentAgentId),
          task_description: businessLogic
        },
        (data) => {
          // Process streaming response data
          switch (data.type) {
            case 'duty':
              setDutyContent(data.content)
              break
            case 'constraint':
              setConstraintContent(data.content)
              break
            case 'few_shots':
              setFewShotsContent(data.content)
              break
            case 'agent_var_name':
              // Only update if current agent name is empty
              if (!currentAgentName || currentAgentName.trim() === '') {
                setAgentName(data.content)
              }
              break
            case 'agent_description':
              setAgentDescription(data.content)
              break
            case 'agent_display_name':
              // Only update if current agent display name is empty
              if (!currentAgentDisplayName || currentAgentDisplayName.trim() === '') {
                setAgentDisplayName(data.content)
              }
              break
          }
        },
        (error) => {
          console.error('Generate prompt stream error:', error)
          message.error(t('businessLogic.config.message.generateError'))
        },
        () => {
          message.success(t('businessLogic.config.message.generateSuccess'))
        }
      )
    } catch (error) {
      console.error('Generate agent error:', error)
      message.error(t('businessLogic.config.message.generateError'))
    } finally {
      setIsGeneratingAgent(false)
    }
  }

  // Handle export agent
  const handleExportAgent = async () => {
    if (!editingAgent) {
      message.warning(t('agent.error.noAgentSelected'))
      return
    }

    try {
      const result = await exportAgent(Number(editingAgent.id))
      if (result.success) {
        // Handle backend returned string or object
        let exportData = result.data;
        if (typeof exportData === 'string') {
          try {
            exportData = JSON.parse(exportData);
          } catch (e) {
            // If parsing fails, it means it's already a string, export directly
          }
        }
        const blob = new Blob([JSON.stringify(exportData, null, 2)], {
          type: 'application/json'
        });

        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${editingAgent.name}_config.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        message.success(t('businessLogic.config.message.agentExportSuccess'));
      } else {
        message.error(result.message || t('businessLogic.config.error.agentExportFailed'))
      }
    } catch (error) {
      console.error(t('debug.console.exportAgentFailed'), error)
      message.error(t('businessLogic.config.error.agentExportFailed'))
    }
  }

  // Handle delete agent
  const handleDeleteAgent = async () => {
    if (!editingAgent) {
      message.warning(t('agent.error.noAgentSelected'))
      return
    }

    try {
      const result = await deleteAgent(Number(editingAgent.id))
      if (result.success) {
        message.success(t('businessLogic.config.message.agentDeleteSuccess', { name: editingAgent.name }))
        // Reset editing state
        setIsEditingAgent(false)
        setEditingAgent(null)
        setBusinessLogic("")
        setDutyContent("")
        setConstraintContent("")
        setFewShotsContent("")
        setAgentName("")
        setAgentDescription("")
        // Notify AgentManagementConfig to refresh agent list
        window.dispatchEvent(new CustomEvent('refreshAgentList'));
      } else {
        message.error(result.message || t('businessLogic.config.message.agentDeleteFailed'))
      }
    } catch (error) {
      console.error(t('debug.console.deleteAgentFailed'), error)
      message.error(t('businessLogic.config.message.agentDeleteFailed'))
    }
  }

  // Load tools when page is loaded
  useEffect(() => {
    const loadTools = async () => {
      try {
        const result = await fetchTools()
        if (result.success) {
          setTools(result.data)
          // If the tool list is empty and auto scan hasn't been triggered, trigger scan once
          if (result.data.length === 0 && !hasAutoScanned.current) {
            hasAutoScanned.current = true
            // Mark as auto scanned
            const scanResult = await updateToolList()
            if (!scanResult.success) {
              message.error(t('toolManagement.message.refreshFailed'))
              return
            }
            message.success(t('toolManagement.message.refreshSuccess'))
            // After scan, fetch the tool list again
            const reFetch = await fetchTools()
            if (reFetch.success) {
              setTools(reFetch.data)
            }
          }
        } else {
          message.error(result.message)
        }
      } catch (error) {
        console.error(t('agent.error.loadTools'), error)
        message.error(t('agent.error.loadToolsRetry'))
      }
    }
    
    loadTools()
  }, [t])

  // get agent list
  const fetchAgents = async () => {
    setLoadingAgents(true);
    try {
      const result = await fetchAgentList();
      if (result.success) {
        // fetchAgentList now returns AgentBasicInfo[], so we just set the subAgentList
        setSubAgentList(result.data);
        // Clear other states since we don't have detailed info yet
        setMainAgentId(null);
        // No longer manually clear enabledAgentIds, completely rely on backend returned sub_agent_id_list
        setMainAgentModel(OpenAIModel.MainModel);
        setMainAgentMaxStep(5);
        setBusinessLogic('');
        setDutyContent('');
        setConstraintContent('');
        setFewShotsContent('');
        // Clear agent name and description only when not in editing mode
        if (!isEditingAgent) {
          setAgentName('');
          setAgentDescription('');
          setAgentDisplayName('');
        }
      } else {
        message.error(result.message || t('agent.error.fetchAgentList'));
      }
    } catch (error) {
      console.error(t('agent.error.fetchAgentList'), error);
      message.error(t('agent.error.fetchAgentListRetry'));
    } finally {
      setLoadingAgents(false);
    }
  };
  

  // get agent list when component is loaded
  useEffect(() => {
    fetchAgents();
  }, []);

  // add event listener to respond to the data request from the main page
  useEffect(() => {
    const handleGetAgentConfigData = () => {
      // Check if there is system prompt content
      let hasSystemPrompt = false;
      
      // If any of the segmented prompts has content, consider it as having system prompt
      if (dutyContent && dutyContent.trim() !== '') {
        hasSystemPrompt = true;
      } else if (constraintContent && constraintContent.trim() !== '') {
        hasSystemPrompt = true;
      } else if (fewShotsContent && fewShotsContent.trim() !== '') {
        hasSystemPrompt = true;
      }
      
      // send the current configuration data to the main page
      window.dispatchEvent(new CustomEvent('agentConfigDataResponse', {
        detail: {
          businessLogic: businessLogic,
          systemPrompt: hasSystemPrompt ? 'has_content' : ''
        }
      }));
    };

    window.addEventListener('getAgentConfigData', handleGetAgentConfigData);

    return () => {
      window.removeEventListener('getAgentConfigData', handleGetAgentConfigData);
    };
  }, [businessLogic, dutyContent, constraintContent, fewShotsContent]);



  // Remove frontend caching logic, completely rely on backend returned sub_agent_id_list
  // No longer need to set selectedAgents based on enabledAgentIds

  // Monitor the status change of creating a new agent, and reset the relevant status
  useEffect(() => {
    if (isCreatingNewAgent) {
      // When starting to create new agent, try to restore cached content
      restoreNewAgentContent();
    } 
    
    // Always reset these states regardless of creation mode
    setSelectedTools([]);
    
    // Reset the main agent configuration related status
    if (!isCreatingNewAgent) {
      setMainAgentModel(OpenAIModel.MainModel);
      setMainAgentMaxStep(5);
    }
  }, [isCreatingNewAgent]);

  const handleEditingStateChange = (isEditing: boolean, agent: any) => {
    setIsEditingAgent(isEditing)
    setEditingAgent(agent)
    
    // When starting to edit agent, set agent name and description to the right-side name description box
    if (isEditing && agent) {
      setAgentName(agent.name || '')
      setAgentDescription(agent.description || '')
      // If creating new agent, cache current content first, then clear
      if (isCreatingNewAgent) {
        setNewAgentCache({
          businessLogic,
          dutyContent,
          constraintContent,
          fewShotsContent,
          agentName,
          agentDescription,
          agentDisplayName
        })
        // Clear new creation related content
        setIsCreatingNewAgent(false)
        setDutyContent('')
        setConstraintContent('')
        setFewShotsContent('')
      }
    } else if (!isEditing) {
      // When stopping editing, clear name description box
      setAgentName('')
      setAgentDescription('')
      setAgentDisplayName('')
    }
  }

  const getCurrentAgentId = () => {
    if (isEditingAgent && editingAgent) {
      return parseInt(editingAgent.id)
    }
    return mainAgentId ? parseInt(mainAgentId) : undefined
  }

  const restoreNewAgentContent = () => {
    if (newAgentCache.businessLogic || newAgentCache.dutyContent || newAgentCache.constraintContent || 
        newAgentCache.fewShotsContent || newAgentCache.agentName || newAgentCache.agentDescription) {
      setBusinessLogic(newAgentCache.businessLogic)
      setDutyContent(newAgentCache.dutyContent)
      setConstraintContent(newAgentCache.constraintContent)
      setFewShotsContent(newAgentCache.fewShotsContent)
      setAgentName(newAgentCache.agentName)
      setAgentDescription(newAgentCache.agentDescription)
      setAgentDisplayName(newAgentCache.agentDisplayName)
    }
  }

  const clearNewAgentCache = () => {
    setNewAgentCache({
      businessLogic: "",
      dutyContent: "",
      constraintContent: "",
      fewShotsContent: "",
      agentName: "",
      agentDescription: "",
      agentDisplayName: ""
    })
  }

  // Handle exit creation mode - should clear cache
  const handleExitCreation = () => {
    setIsCreatingNewAgent(false)
    clearNewAgentCache()
    setBusinessLogic('')
    setDutyContent('')
    setConstraintContent('')
    setFewShotsContent('')
    setAgentName('')
    setAgentDescription('')
  }

  // Refresh tool list
  const handleToolsRefresh = async () => {
    try {
      const result = await fetchTools()
      if (result.success) {
        setTools(result.data)
        message.success(t('agentConfig.tools.refreshSuccess'))
      } else {
        message.error(t('agentConfig.tools.refreshFailed'))
      }
    } catch (error) {
      console.error(t('agentConfig.debug.refreshToolsFailed'), error)
      message.error(t('agentConfig.tools.refreshFailed'))
    }
  }

  return (
    <App>
      <div className="w-full mx-auto" style={{ 
        maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
        height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT
      }}>
        <div className={STANDARD_CARD.BASE_CLASSES} style={{
          height: "100%",
          ...STANDARD_CARD.CONTENT_SCROLL
        }}>
          <div style={{ padding: STANDARD_CARD.PADDING, height: "100%" }}>
            <BusinessLogicConfig 
                      businessLogic={businessLogic}
                      setBusinessLogic={(value) => {
                        setBusinessLogic(value);
                        if (isCreatingNewAgent) {
                          setNewAgentCache(prev => ({ ...prev, businessLogic: value }));
                        }
                      }}
                      selectedTools={selectedTools}
                      setSelectedTools={setSelectedTools}
                      isCreatingNewAgent={isCreatingNewAgent}
                      setIsCreatingNewAgent={setIsCreatingNewAgent}
                      mainAgentModel={mainAgentModel}
                      setMainAgentModel={setMainAgentModel}
                      mainAgentMaxStep={mainAgentMaxStep}
                      setMainAgentMaxStep={setMainAgentMaxStep}
                      tools={tools}
                      subAgentList={subAgentList}
                      loadingAgents={loadingAgents}
                      mainAgentId={mainAgentId}
                      setMainAgentId={setMainAgentId}
                      setSubAgentList={setSubAgentList}
                      enabledAgentIds={enabledAgentIds}
                      setEnabledAgentIds={setEnabledAgentIds}
                      onEditingStateChange={handleEditingStateChange}
                      onToolsRefresh={handleToolsRefresh}
                      dutyContent={dutyContent}
                      setDutyContent={(value) => {
                        setDutyContent(value);
                        if (isCreatingNewAgent) {
                          setNewAgentCache(prev => ({ ...prev, dutyContent: value }));
                        }
                      }}
                      constraintContent={constraintContent}
                      setConstraintContent={(value) => {
                        setConstraintContent(value);
                        if (isCreatingNewAgent) {
                          setNewAgentCache(prev => ({ ...prev, constraintContent: value }));
                        }
                      }}
                      fewShotsContent={fewShotsContent}
                      setFewShotsContent={(value) => {
                        setFewShotsContent(value);
                        if (isCreatingNewAgent) {
                          setNewAgentCache(prev => ({ ...prev, fewShotsContent: value }));
                        }
                      }}
                      agentName={agentName}
                      setAgentName={(value) => {
                        setAgentName(value);
                        if (isCreatingNewAgent) {
                          setNewAgentCache(prev => ({ ...prev, agentName: value }));
                        }
                      }}
                      agentDescription={agentDescription}
                      setAgentDescription={(value) => {
                        setAgentDescription(value);
                        if (isCreatingNewAgent) {
                          setNewAgentCache(prev => ({ ...prev, agentDescription: value }));
                        }
                      }}
                      agentDisplayName={agentDisplayName}
                      setAgentDisplayName={(value) => {
                        setAgentDisplayName(value);
                        if (isCreatingNewAgent) {
                          setNewAgentCache(prev => ({ ...prev, agentDisplayName: value }));
                        }
                      }}
                      isGeneratingAgent={isGeneratingAgent}
                    // SystemPromptDisplay related props
                      onDebug={() => {
                        setIsDebugDrawerOpen(true);
                      }}
                    getCurrentAgentId={getCurrentAgentId}
                      onGenerateAgent={handleGenerateAgent}
                      onExportAgent={handleExportAgent}
                      onDeleteAgent={handleDeleteAgent}
                      editingAgent={editingAgent}
                      onExitCreation={handleExitCreation}
                    />
          </div>
        </div>
      </div>

      {/* Commissioning drawer */}
      <Drawer
        title={t('agent.debug.title')}
        placement="right"
        onClose={() => setIsDebugDrawerOpen(false)}
        open={isDebugDrawerOpen}
        width={LAYOUT_CONFIG.DRAWER_WIDTH}
        styles={{
          body: {
            padding: 0,
            height: '100%',
            overflow: 'hidden'
          }
        }}
      >
        <div className="h-full">
          <DebugConfig 
            agentId={getCurrentAgentId()}
          />
        </div>
      </Drawer>
    </App>
  )
} 