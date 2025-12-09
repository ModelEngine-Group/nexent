"use client";

import React, { useState, useEffect } from "react";
import { Modal, Steps, Button, Select, Input, Form, Tag, Space, Spin, App, Collapse, Radio } from "antd";
import { DownloadOutlined, CheckCircleOutlined, CloseCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { ModelOption } from "@/types/modelConfig";
import { modelService } from "@/services/modelService";
import { getMcpServerList, addMcpServer, updateToolList } from "@/services/mcpService";
import { McpServer, AgentRefreshEvent } from "@/types/agentConfig";
import { ImportAgentData } from "@/hooks/useAgentImport";
import { importAgent } from "@/services/agentConfigService";
import log from "@/lib/logger";

export interface AgentImportWizardProps {
  visible: boolean;
  onCancel: () => void;
  initialData: ImportAgentData | null; // ExportAndImportDataFormat structure
  onImportComplete?: () => void;
  title?: string; // Optional custom title
  agentDisplayName?: string; // Optional display name for preview
  agentDescription?: string; // Optional description for preview
}

interface ConfigField {
  agentKey: string; // key in agent_info, e.g. "1"
  agentDisplayName: string; // display name for grouping / hint
  fieldPath: string; // e.g., "duty_prompt", "tools[0].params.api_key"
  fieldLabel: string; // User-friendly label
  promptHint?: string; // Hint from <TO_CONFIG:XXXX>
  currentValue: string;
  valueKey: string; // unique key for configValues map (agentKey + fieldPath)
}

interface McpServerToInstall {
  mcp_server_name: string;
  mcp_url: string;
  isInstalled: boolean;
  isUrlEditable: boolean; // true if url is <TO_CONFIG>
  editedUrl?: string;
}

const needsConfig = (value: any): boolean => {
  if (typeof value === "string") {
    return value.trim() === "<TO_CONFIG>" || value.trim().startsWith("<TO_CONFIG:");
  }
  return false;
};

const extractPromptHint = (value: string): string | undefined => {
  if (typeof value !== "string") return undefined;
  const match = value.trim().match(/^<TO_CONFIG:(.+)>$/);
  return match ? match[1] : undefined;
};

// Parse Markdown links in text and convert to React elements
const parseMarkdownLinks = (text: string): React.ReactNode[] => {
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;
  let key = 0;

  while ((match = linkRegex.exec(text)) !== null) {
    // Add text before the link
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index));
    }
    // Add the link
    parts.push(
      <a
        key={key++}
        href={match[2]}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        {match[1]}
      </a>
    );
    lastIndex = match.index + match[0].length;
  }
  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
};

