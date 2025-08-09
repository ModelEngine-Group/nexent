"use client"

import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import BusinessLogicConfig from './AgentManagementConfig'
import DebugConfig from './DebugConfig'
import GuideSteps from './components/GuideSteps'
import { Row, Col, Drawer, App } from 'antd'
import { fetchTools, fetchAgentList, fetchAgentDetail, exportAgent, deleteAgent, updateAgent } from '@/services/agentConfigService'
import { generatePromptStream } from '@/services/promptService'
import { OpenAIModel } from '@/app/setup/agentSetup/ConstInterface'
import { updateToolList } from '@/services/mcpService'
import { 
  SETUP_PAGE_CONTAINER, 
  THREE_COLUMN_LAYOUT,
  STANDARD_CARD,
  CARD_HEADER 
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
 */
export default function AgentConfig() {
  const { t } = useTranslation('common')
  const { message } = App.useApp()
  const [businessLogic, setBusinessLogic] = useState("")
  const [systemPrompt, setSystemPrompt] = useState("")
  const [selectedAgents, setSelectedAgents] = useState<any[]>([])
  const [selectedTools, setSelectedTools] = useState<any[]>([])
  const [testQuestion, setTestQuestion] = useState("")
  const [testAnswer, setTestAnswer] = useState("")
  const [isDebugDrawerOpen, setIsDebugDrawerOpen] = useState(false)
  const [isCreatingNewAgent, setIsCreatingNewAgent] = useState(false)
  const [mainAgentModel, setMainAgentModel] = useState(OpenAIModel.MainModel)
  const [mainAgentMaxStep, setMainAgentMaxStep] = useState(5)
  const [tools, setTools] = useState<any[]>([])
  const [mainAgentId, setMainAgentId] = useState<string | null>(null)
  const [subAgentList, setSubAgentList] = useState<any[]>([])
  const [loadingAgents, setLoadingAgents] = useState(false)

  const [enabledAgentIds, setEnabledAgentIds] = useState<number[]>([])
  const [currentGuideStep, setCurrentGuideStep] = useState<number | undefined>(undefined)
  const [newAgentName, setNewAgentName] = useState("")
  const [newAgentDescription, setNewAgentDescription] = useState("")
  const [newAgentProvideSummary, setNewAgentProvideSummary] = useState(false)
  const [isNewAgentInfoValid, setIsNewAgentInfoValid] = useState(false)
  const [isEditingAgent, setIsEditingAgent] = useState(false)
  const [editingAgent, setEditingAgent] = useState<any>(null)
  
  // Add state for three segmented content sections
  const [dutyContent, setDutyContent] = useState("")
  const [constraintContent, setConstraintContent] = useState("")
  const [fewShotsContent, setFewShotsContent] = useState("")

  // Add state for agent name and description
  const [agentName, setAgentName] = useState("")
  const [agentDescription, setAgentDescription] = useState("")

  // Add cache for new agent creation to preserve content when switching controllers
  const [newAgentCache, setNewAgentCache] = useState({
    businessLogic: "",
    dutyContent: "",
    constraintContent: "",
    fewShotsContent: "",
    agentName: "",
    agentDescription: ""
  })

  // Add state for business logic and action buttons
  const [isGeneratingAgent, setIsGeneratingAgent] = useState(false)
  const [isSavingAgent, setIsSavingAgent] = useState(false)

  // Only auto scan once flag
  const hasAutoScanned = useRef(false)

  // Handle business logic change
  const handleBusinessLogicChange = (value: string) => {
    setBusinessLogic(value)
    // Cache the content when creating new agent
    if (isCreatingNewAgent) {
      setNewAgentCache(prev => ({ ...prev, businessLogic: value }))
    }
  }

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

  // Handle save agent
  const handleSaveAgent = async () => {
    if (!canSaveAgent) {
      message.warning(getButtonTitle())
      return
    }

    const currentAgentId = getCurrentAgentId()
    if (!currentAgentId) {
      message.error(t('businessLogic.config.error.noAgentId'))
      return
    }

    setIsSavingAgent(true)
    try {
      // Call the actual save API
      const result = await updateAgent(
        Number(currentAgentId),
        agentName,
        agentDescription,
        mainAgentModel,
        mainAgentMaxStep,
        false, // provide_run_summary
        true, // enabled - enable when saving to agent pool
        businessLogic,
        dutyContent,
        constraintContent,
        fewShotsContent
      )

      if (result.success) {
        const actionText = isCreatingNewAgent ? t('agent.action.create') : t('agent.action.modify')
        message.success(t('businessLogic.config.message.agentCreated', { name: agentName, action: actionText }))

        // Reset state
        setIsCreatingNewAgent(false)
        setIsEditingAgent(false)
        setEditingAgent(null)
        setBusinessLogic('')
        setDutyContent('')
        setConstraintContent('')
        setFewShotsContent('')
        setAgentName('')
        setAgentDescription('')
        setSelectedTools([])

        // Clear new agent cache
        clearNewAgentCache()

        // Notify parent component of state change
        handleEditingStateChange(false, null)

        // Refresh agent list
        fetchAgents()
      } else {
        message.error(result.message || t('businessLogic.config.error.saveFailed'))
      }
    } catch (error) {
      console.error('Save agent error:', error)
      message.error(t('businessLogic.config.error.saveFailed'))
    } finally {
      setIsSavingAgent(false)
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
        // Refresh agent list
        fetchAgents()
      } else {
        message.error(result.message || t('businessLogic.config.message.agentDeleteFailed'))
      }
    } catch (error) {
      console.error(t('debug.console.deleteAgentFailed'), error)
      message.error(t('businessLogic.config.message.agentDeleteFailed'))
    }
  }

  // Get button title
  const getButtonTitle = () => {
    if (!businessLogic || businessLogic.trim() === '') {
      return t('businessLogic.config.message.businessDescriptionRequired')
    }
    if (!(dutyContent?.trim()) && !(constraintContent?.trim()) && !(fewShotsContent?.trim())) {
      return t('businessLogic.config.message.generatePromptFirst')
    }
    if (!agentName || agentName.trim() === '') {
      return t('businessLogic.config.message.completeAgentInfo')
    }
    return ""
  }

  // Check if can save agent
  const canSaveAgent = !!(businessLogic?.trim() && agentName?.trim() && (dutyContent?.trim() || constraintContent?.trim() || fewShotsContent?.trim()))

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
    } else {
      // When not creating new agent, reset all states to initial values
      setBusinessLogic('');
      setDutyContent('');
      setConstraintContent('');
      setFewShotsContent('');
      // Only clear agent name/description if not editing existing agent
      if (!isEditingAgent) {
        setAgentName('');
        setAgentDescription('');
      }
    }
    
    // Always reset these states regardless of creation mode
    setSystemPrompt('');
    setSelectedAgents([]);
    setSelectedTools([]);
    setTestQuestion('');
    setTestAnswer('');
    setCurrentGuideStep(undefined);
    // Reset agent info states
    setNewAgentName('');
    setNewAgentDescription('');
    setNewAgentProvideSummary(true);
    setIsNewAgentInfoValid(false);
    
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
      console.log('Setting agent name and description:', agent.name, agent.description);
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
          agentDescription
        })
        // Clear new creation related content
        setIsCreatingNewAgent(false)
        setBusinessLogic('')
        setDutyContent('')
        setConstraintContent('')
        setFewShotsContent('')
      }
    } else if (!isEditing) {
      // When stopping editing, clear name description box
      setAgentName('')
      setAgentDescription('')
    }
  }

  const getCurrentAgentId = () => {
    if (isEditingAgent && editingAgent) {
      return parseInt(editingAgent.id)
    }
    return mainAgentId ? parseInt(mainAgentId) : undefined
  }

  // Handle caching and restoring content for new agent creation
  const cacheNewAgentContent = () => {
    if (isCreatingNewAgent) {
      setNewAgentCache({
        businessLogic,
        dutyContent,
        constraintContent,
        fewShotsContent,
        agentName,
        agentDescription
      })
    }
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
    }
  }

  const clearNewAgentCache = () => {
    setNewAgentCache({
      businessLogic: "",
      dutyContent: "",
      constraintContent: "",
      fewShotsContent: "",
      agentName: "",
      agentDescription: ""
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

  // Handle model change with proper type conversion
  const handleModelChange = (value: string) => {
    setMainAgentModel(value as OpenAIModel)
  }

  // Handle max step change with proper type conversion
  const handleMaxStepChange = (value: number | null) => {
    if (value !== null) {
      setMainAgentMaxStep(value)
    }
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
    <div className="w-full h-full mx-auto" style={{ 
      maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
      padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`
    }}>
      <div className="w-full h-full">
        <Row gutter={THREE_COLUMN_LAYOUT.GUTTER} className="h-full">
          {/* Left Timeline Guide */}
          <Col xs={24} md={24} lg={4} xl={4} className="h-full">
            <div className="bg-white border border-gray-200 rounded-md flex flex-col overflow-hidden h-[300px] lg:h-[82vh]" style={{
              padding: STANDARD_CARD.PADDING,
              overflowY: "auto",
              overflowX: "hidden"
            }}>
                <GuideSteps
                  isCreatingNewAgent={isCreatingNewAgent}
                  systemPrompt={systemPrompt}
                  businessLogic={businessLogic}
                  selectedTools={selectedTools}
                  selectedAgents={selectedAgents}
                  mainAgentId={mainAgentId}
                  currentStep={currentGuideStep}
                  agentName={newAgentName}
                  agentDescription={newAgentDescription}
                  agentProvideSummary={newAgentProvideSummary}
                  isEditingAgent={isEditingAgent}
                  dutyContent={dutyContent}
                  constraintContent={constraintContent}
                  fewShotsContent={fewShotsContent}
                  enabledAgentIds={enabledAgentIds}
                />
            </div>
          </Col>

          {/* Middle and Right Panel Container */}
          <Col xs={24} md={24} lg={20} xl={20}>
            <div className="bg-white border border-gray-200 rounded-md flex flex-col overflow-hidden h-[calc(100vh-200px)] lg:h-[82vh]" style={{
              overflowY: "auto",
              overflowX: "hidden"
            }}>
                {/* Middle Panel - Business Logic Configuration */}
                <div className="flex-1 min-h-0" style={{
                  padding: STANDARD_CARD.PADDING,
                  overflowY: "auto",
                  overflowX: "hidden"
                }}>
                  <BusinessLogicConfig 
                    businessLogic={businessLogic}
                    setBusinessLogic={(value) => {
                      setBusinessLogic(value);
                      if (isCreatingNewAgent) {
                        setNewAgentCache(prev => ({ ...prev, businessLogic: value }));
                      }
                    }}
                    selectedAgents={selectedAgents}
                    setSelectedAgents={setSelectedAgents}
                    selectedTools={selectedTools}
                    setSelectedTools={setSelectedTools}
                    systemPrompt={systemPrompt}
                    setSystemPrompt={setSystemPrompt}
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
                    newAgentName={newAgentName}
                    newAgentDescription={newAgentDescription}
                    newAgentProvideSummary={newAgentProvideSummary}
                    setNewAgentName={setNewAgentName}
                    setNewAgentDescription={setNewAgentDescription}
                    setNewAgentProvideSummary={setNewAgentProvideSummary}
                    isNewAgentInfoValid={isNewAgentInfoValid}
                    setIsNewAgentInfoValid={setIsNewAgentInfoValid}
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
                    isGeneratingAgent={isGeneratingAgent}
                  // SystemPromptDisplay related props
                    onDebug={() => {
                      setIsDebugDrawerOpen(true);
                      setCurrentGuideStep(isCreatingNewAgent ? 5 : 5);
                    }}
                  getCurrentAgentId={getCurrentAgentId}
                    onModelChange={handleModelChange}
                    onMaxStepChange={handleMaxStepChange}
                    onBusinessLogicChange={handleBusinessLogicChange}
                    onGenerateAgent={handleGenerateAgent}
                    onSaveAgent={handleSaveAgent}
                    isSavingAgent={isSavingAgent}
                    canSaveAgent={canSaveAgent}
                    getButtonTitle={getButtonTitle}
                    onExportAgent={handleExportAgent}
                    onDeleteAgent={handleDeleteAgent}
                    editingAgent={editingAgent}
                    onExitCreation={handleExitCreation}
                  />
              </div>
            </div>
          </Col>
        </Row>
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
            testQuestion={testQuestion}
            setTestQuestion={setTestQuestion}
            testAnswer={testAnswer}
            setTestAnswer={setTestAnswer}
            agentId={getCurrentAgentId()}
          />
        </div>
      </Drawer>
    </div>
  )
} 