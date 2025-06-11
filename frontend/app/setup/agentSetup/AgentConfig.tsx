"use client"

import { useState, useEffect } from 'react'
import BusinessLogicConfig from './AgentManagementConfig'
import SystemPromptDisplay from './components/SystemPromptDisplay'
import DebugConfig from './DebugConfig'
import GuideSteps from './components/GuideSteps'
import { Row, Col, Drawer, message } from 'antd'
import { fetchTools, fetchAgentList, fetchMcpList } from '@/services/agentConfigService'
import { OpenAIModel } from '@/app/setup/agentSetup/ConstInterface'

// Layout Height Constant Configuration
const LAYOUT_CONFIG = {
  MAIN_CONTENT_HEIGHT: "calc(75vh - 45px)",
  CARD_HEADER_PADDING: "10px 24px",
  CARD_BODY_PADDING: "12px 20px",
  CARD_GAP: 12,
  DRAWER_WIDTH: "40%",
}

/**
 * Agent configuration main component
 */
export default function AgentConfig() {
  const [businessLogic, setBusinessLogic] = useState("")
  const [systemPrompt, setSystemPrompt] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [selectedAgents, setSelectedAgents] = useState<any[]>([])
  const [selectedTools, setSelectedTools] = useState<any[]>([])
  const [testQuestion, setTestQuestion] = useState("")
  const [testAnswer, setTestAnswer] = useState("")
  const [isDebugDrawerOpen, setIsDebugDrawerOpen] = useState(false)
  const [isCreatingNewAgent, setIsCreatingNewAgent] = useState(false)
  const [mainAgentModel, setMainAgentModel] = useState(OpenAIModel.MainModel)
  const [mainAgentMaxStep, setMainAgentMaxStep] = useState(5)
  const [mainAgentPrompt, setMainAgentPrompt] = useState("")
  const [tools, setTools] = useState<any[]>([])
  const [loadingTools, setLoadingTools] = useState(false)
  const [mainAgentId, setMainAgentId] = useState<string | null>(null)
  const [subAgentList, setSubAgentList] = useState<any[]>([])
  const [loadingAgents, setLoadingAgents] = useState(false)
  const [enabledToolIds, setEnabledToolIds] = useState<number[]>([])
  const [enabledAgentIds, setEnabledAgentIds] = useState<number[]>([])
  const [localIsGenerating, setLocalIsGenerating] = useState(false)
  const [mcpList, setMcpList] = useState<any[]>([])

  // load tools when page is loaded
  useEffect(() => {
    const loadTools = async () => {
      setLoadingTools(true)
      try {
        const result = await fetchTools()
        if (result.success) {
          setTools(result.data)
        } else {
          message.error(result.message)
        }
      } catch (error) {
        console.error('加载工具列表失败:', error)
        message.error('获取工具列表失败，请刷新页面重试')
      } finally {
        setLoadingTools(false)
      }
    }
    
    loadTools()
  }, [])

  // get mcp list
  useEffect(() => {
    const loadMcpList = async () => {
      const result = await fetchMcpList();
      if (result.success) {
        setMcpList(result.data);
      } else {
        message.error(result.message);
      }
    }
    loadMcpList();
  }, [])

  // get agent list
  const fetchAgents = async () => {
    setLoadingAgents(true);
    try {
      const result = await fetchAgentList();
      if (result.success) {
        setSubAgentList(result.data.subAgentList);
        setMainAgentId(result.data.mainAgentId ? String(result.data.mainAgentId) : null);
        setEnabledToolIds(result.data.enabledToolIds);
        setEnabledAgentIds(result.data.enabledAgentIds);
        
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
      } else {
        message.error(result.message || '获取Agent列表失败');
      }
    } catch (error) {
      console.error('获取Agent列表失败:', error);
      message.error('获取Agent列表失败，请稍后重试');
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
      // send the current configuration data to the main page
      window.dispatchEvent(new CustomEvent('agentConfigDataResponse', {
        detail: {
          businessLogic: businessLogic,
          systemPrompt: systemPrompt
        }
      }));
    };

    window.addEventListener('getAgentConfigData', handleGetAgentConfigData);

    return () => {
      window.removeEventListener('getAgentConfigData', handleGetAgentConfigData);
    };
  }, [businessLogic, systemPrompt]);

  // When the tool list is loaded, check and set the enabled tools
  useEffect(() => {
    if (tools.length > 0 && enabledToolIds.length > 0) {
      const enabledTools = tools.filter(tool => 
        enabledToolIds.includes(Number(tool.id))
      );
      setSelectedTools(enabledTools);
    }
  }, [tools, enabledToolIds]);

  // When the agent list is loaded, check and set the selected agents
  useEffect(() => {
    if (subAgentList.length > 0 && enabledAgentIds.length > 0) {
      const enabledAgents = subAgentList.filter(agent => 
        enabledAgentIds.includes(Number(agent.id))
      );
      setSelectedAgents(enabledAgents);
    }
  }, [subAgentList, enabledAgentIds]);

  // Monitor the status change of creating a new agent, and reset the relevant status
  useEffect(() => {
    // Reset all states to initial values
    setBusinessLogic('');
    setSystemPrompt('');
    setSelectedAgents([]);
    setSelectedTools([]);
    setTestQuestion('');
    setTestAnswer('');
    
    // Reset the main agent configuration related status
    if (!isCreatingNewAgent) {
      setMainAgentModel(OpenAIModel.MainModel);
      setMainAgentMaxStep(5);
      setMainAgentPrompt('');
    }
  }, [isCreatingNewAgent]);


  return (
    <div className="w-full h-full mx-auto px-4" style={{ maxWidth: "1920px" }}>
      <div className="w-full h-full">
        <Row gutter={[LAYOUT_CONFIG.CARD_GAP, LAYOUT_CONFIG.CARD_GAP]} className="h-full">
          {/* Left Timeline Guide */}
          <Col xs={24} md={24} lg={4} xl={4} className="h-full">
            <div className="bg-white border border-gray-200 rounded-md flex flex-col overflow-hidden p-4">
              <div
                className="h-full flex flex-col"
                style={{
                  height: LAYOUT_CONFIG.MAIN_CONTENT_HEIGHT,
                  overflowY: "auto",
                  overflowX: "hidden"
                }}
              >
                <GuideSteps
                  isCreatingNewAgent={isCreatingNewAgent}
                  systemPrompt={systemPrompt}
                  businessLogic={businessLogic}
                  selectedTools={selectedTools}
                  selectedAgents={selectedAgents}
                  mainAgentId={mainAgentId}
                  subAgentList={subAgentList}
                  loadingAgents={loadingAgents}
                />
              </div>
            </div>
          </Col>

          {/* Middle Panel - Business Logic Configuration */}
          <Col xs={24} md={24} lg={13} xl={13}>
            <div className="bg-white border border-gray-200 rounded-md flex flex-col overflow-hidden p-4">
              <div style={{ 
                height: LAYOUT_CONFIG.MAIN_CONTENT_HEIGHT, 
                overflowY: "auto",
                overflowX: "hidden"
              }}>
                <BusinessLogicConfig 
                  businessLogic={businessLogic}
                  setBusinessLogic={setBusinessLogic}
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
                  mainAgentPrompt={mainAgentPrompt}
                  setMainAgentPrompt={setMainAgentPrompt}
                  tools={tools}
                  loadingTools={loadingTools}
                  subAgentList={subAgentList}
                  loadingAgents={loadingAgents}
                  mainAgentId={mainAgentId}
                  setMainAgentId={setMainAgentId}
                  setSubAgentList={setSubAgentList}
                  enabledAgentIds={enabledAgentIds}
                  setEnabledAgentIds={setEnabledAgentIds}
                  localIsGenerating={localIsGenerating}
                  mcpList={mcpList}
                  setTools={setTools}
                />
              </div>
            </div>
          </Col>
          
          {/* Right Panel - System Prompt Word Configuration */}
          <Col xs={24} md={24} lg={7} xl={7}>
            <div className="bg-white border border-gray-200 rounded-md flex flex-col overflow-hidden p-4">
              <div style={{ 
                height: LAYOUT_CONFIG.MAIN_CONTENT_HEIGHT, 
                overflowY: "auto",
                overflowX: "hidden"
              }}>
                <SystemPromptDisplay
                  prompt={systemPrompt}
                  onPromptChange={setSystemPrompt}
                  isGenerating={isGenerating}
                  onDebug={() => setIsDebugDrawerOpen(true)}
                  agentId={mainAgentId ? parseInt(mainAgentId) : undefined}
                  taskDescription={businessLogic}
                  onLocalIsGeneratingChange={setLocalIsGenerating}
                />
              </div>
            </div>
          </Col>
        </Row>
      </div>

      {/* Commissioning drawer */}
      <Drawer
        title="Agent调试"
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
            agentId={mainAgentId ? Number(mainAgentId) : undefined}
          />
        </div>
      </Drawer>
    </div>
  )
} 