export default function AgentImportWizard({
  visible,
  onCancel,
  initialData,
  onImportComplete,
  title,
  agentDisplayName,
  agentDescription,
}: AgentImportWizardProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const [currentStep, setCurrentStep] = useState(0);
  const [llmModels, setLlmModels] = useState<ModelOption[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  
  // Model selection mode: "unified" (one model for all) or "individual" (separate model for each agent)
  const [modelSelectionMode, setModelSelectionMode] = useState<"unified" | "individual">("unified");
  
  // Unified mode: single model for all agents
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const [selectedModelName, setSelectedModelName] = useState<string>("");
  
  // Individual mode: model for each agent
  const [selectedModelsByAgent, setSelectedModelsByAgent] = useState<Record<string, { modelId: number | null; modelName: string }>>({});

  const [configFields, setConfigFields] = useState<ConfigField[]>([]);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});

  const [mcpServers, setMcpServers] = useState<McpServerToInstall[]>([]);
  const [existingMcpServers, setExistingMcpServers] = useState<McpServer[]>([]);
  const [loadingMcpServers, setLoadingMcpServers] = useState(false);
  const [installingMcp, setInstallingMcp] = useState<Record<string, boolean>>({});
  const [isImporting, setIsImporting] = useState(false);

  // Helper: Refresh tools and agents after MCP changes
  const refreshToolsAndAgents = async () => {
    try {
      const updateResult = await updateToolList();
      if (updateResult.success) {
        // Notify listeners (AgentSetupOrchestrator, ToolPool, etc.) that tools have been updated
        window.dispatchEvent(new CustomEvent("toolsUpdated"));
      }

      // Trigger agent list refresh so availability status reflects new MCP tools
      window.dispatchEvent(
        new CustomEvent("refreshAgentList") as AgentRefreshEvent
      );
    } catch (error) {
      // Do not block user flow on refresh errors
      log.error("Failed to refresh tools and agents after MCP install:", error);
    }
  };

  // Load LLM models
  useEffect(() => {
    if (visible) {
      loadLLMModels();
    }
  }, [visible]);

  // Parse agent data for config fields and MCP servers
  useEffect(() => {
    if (visible && initialData) {
      parseConfigFields();
      parseMcpServers();
      initializeModelSelection();
    }
  }, [visible, initialData]);

  // Initialize model selection for individual mode
  const initializeModelSelection = () => {
    if (!initialData?.agent_info) return;
    
    const initialModels: Record<string, { modelId: number | null; modelName: string }> = {};
    
    Object.keys(initialData.agent_info).forEach(agentKey => {
      initialModels[agentKey] = { modelId: null, modelName: "" };
    });
    
    setSelectedModelsByAgent(initialModels);
  };

  const loadLLMModels = async () => {
    setLoadingModels(true);
    try {
      const models = await modelService.getLLMModels();
      setLlmModels(models.filter(m => m.connect_status === "available"));
      
      // Auto-select first available model
      if (models.length > 0 && models[0].connect_status === "available") {
        setSelectedModelId(models[0].id);
        setSelectedModelName(models[0].displayName);
      }
    } catch (error) {
      log.error("Failed to load LLM models:", error);
      message.error(t("market.install.error.loadModels", "Failed to load models"));
    } finally {
      setLoadingModels(false);
    }
  };

  const parseConfigFields = () => {
    if (!initialData?.agent_info) {
      setConfigFields([]);
      setConfigValues({});
      return;
    }

    const fields: ConfigField[] = [];
    const agentInfoMap = initialData.agent_info;
    const mainAgentId = String(initialData.agent_id);

    // Iterate through all agents (main agent + sub-agents)
    Object.entries(agentInfoMap).forEach(([agentKey, rawInfo]) => {
      const info = rawInfo as any;
      const agentDisplayName =
        info.display_name || info.name || `${t("market.install.agent.defaultName", "Agent")} ${agentKey}`;
      const isMainAgent = agentKey === mainAgentId;

      // Check basic fields for this agent
      const basicFields: Array<{ key: string; label: string }> = [
        {
          key: "description",
          label: t("market.detail.description", "Description"),
        },
        {
          key: "business_description",
          label: t("market.detail.businessDescription", "Business Description"),
        },
        {
          key: "duty_prompt",
          label: t("market.detail.dutyPrompt", "Duty Prompt"),
        },
        {
          key: "constraint_prompt",
          label: t("market.detail.constraintPrompt", "Constraint Prompt"),
        },
        {
          key: "few_shots_prompt",
          label: t("market.detail.fewShotsPrompt", "Few Shots Prompt"),
        },
      ];

      basicFields.forEach(({ key, label }) => {
        const value = info[key];
        if (needsConfig(value)) {
          const valueKey = `${agentKey}::${key}`;
          fields.push({
            agentKey,
            agentDisplayName,
            fieldPath: key,
            fieldLabel: isMainAgent ? label : `${agentDisplayName} - ${label}`,
            promptHint: extractPromptHint(value as string),
            currentValue: value as string,
            valueKey,
          });
        }
      });

      // Check tool params for this agent
      if (Array.isArray(info.tools)) {
        info.tools.forEach((tool: any, toolIndex: number) => {
          if (tool.params && typeof tool.params === "object") {
            Object.entries(tool.params).forEach(([paramKey, paramValue]) => {
              if (needsConfig(paramValue)) {
                const fieldPath = `tools[${toolIndex}].params.${paramKey}`;
                const valueKey = `${agentKey}::${fieldPath}`;
                fields.push({
                  agentKey,
                  agentDisplayName,
                  fieldPath,
                  fieldLabel: `${agentDisplayName} - ${tool.name || tool.class_name} - ${paramKey}`,
                  promptHint: extractPromptHint(paramValue as string),
                  currentValue: paramValue as string,
                  valueKey,
                });
              }
            });
          }
        });
      }
    });

    setConfigFields(fields);

    // Initialize config values using valueKey
    const initialValues: Record<string, string> = {};
    fields.forEach(field => {
      initialValues[field.valueKey] = "";
    });
    setConfigValues(initialValues);
  };

  const parseMcpServers = async () => {
    // Use mcp_info as the source of truth
    if (!initialData?.mcp_info || initialData.mcp_info.length === 0) {
      setMcpServers([]);
      return;
    }

    setLoadingMcpServers(true);
    try {
      // Load existing MCP servers from system
      const result = await getMcpServerList();
      const existing = result.success ? result.data : [];
      setExistingMcpServers(existing);

      // Check each MCP server from mcp_info
      const serversToInstall: McpServerToInstall[] = initialData.mcp_info.map((mcp: any) => {
        const isUrlConfigNeeded = needsConfig(mcp.mcp_url);
        
        // Check if already installed (match by both name and url)
        const isInstalled = !isUrlConfigNeeded && existing.some(
          (existingMcp: McpServer) => 
            existingMcp.service_name === mcp.mcp_server_name && 
            existingMcp.mcp_url === mcp.mcp_url
        );

        return {
          mcp_server_name: mcp.mcp_server_name,
          mcp_url: mcp.mcp_url,
          isInstalled,
          isUrlEditable: isUrlConfigNeeded,
          editedUrl: isUrlConfigNeeded ? "" : mcp.mcp_url,
        };
      });

      setMcpServers(serversToInstall);
    } catch (error) {
      log.error("Failed to check MCP servers:", error);
      message.error(t("market.install.error.checkMcp", "Failed to check MCP servers"));
    } finally {
      setLoadingMcpServers(false);
    }
  };

  const handleMcpUrlChange = (index: number, newUrl: string) => {
    setMcpServers(prev => {
      const updated = [...prev];
      updated[index].editedUrl = newUrl;
      return updated;
    });
  };

  const handleInstallMcp = async (index: number) => {
    const mcp = mcpServers[index];
    const urlToUse = mcp.editedUrl || mcp.mcp_url;

    if (!urlToUse || urlToUse.trim() === "") {
      message.error(t("market.install.error.mcpUrlRequired", "MCP URL is required"));
      return;
    }

    const key = `${index}`;
    setInstallingMcp(prev => ({ ...prev, [key]: true }));

    try {
      const result = await addMcpServer(urlToUse, mcp.mcp_server_name);
      if (result.success) {
        // After creating MCP server, refresh tool list and agent availability
        await refreshToolsAndAgents();

        message.success(t("market.install.success.mcpInstalled", "MCP server installed successfully"));
        // Mark as installed - update state directly without re-fetching
        setMcpServers(prev => {
          const updated = [...prev];
          updated[index].isInstalled = true;
          updated[index].editedUrl = urlToUse;
          return updated;
        });
      } else {
        message.error(result.message || t("market.install.error.mcpInstall", "Failed to install MCP server"));
      }
    } catch (error) {
      log.error("Failed to install MCP server:", error);
      message.error(t("market.install.error.mcpInstall", "Failed to install MCP server"));
    } finally {
      setInstallingMcp(prev => ({ ...prev, [key]: false }));
    }
  };

  const handleNext = () => {
    if (currentStep === 0) {
      // Step 1: Model selection validation
      if (modelSelectionMode === "unified") {
        if (!selectedModelId || !selectedModelName) {
          message.error(t("market.install.error.modelRequired", "Please select a model"));
          return;
        }
      } else {
        // Individual mode: check all agents have models selected
        const agentInfoMap = initialData?.agent_info;
        if (agentInfoMap) {
          const missingModels = Object.keys(agentInfoMap).filter(agentKey => {
            const model = selectedModelsByAgent[agentKey];
            return !model || !model.modelId || !model.modelName;
          });
          if (missingModels.length > 0) {
            message.error(t("market.install.error.allModelsRequired", "Please select models for all agents"));
            return;
          }
        }
      }
    } else if (currentStep === 1) {
      // Step 2: Config fields validation
      const emptyFields = configFields.filter(field => !configValues[field.valueKey]?.trim());
      if (emptyFields.length > 0) {
        message.error(t("market.install.error.configRequired", "Please fill in all required fields"));
        return;
      }
    }

    setCurrentStep(prev => prev + 1);
  };

  const handlePrevious = () => {
    setCurrentStep(prev => prev - 1);
  };

  const handleImport = async () => {
    try {
      // Prepare the data structure for import
      const importData = prepareImportData();
      
      if (!importData) {
        message.error(t("market.install.error.invalidData", "Invalid agent data"));
        return;
      }

      log.info("Importing agent with data:", importData);

      setIsImporting(true);
      // Import using agentConfigService directly
      const result = await importAgent(importData, { forceImport: false });
      
      if (result.success) {
        message.success(t("market.install.success", "Agent installed successfully!"));
        onImportComplete?.();
        handleCancel(); // Close wizard after success
      } else {
        message.error(result.message || t("market.install.error.installFailed", "Failed to install agent"));
      }
    } catch (error) {
      log.error("Failed to install agent:", error);
      message.error(t("market.install.error.installFailed", "Failed to install agent"));
    } finally {
      setIsImporting(false);
    }
  };

  const prepareImportData = (): ImportAgentData | null => {
    if (!initialData) return null;

    // Clone agent data structure
    const agentJson = JSON.parse(JSON.stringify(initialData));

    // Update model information based on selection mode
    if (modelSelectionMode === "unified") {
      // Unified mode: apply selected model to all agents
      Object.entries(agentJson.agent_info).forEach(([agentKey, agentInfo]: [string, any]) => {
        agentInfo.model_id = selectedModelId;
        agentInfo.model_name = selectedModelName;
        
        // Clear business logic model fields
        agentInfo.business_logic_model_id = null;
        agentInfo.business_logic_model_name = null;
      });
    } else {
      // Individual mode: apply models to all agents
      Object.entries(agentJson.agent_info).forEach(([agentKey, agentInfo]: [string, any]) => {
        const modelSelection = selectedModelsByAgent[agentKey];
        if (modelSelection && modelSelection.modelId && modelSelection.modelName) {
          agentInfo.model_id = modelSelection.modelId;
          agentInfo.model_name = modelSelection.modelName;
          
          // Clear business logic model fields
          agentInfo.business_logic_model_id = null;
          agentInfo.business_logic_model_name = null;
        }
      });
    }

    // Update config fields for all agents (main + sub-agents)
    configFields.forEach(field => {
      const value = configValues[field.valueKey];
      if (!value) return; // Skip empty values

      // Find the target agent by agentKey
      const targetAgentInfo = agentJson.agent_info[field.agentKey];
      if (!targetAgentInfo) return;

      if (field.fieldPath.includes("tools[")) {
        // Handle tool params
        const match = field.fieldPath.match(/tools\[(\d+)\]\.params\.(.+)/);
        if (match && targetAgentInfo.tools) {
          const toolIndex = parseInt(match[1]);
          const paramKey = match[2];
          if (targetAgentInfo.tools[toolIndex]) {
            if (!targetAgentInfo.tools[toolIndex].params) {
              targetAgentInfo.tools[toolIndex].params = {};
            }
            targetAgentInfo.tools[toolIndex].params[paramKey] = value;
          }
        }
      } else {
        // Handle basic fields
        targetAgentInfo[field.fieldPath] = value;
      }
    });

    // Update MCP info
    if (agentJson.mcp_info) {
      agentJson.mcp_info = agentJson.mcp_info.map((mcp: any) => {
        const matchingServer = mcpServers.find(
          s => s.mcp_server_name === mcp.mcp_server_name
        );
        if (matchingServer && matchingServer.editedUrl) {
          return {
            ...mcp,
            mcp_url: matchingServer.editedUrl,
          };
        }
        return mcp;
      });
    }

    return agentJson;
  };

  const handleCancel = () => {
    // Reset state
    setCurrentStep(0);
    setModelSelectionMode("unified");
    setSelectedModelId(null);
    setSelectedModelName("");
    setSelectedModelsByAgent({});
    setConfigFields([]);
    setConfigValues({});
    setMcpServers([]);
    setIsImporting(false);
    onCancel();
  };

  // Filter only required steps for navigation
  const steps = [
    {
      key: "model",
      title: t("market.install.step.model", "Select Model"),
    },
    configFields.length > 0 && {
      key: "config",
      title: t("market.install.step.config", "Configure Fields"),
    },
    mcpServers.length > 0 && {
      key: "mcp",
      title: t("market.install.step.mcp", "MCP Servers"),
    },
  ].filter(Boolean) as Array<{ key: string; title: string }>;

  // Check if can proceed to next step
  const canProceed = () => {
    const currentStepKey = steps[currentStep]?.key;
    
    if (currentStepKey === "model") {
      if (modelSelectionMode === "unified") {
        return selectedModelId !== null && selectedModelName !== "";
      } else {
        // Individual mode: check all agents have models
        const agentInfoMap = initialData?.agent_info;
        if (!agentInfoMap) return false;
        return Object.keys(agentInfoMap).every(agentKey => {
          const model = selectedModelsByAgent[agentKey];
          return model && model.modelId && model.modelName;
        });
      }
    } else if (currentStepKey === "config") {
      return configFields.every(field => configValues[field.valueKey]?.trim());
    } else if (currentStepKey === "mcp") {
      // All non-editable MCPs should be installed or have edited URLs
      return mcpServers.every(mcp => 
        mcp.isInstalled || 
        (mcp.isUrlEditable && mcp.editedUrl && mcp.editedUrl.trim() !== "") ||
        (!mcp.isUrlEditable && mcp.mcp_url && mcp.mcp_url.trim() !== "")
      );
    }
    
    return true;
  };

  const renderStepContent = () => {
    const currentStepKey = steps[currentStep]?.key;

    if (currentStepKey === "model") {
      return (
        <div className="space-y-6">
          {/* Agent Info - Title and Description Style */}
          {(agentDisplayName || agentDescription) && (
            <div className="bg-gradient-to-r from-purple-50 to-indigo-50 dark:from-purple-900/20 dark:to-indigo-900/20 rounded-lg p-6 border border-purple-100 dark:border-purple-800">
              {agentDisplayName && (
                <h3 className="text-xl font-bold text-purple-900 dark:text-purple-100 mb-2">
                  {agentDisplayName}
                </h3>
              )}
              {agentDescription && (
                <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                  {agentDescription}
                </p>
              )}
            </div>
          )}

          <div className="space-y-4">
            {/* Model selection mode toggle */}
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 block">
                {t("market.install.model.mode", "Model Selection Mode")}
              </label>
              <Radio.Group
                value={modelSelectionMode}
                onChange={(e) => {
                  setModelSelectionMode(e.target.value);
                  // Reset selections when switching modes
                  if (e.target.value === "unified") {
                    setSelectedModelsByAgent({});
                  } else {
                    setSelectedModelId(null);
                    setSelectedModelName("");
                    initializeModelSelection();
                  }
                }}
                className="w-full"
              >
                <Radio value="unified">
                  {t("market.install.model.mode.unified", "Unified: Use one model for all agents")}
                </Radio>
                <Radio value="individual">
                  {t("market.install.model.mode.individual", "Individual: Select model for each agent")}
                </Radio>
              </Radio.Group>
            </div>

            {modelSelectionMode === "unified" ? (
              // Unified mode: single model selection for all agents
              <div>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                  {t("market.install.model.description.unified", "Select a model from your configured models. This model will be applied to all agents (main agent and sub-agents).")}
                </p>
                
                <div className="flex items-center gap-3">
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
                    {t("market.install.model.label", "Model")}
                    <span className="text-red-500 ml-1">*</span>
                  </label>
                  <div className="flex-1">
                    {loadingModels ? (
                      <Spin />
                    ) : (
                      <Select
                        value={selectedModelName || undefined}
                        onChange={(value, option) => {
                          const modelId = option && 'key' in option ? Number(option.key) : null;
                          setSelectedModelName(value);
                          setSelectedModelId(modelId);
                        }}
                        size="large"
                        style={{ width: "100%" }}
                        placeholder={t("market.install.model.placeholder", "Select a model")}
                      >
                        {llmModels.map((model) => (
                          <Select.Option key={model.id} value={model.displayName}>
                            {model.displayName}
                          </Select.Option>
                        ))}
                      </Select>
                    )}
                  </div>
                </div>

                {llmModels.length === 0 && !loadingModels && (
                  <div className="text-sm text-red-600 mt-2">
                    {t("market.install.model.noModels", "No available models. Please configure models first.")}
                  </div>
                )}
              </div>
            ) : (
              // Individual mode: model selection for each agent
              <div>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                  {t("market.install.model.description.individual", "Select a model for each agent (main agent and sub-agents).")}
                </p>

                {initialData?.agent_info && (() => {
                  // Sort agents: main agent first, then sub-agents
                  const agentEntries = Object.entries(initialData.agent_info as Record<string, any>);
                  const mainAgentKey = String(initialData.agent_id);
                  const sortedEntries = agentEntries.sort(([keyA], [keyB]) => {
                    if (keyA === mainAgentKey) return -1;
                    if (keyB === mainAgentKey) return 1;
                    return 0;
                  });

                  return (
                    <div className="space-y-4">
                      {sortedEntries.map(([agentKey, agentInfo]: [string, any]) => {
                        const agentDisplayName = agentInfo.display_name || agentInfo.name || `${t("market.install.agent.defaultName", "Agent")} ${agentKey}`;
                        const isMainAgent = agentKey === mainAgentKey;
                        const currentSelection = selectedModelsByAgent[agentKey] || { modelId: null, modelName: "" };

                        return (
                          <div 
                            key={agentKey} 
                            className={`border rounded-lg p-4 ${
                              isMainAgent 
                                ? "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800" 
                                : "border-gray-200 dark:border-gray-700"
                            }`}
                          >
                            <div className="flex items-center gap-2 mb-3">
                              <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                {agentDisplayName}
                              </label>
                              {isMainAgent && (
                                <Tag color="blue" className="text-xs">
                                  {t("market.install.agent.main", "Main")}
                                </Tag>
                              )}
                            </div>
                            <div className="flex items-center gap-3">
                              <label className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                                {t("market.install.model.label", "Model")}
                                <span className="text-red-500 ml-1">*</span>
                              </label>
                              <div className="flex-1">
                                {loadingModels ? (
                                  <Spin />
                                ) : (
                                  <Select
                                    value={currentSelection.modelName || undefined}
                                    onChange={(value, option) => {
                                      const modelId = option && 'key' in option ? Number(option.key) : null;
                                      setSelectedModelsByAgent(prev => ({
                                        ...prev,
                                        [agentKey]: { modelId, modelName: value },
                                      }));
                                    }}
                                    size="large"
                                    style={{ width: "100%" }}
                                    placeholder={t("market.install.model.placeholder", "Select a model")}
                                  >
                                    {llmModels.map((model) => (
                                      <Select.Option key={model.id} value={model.displayName}>
                                        {model.displayName}
                                      </Select.Option>
                                    ))}
                                  </Select>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

                {llmModels.length === 0 && !loadingModels && (
                  <div className="text-sm text-red-600 mt-2">
                    {t("market.install.model.noModels", "No available models. Please configure models first.")}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      );
    } else if (currentStepKey === "config") {
      // Group config fields by agent
      const fieldsByAgent = configFields.reduce((acc, field) => {
        if (!acc[field.agentKey]) {
          acc[field.agentKey] = {
            agentDisplayName: field.agentDisplayName,
            fields: [],
          };
        }
        acc[field.agentKey].fields.push(field);
        return acc;
      }, {} as Record<string, { agentDisplayName: string; fields: ConfigField[] }>);

      const collapseItems = Object.entries(fieldsByAgent).map(([agentKey, { agentDisplayName, fields }]) => ({
        key: agentKey,
        label: (
          <span className="font-medium">
            {agentDisplayName}
            <span className="text-gray-500 text-sm ml-2">
              ({fields.length} {t("market.install.config.fields", "fields")})
            </span>
          </span>
        ),
        children: (
          <Form layout="vertical" className="mt-2">
            {fields.map((field) => (
              <Form.Item
                key={field.valueKey}
                label={
                  <span>
                    {field.fieldLabel.replace(`${agentDisplayName} - `, "")}
                    <span className="text-red-500 ml-1">*</span>
                  </span>
                }
                required={false}
              >
                <Input.TextArea
                  value={configValues[field.valueKey] || ""}
                  onChange={(e) => {
                    setConfigValues(prev => ({
                      ...prev,
                      [field.valueKey]: e.target.value,
                    }));
                  }}
                  placeholder={field.promptHint || t("market.install.config.placeholder", "Enter configuration value")}
                  rows={3}
                  size="large"
                />
              </Form.Item>
            ))}
          </Form>
        ),
      }));

      return (
        <div className="space-y-4">
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            {t("market.install.config.description", "Please configure the following required fields for this agent and its sub-agents.")}
          </p>

          {collapseItems.length > 0 ? (
            <Collapse
              items={collapseItems}
              defaultActiveKey={Object.keys(fieldsByAgent)}
              className="agent-config-collapse"
            />
          ) : (
            <p className="text-sm text-gray-500 text-center py-4">
              {t("market.install.config.noFields", "No configuration fields required.")}
            </p>
          )}
        </div>
      );
    } else if (currentStepKey === "mcp") {
      return (
        <div className="space-y-4">
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            {t("market.install.mcp.description", "This agent requires the following MCP servers. Please install or configure them.")}
          </p>

          {loadingMcpServers ? (
            <div className="text-center py-8">
              <Spin />
            </div>
          ) : (
            <div className="space-y-3">
              {mcpServers.map((mcp, index) => (
                <div
                  key={`${mcp.mcp_server_name}-${index}`}
                  className="border border-gray-200 dark:border-gray-700 rounded-lg p-4"
                >
                  <div className="flex items-center justify-between w-full gap-4 mb-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-base">
                        {mcp.mcp_server_name}
                      </span>
                      {mcp.isInstalled ? (
                        <Tag icon={<CheckCircleOutlined />} color="success" className="text-xs">
                          {t("market.install.mcp.installed", "Installed")}
                        </Tag>
                      ) : (
                        <Tag icon={<CloseCircleOutlined />} color="default" className="text-xs">
                          {t("market.install.mcp.notInstalled", "Not Installed")}
                        </Tag>
                      )}
                    </div>

                    {!mcp.isInstalled && (
                      <Button
                        type="primary"
                        size="middle"
                        icon={<PlusOutlined />}
                        onClick={() => handleInstallMcp(index)}
                        loading={installingMcp[String(index)]}
                        disabled={!mcp.editedUrl || mcp.editedUrl.trim() === ""}
                        className="flex-shrink-0"
                      >
                        {t("market.install.mcp.install", "Install")}
                      </Button>
                    )}
                  </div>

                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                        MCP URL:
                      </span>
                      {(mcp.isUrlEditable || !mcp.isInstalled) ? (
                        <Input
                          value={mcp.editedUrl || ""}
                          onChange={(e) => handleMcpUrlChange(index, e.target.value)}
                          placeholder={mcp.isUrlEditable 
                            ? t("market.install.mcp.urlPlaceholder", "Enter MCP server URL")
                            : mcp.mcp_url
                          }
                          size="middle"
                          disabled={mcp.isInstalled}
                          style={{ maxWidth: "400px" }}
                          className={mcp.isUrlEditable && needsConfig(mcp.mcp_url) ? "bg-gray-100 dark:bg-gray-800" : ""}
                        />
                      ) : (
                        <span className="text-sm text-gray-700 dark:text-gray-300 break-all">
                          {mcp.editedUrl || mcp.mcp_url}
                        </span>
                      )}
                    </div>
                    {/* Show hint if URL needs configuration */}
                    {mcp.isUrlEditable && needsConfig(mcp.mcp_url) && (() => {
                      const hint = extractPromptHint(mcp.mcp_url);
                      const hintText = hint || t("market.install.mcp.defaultConfigHint", "Please enter the MCP server URL");
                      return (
                        <div className="ml-0 text-xs text-gray-500 dark:text-gray-400 max-w-md">
                          <span className="text-gray-600 dark:text-gray-400 inline-flex flex-wrap items-center gap-1">
                            {parseMarkdownLinks(hintText)}
                          </span>
                        </div>
                      );
                    })()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    return null;
  };

  const isLastStep = currentStep === steps.length - 1;

  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <DownloadOutlined />
          <span>{title || t("market.install.title", "Install Agent")}</span>
        </div>
      }
      open={visible}
      onCancel={handleCancel}
      width={800}
      footer={
        <div className="flex justify-between">
          <Button onClick={handleCancel}>
            {t("common.cancel", "Cancel")}
          </Button>
          <Space>
            {currentStep > 0 && (
              <Button onClick={handlePrevious}>
                {t("market.install.button.previous", "Previous")}
              </Button>
            )}
            {!isLastStep && (
              <Button
                type="primary"
                onClick={handleNext}
                disabled={!canProceed()}
              >
                {t("market.install.button.next", "Next")}
              </Button>
            )}
            {isLastStep && (
              <Button
                type="primary"
                onClick={handleImport}
                disabled={!canProceed()}
                loading={isImporting}
                icon={<DownloadOutlined />}
              >
                {isImporting 
                  ? t("market.install.button.installing", "Installing...")
                  : t("market.install.button.install", "Install")}
              </Button>
            )}
          </Space>
        </div>
      }
    >
      <div className="py-4">
        <Steps
          current={currentStep}
          items={steps.map(step => ({
            title: step.title,
          }))}
          className="mb-6"
        />

        <div className="min-h-[300px]">
          {renderStepContent()}
        </div>
      </div>
    </Modal>
  );
}

