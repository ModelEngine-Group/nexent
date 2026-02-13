"use client";

import React, { useState, useEffect, useRef } from "react";
import { Modal, Steps, Button, Select, Input, Form, Tag, Space, Spin, App, Collapse, Radio } from "antd";
import { Download, CircleCheck, CircleX, Plus, Wrench, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ModelOption } from "@/types/modelConfig";
import { modelService } from "@/services/modelService";
import { getMcpServerList, addMcpServer, updateToolList } from "@/services/mcpService";
import { McpServer } from "@/types/agentConfig";
import { ImportAgentData } from "@/hooks/useAgentImport";
import { importAgent, checkAgentNameConflictBatch, regenerateAgentNameBatch, fetchTools } from "@/services/agentConfigService";
import { useQueryClient } from "@tanstack/react-query";
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
  const queryClient = useQueryClient();

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
  const [availableTools, setAvailableTools] = useState<Array<{ name?: string; origin_name?: string; usage?: string; source?: string }>>([]);
  const [missingTools, setMissingTools] = useState<Array<{ name: string; source?: string; usage?: string; agents: string[] }>>([]);
  const [loadingTools, setLoadingTools] = useState(false);

  // Name conflict checking and renaming
  // Structure: agentKey -> { hasConflict, conflictAgents, renamedName, renamedDisplayName }
  const [agentNameConflicts, setAgentNameConflicts] = useState<Record<string, {
    hasConflict: boolean;
    conflictAgents: Array<{ name?: string; display_name?: string }>;
    renamedName: string;
    renamedDisplayName: string;
  }>>({});
  const [checkingName, setCheckingName] = useState(false);
  const [regeneratingAll, setRegeneratingAll] = useState(false);
  // Track which agents have been successfully renamed (no conflicts)
  const [successfullyRenamedAgents, setSuccessfullyRenamedAgents] = useState<Set<string>>(new Set());
  // Debounce timer for manual name changes - use ref to avoid stale closures
  const nameCheckTimerRef = useRef<NodeJS.Timeout | null>(null);
  // Store latest agentNameConflicts in ref to avoid stale closures in timer callbacks
  const agentNameConflictsRef = useRef<Record<string, {
    hasConflict: boolean;
    conflictAgents: Array<{ name?: string; display_name?: string }>;
    renamedName: string;
    renamedDisplayName: string;
  }>>({});

  // Helper: Refresh tools and agents after MCP changes
  const refreshToolsAndAgents = async () => {
    try {
      await updateToolList();
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    } catch (error) {
      // Do not block user flow on refresh errors
      log.error("Failed to refresh tools and agents after MCP install:", error);
    }
  };

  // Load LLM models
  useEffect(() => {
    if (visible) {
      loadLLMModels();
      loadAvailableTools();
    }
  }, [visible]);

  // Check name conflict immediately after file upload
  useEffect(() => {
    if (visible && initialData) {
      checkNameConflict();
    }
  }, [visible, initialData]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (nameCheckTimerRef.current) {
        clearTimeout(nameCheckTimerRef.current);
      }
    };
  }, []);

  // Parse agent data for config fields and MCP servers
  useEffect(() => {
    if (visible && initialData) {
      parseConfigFields();
      parseMcpServers();
      initializeModelSelection();
      computeMissingTools();
    }
  }, [visible, initialData]);

  // Recompute missing tools when available tool list changes
  useEffect(() => {
    if (visible) {
      computeMissingTools();
    }
  }, [visible, availableTools]);

  // Initialize model selection for individual mode
  const initializeModelSelection = () => {
    if (!initialData?.agent_info) return;

    const initialModels: Record<string, { modelId: number | null; modelName: string }> = {};

    Object.keys(initialData.agent_info).forEach(agentKey => {
      initialModels[agentKey] = { modelId: null, modelName: "" };
    });

    setSelectedModelsByAgent(initialModels);
  };

  // Check name conflict for all agents (main agent + sub-agents)
  const checkNameConflict = async () => {
    if (!initialData?.agent_info) return;

    setCheckingName(true);
    const conflicts: Record<string, {
      hasConflict: boolean;
      conflictAgents: Array<{ name?: string; display_name?: string }>;
      renamedName: string;
      renamedDisplayName: string;
    }> = {};

    try {
      // Check all agents in agent_info
      const agentInfoMap = initialData.agent_info;
      const items = Object.entries(agentInfoMap).map(([agentKey, agentInfo]: [string, any]) => ({
        key: agentKey,
        name: agentInfo?.name || "",
        display_name: agentInfo?.display_name,
      }));

      const result = await checkAgentNameConflictBatch({
        items: items.map((item) => ({
          name: item.name,
          display_name: item.display_name,
        })),
      });

      if (!result.success || !Array.isArray(result.data)) {
        log.warn("Skip name conflict check due to fetch failure");
        setAgentNameConflicts({});
        agentNameConflictsRef.current = {};
        setCheckingName(false);
        return;
      }

      result.data.forEach((res: any, idx: number) => {
        const item = items[idx];
        const agentKey = item.key;
        const hasNameConflict = res?.name_conflict || false;
        const hasDisplayNameConflict = res?.display_name_conflict || false;
        const conflictAgentsRaw = Array.isArray(res?.conflict_agents) ? res.conflict_agents : [];
        // Deduplicate by name/display_name
        const seen = new Set<string>();
        const conflictAgents = conflictAgentsRaw.reduce((acc: Array<{ name?: string; display_name?: string }>, curr: any) => {
          const key = `${curr?.name || ""}||${curr?.display_name || ""}`;
          if (seen.has(key)) return acc;
          seen.add(key);
          acc.push({ name: curr?.name, display_name: curr?.display_name });
          return acc;
        }, []);

        const hasConflict = hasNameConflict || hasDisplayNameConflict;
          conflicts[agentKey] = {
            hasConflict,
            conflictAgents,
            renamedName: item.name,
            renamedDisplayName: item.display_name || "",
          };
      });

      setAgentNameConflicts(conflicts);

      // Update successfully renamed agents based on initial check
      // Only add to successfullyRenamedAgents if there was a conflict that was resolved
      // For initial check, we don't add anything since no renaming has happened yet
      setSuccessfullyRenamedAgents((prev) => {
        const next = new Set(prev);
        // Don't modify on initial check - only track agents that were successfully renamed
        return next;
      });
    } catch (error) {
      log.error("Failed to check name conflicts:", error);
    } finally {
      setCheckingName(false);
    }
  };

  // Check name conflict for a specific agent after renaming
  const checkSingleAgentConflict = async (agentKey: string, name: string, displayName?: string) => {
    if (!initialData?.agent_info) return;

    try {
      const result = await checkAgentNameConflictBatch({
        items: [
          {
            name,
            display_name: displayName,
          },
        ],
      });

      if (!result.success || !Array.isArray(result.data) || !result.data[0]) {
        return;
      }

      const checkResult = result.data[0];
      const hasNameConflict = checkResult?.name_conflict || false;
      const hasDisplayNameConflict = checkResult?.display_name_conflict || false;
      const hasConflict = hasNameConflict || hasDisplayNameConflict;
      const conflictAgentsRaw = Array.isArray(checkResult?.conflict_agents) ? checkResult.conflict_agents : [];

      // Deduplicate by name/display_name
      const seen = new Set<string>();
      const conflictAgents = conflictAgentsRaw.reduce((acc: Array<{ name?: string; display_name?: string }>, curr: any) => {
        const key = `${curr?.name || ""}||${curr?.display_name || ""}`;
        if (seen.has(key)) return acc;
        seen.add(key);
        acc.push({ name: curr?.name, display_name: curr?.display_name });
        return acc;
      }, []);

      setAgentNameConflicts((prev) => {
        const next = { ...prev };
        if (!next[agentKey]) {
          const agentInfo = initialData.agent_info[agentKey] as any;
          next[agentKey] = {
            hasConflict: false,
            conflictAgents: [],
            renamedName: agentInfo?.name || "",
            renamedDisplayName: agentInfo?.display_name || "",
          };
        }
        next[agentKey] = {
          ...next[agentKey],
          hasConflict,
          conflictAgents,
          renamedName: name,
          renamedDisplayName: displayName || "",
        };
        agentNameConflictsRef.current = next;
        return next;
      });

      // Update success status
      setSuccessfullyRenamedAgents((prev) => {
        const next = new Set(prev);
        if (hasConflict) {
          next.delete(agentKey);
        } else {
          next.add(agentKey);
        }
        return next;
      });

      return hasConflict;
    } catch (error) {
      log.error("Failed to check single agent conflict:", error);
      return true; // Assume conflict on error to be safe
    }
  };

  // One-click regenerate all conflicted agents using selected model(s)
  const handleRegenerateAll = async () => {
    if (!initialData?.agent_info) return;

    const agentsWithConflicts = Object.entries(agentNameConflicts).filter(
      ([_, conflict]) => conflict.hasConflict
    );
    if (agentsWithConflicts.length === 0) return;

    setRegeneratingAll(true);
    try {
      const payload = {
        items: agentsWithConflicts.map(([agentKey, conflict]) => {
          const agentInfo = initialData.agent_info[agentKey] as any;
          return {
            agent_id: agentInfo?.agent_id,
            name: conflict.renamedName || agentInfo?.name || "",
            display_name: conflict.renamedDisplayName || agentInfo?.display_name || "",
            task_description: agentInfo?.business_description || agentInfo?.description || "",
            language: "zh",
          };
        }),
      };

      const result = await regenerateAgentNameBatch(payload);

      if (!result.success || !Array.isArray(result.data)) {
        message.error(result.message || t("market.install.error.nameRegenerationFailed", "Failed to regenerate name"));
        return;
      }

      const regenerated = result.data as Array<{ name?: string; display_name?: string }>;

      // Update conflicts state with regenerated names
      setAgentNameConflicts((prev) => {
        const next = { ...prev };
        agentsWithConflicts.forEach(([agentKey, conflict], idx) => {
          const agentInfo = initialData.agent_info[agentKey] as any;
          const data = regenerated[idx] || {};
          next[agentKey] = {
            ...next[agentKey],
            renamedName: data.name || conflict.renamedName || agentInfo?.name || "",
            renamedDisplayName:
              data.display_name || conflict.renamedDisplayName || agentInfo?.display_name || "",
          };
        });
        agentNameConflictsRef.current = next;
        return next;
      });

      // Re-check conflicts for all regenerated agents
      const checkPromises = agentsWithConflicts.map(async ([agentKey, conflict], idx) => {
        const data = regenerated[idx] || {};
        const newName = data.name || conflict.renamedName || "";
        const newDisplayName = data.display_name || conflict.renamedDisplayName || "";
        return checkSingleAgentConflict(agentKey, newName, newDisplayName);
      });

      const checkResults = await Promise.all(checkPromises);
      const allResolved = checkResults.every((hasConflict) => !hasConflict);

      if (allResolved) {
        message.success(t("market.install.success.nameRegeneratedAndResolved", "Agent names regenerated successfully and all conflicts resolved"));
      } else {
        message.success(t("market.install.success.nameRegenerated", "Agent name regenerated successfully"));
      }
    } catch (error) {
      log.error("Failed to regenerate agent names:", error);
      message.error(t("market.install.error.nameRegenerationFailed", "Failed to regenerate name"));
    } finally {
      setRegeneratingAll(false);
    }
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

  const loadAvailableTools = async () => {
    setLoadingTools(true);
    try {
      const result = await fetchTools();
      if (result.success) {
        setAvailableTools(result.data || []);
      } else {
        log.warn("Skip tool availability check due to fetch failure");
        setAvailableTools([]);
      }
    } catch (error) {
      log.error("Failed to load available tools:", error);
      setAvailableTools([]);
    } finally {
      setLoadingTools(false);
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

  // Detect missing tools in imported agents compared to available tools
  const computeMissingTools = () => {
    if (!initialData?.agent_info) {
      setMissingTools([]);
      return;
    }

    const availableNameSet = new Set<string>();
    availableTools.forEach((tool) => {
      if (tool.name) {
        availableNameSet.add(tool.name.toLowerCase());
      }
      if (tool.origin_name) {
        availableNameSet.add(tool.origin_name.toLowerCase());
      }
    });

    const missingMap: Record<string, { name: string; source?: string; usage?: string; agents: Set<string> }> = {};

    Object.entries(initialData.agent_info).forEach(([agentKey, agentInfo]) => {
      const agentDisplayName = (agentInfo as any)?.display_name || (agentInfo as any)?.name || `${t("market.install.agent.defaultName", "Agent")} ${agentKey}`;
      if (Array.isArray((agentInfo as any)?.tools)) {
        (agentInfo as any).tools.forEach((tool: any) => {
          // Skip MCP tools as they will be handled in the MCP server installation step
          const toolSource = (tool?.source || "").toLowerCase();
          if (toolSource === "mcp") {
            return;
          }

          const rawName = tool?.name || tool?.origin_name || tool?.class_name;
          const name = typeof rawName === "string" ? rawName.trim() : "";
          if (!name) return;
          const key = name.toLowerCase();
          if (availableNameSet.has(key)) return;

          if (!missingMap[key]) {
            missingMap[key] = {
              name,
              source: tool?.source,
              usage: tool?.usage,
              agents: new Set<string>(),
            };
          }
          missingMap[key].agents.add(agentDisplayName);
        });
      }
    });

    const missingList = Object.values(missingMap).map((item) => ({
      name: item.name,
      source: item.source,
      usage: item.usage,
      agents: Array.from(item.agents),
    }));

    setMissingTools(missingList);
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
    const currentStepKey = steps[currentStep]?.key;

    if (currentStepKey === "rename") {
      // no mandatory name check
    } else if (currentStepKey === "model") {
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
    } else if (currentStepKey === "config") {
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
    // Check for potential issues that could make the agent unusable
    const issues: string[] = [];

    // Check for unresolved agent name conflicts
    const unresolvedConflicts = Object.values(agentNameConflicts).filter(conflict => conflict.hasConflict);
    if (unresolvedConflicts.length > 0) {
      issues.push(t("market.install.warning.nameConflict", "Unresolved name conflicts exist"));
    }

    // Check for uninstalled MCP servers
    const uninstalledMcpServers = mcpServers.filter(mcp => !mcp.isInstalled);
    if (uninstalledMcpServers.length > 0) {
      const serverNames = uninstalledMcpServers.map(mcp => mcp.mcp_server_name);
      issues.push(`${t("market.install.warning.mcpNotInstalled", "Uninstalled MCP services exist")} : ${serverNames.join("、")}`);
    }

    // If there are issues, show confirmation dialog
      if (issues.length > 0) {
      Modal.confirm({
        width: 460,
        icon: null,
        title: (
          <div className="flex items-center gap-2 ml-3">
            <AlertTriangle className="text-yellow-600" size={18} />
            <span className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {t("market.install.warning.title", "Agent May Be Unusable")}
            </span>
          </div>
        ),
        content: (
          // Use full width inside modal and rely on modal width for overall sizing
          <div className="w-full space-y-4">
            {/* Slight right indent for warning and question */}
            <div className="ml-3">
              {/* Warning header - similar to rename step */}
              <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 space-y-3 w-full">
              <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
                {t("market.install.warning.description", "The following issues may make the agent unusable:")}
              </p>
              <div className="space-y-2">
                <ul className="list-disc list-inside text-sm text-gray-700 dark:text-gray-300 space-y-1">
                  {issues.map((issue, index) => (
                    <li key={index}>{issue}</li>
                  ))}
                </ul>
              </div>
              </div>

              {/* Question */}
              <p className="text-sm text-gray-700 dark:text-gray-300 mt-2 ml-1">
                {t("market.install.warning.question", "Do you want to continue with the installation anyway?")}
              </p>
            </div>
          </div>
        ),
        okText: t("market.install.warning.continue", "Continue Anyway"),
        cancelText: t("market.install.warning.goBack", "Go Back to Configure"),
        cancelButtonProps: {
          type: "primary",
        },
        okButtonProps: {
          type: "default",
        },
        onOk: async () => {
          await performImport();
        },
        onCancel: () => {
          // Go back to the appropriate step
          if (unresolvedConflicts.length > 0) {
            setCurrentStep(steps.findIndex(step => step.key === "rename"));
          } else if (uninstalledMcpServers.length > 0) {
            setCurrentStep(steps.findIndex(step => step.key === "mcp"));
          }
        },
      });
      return;
    }

    // No issues found, proceed with import
    await performImport();
  };

  const performImport = async () => {
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
        // Agents are automatically marked as NEW in the database during creation/import
        queryClient.invalidateQueries({ queryKey: ["agents"] });
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

    // Preserve business logic model fields from initial data (passed from market)
    const preservedBusinessLogicModelId = initialData.business_logic_model_id;
    const preservedBusinessLogicModelName = initialData.business_logic_model_name;

    // Update all agents' name/display_name if renamed
    Object.entries(agentNameConflicts).forEach(([agentKey, conflict]) => {
      if (agentJson.agent_info[agentKey]) {
        if (conflict.renamedName) {
          agentJson.agent_info[agentKey].name = conflict.renamedName;
        }
        if (conflict.renamedDisplayName) {
          agentJson.agent_info[agentKey].display_name = conflict.renamedDisplayName;
        }
      }
    });

    // Update model information based on selection mode
    if (modelSelectionMode === "unified") {
      // Unified mode: apply selected model to all agents
      Object.entries(agentJson.agent_info).forEach(([agentKey, agentInfo]: [string, any]) => {
        agentInfo.model_id = selectedModelId;
        agentInfo.model_name = selectedModelName;
      });
    } else {
      // Individual mode: apply models to all agents
      Object.entries(agentJson.agent_info).forEach(([agentKey, agentInfo]: [string, any]) => {
        const modelSelection = selectedModelsByAgent[agentKey];
        if (modelSelection && modelSelection.modelId && modelSelection.modelName) {
          agentInfo.model_id = modelSelection.modelId;
          agentInfo.model_name = modelSelection.modelName;
        }
      });
    }

    // Apply business logic model fields to all agents
    Object.values(agentJson.agent_info).forEach((agentInfo: any) => {
      agentInfo.business_logic_model_id = preservedBusinessLogicModelId ?? null;
      agentInfo.business_logic_model_name = preservedBusinessLogicModelName ?? null;
    });

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
    setAgentNameConflicts({});
    agentNameConflictsRef.current = {};
    setCheckingName(false);
    setRegeneratingAll(false);
    setSuccessfullyRenamedAgents(new Set());
    if (nameCheckTimerRef.current) {
      clearTimeout(nameCheckTimerRef.current);
      nameCheckTimerRef.current = null;
    }
    onCancel();
  };

  // Filter only required steps for navigation
  // Show rename step if name conflict check is complete and there are any agents that had conflicts
  // (even if all conflicts are now resolved, we still want to show the step so users can see the success state)
  const hasAnyAgentsWithConflicts = !checkingName && (
    // Check if any agent has a current conflict
    Object.values(agentNameConflicts).some(conflict => conflict.hasConflict) ||
    // OR if any agent was successfully renamed (meaning it had a conflict that was resolved)
    successfullyRenamedAgents.size > 0
  );
  const hasMissingTools = !loadingTools && missingTools.length > 0;
  // Tools check should be the first step when there are missing tools
  const steps = [
    hasMissingTools && {
      key: "tools",
      title: t("market.install.step.missingTools", "Missing Tools"),
    },
    hasAnyAgentsWithConflicts && {
      key: "rename",
      title: t("market.install.step.rename", "Rename Agent"),
    },
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
    // Disable buttons while checking name conflict
    if (checkingName) {
      return false;
    }

    const currentStepKey = steps[currentStep]?.key;

    if (currentStepKey === "rename") {
      return true;
    } else if (currentStepKey === "tools") {
      return true;
    } else if (currentStepKey === "model") {
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
    // Show loading state while checking name conflict
    if (checkingName) {
      return (
        <div className="flex items-center justify-center py-12">
          <Spin size="large" />
          <span className="ml-4 text-gray-600 dark:text-gray-400">
            {t("market.install.checkingName", "Checking agent name...")}
          </span>
        </div>
      );
    }

    const currentStepKey = steps[currentStep]?.key;

    if (currentStepKey === "rename") {
      // Get all agents that had conflicts (including resolved ones)
      // Show all agents in agentNameConflicts - they either have conflicts or were successfully renamed
      const allAgentsWithConflicts = Object.entries(agentNameConflicts)
        .filter(([agentKey, conflict]) => {
          // Show agent if:
          // 1. It currently has a conflict, OR
          // 2. It was successfully renamed (in successfullyRenamedAgents), OR
          // 3. It's in agentNameConflicts (meaning it was checked and had a conflict at some point)
          // We show all agents in agentNameConflicts to keep the UI consistent
          return true; // Show all agents that were checked
        })
        .sort(([keyA], [keyB]) => {
          // Main agent first
          const mainAgentId = String(initialData?.agent_id);
          if (keyA === mainAgentId) return -1;
          if (keyB === mainAgentId) return 1;
          return 0;
        });

      // Get agents that still have conflicts
      const agentsWithConflicts = allAgentsWithConflicts.filter(
        ([, conflict]) => conflict.hasConflict
      );

      // If no agents had conflicts at all, do not show rename step content
      if (allAgentsWithConflicts.length === 0) {
        return null;
      }

      // Check if all conflicts are resolved
      const allConflictsResolved =
        agentsWithConflicts.length === 0 && allAgentsWithConflicts.length > 0;
      const hasResolvedAgents = allAgentsWithConflicts.some(
        ([agentKey]) => successfullyRenamedAgents.has(agentKey)
      );

      return (
        <div className="space-y-6">
          {allConflictsResolved ? (
            <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 space-y-2">
              <div className="flex items-center gap-2">
                <CircleCheck className="text-green-600 dark:text-green-400 text-lg" size={16} />
                <p className="text-sm font-semibold text-green-800 dark:text-green-200">
                  {t(
                    "market.install.rename.success",
                    "All agent name conflicts have been resolved. You can proceed to the next step."
                  )}
                </p>
              </div>
            </div>
          ) : (
            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 space-y-2">
              {hasResolvedAgents && (
                <div className="mb-2 pb-2 border-b border-yellow-300 dark:border-yellow-700">
                  <div className="flex items-center gap-2">
                    <CircleCheck className="text-green-600 dark:text-green-400 text-sm" size={16} />
                    <p className="text-xs text-green-700 dark:text-green-300">
                      {t(
                        "market.install.rename.partialSuccess",
                        "Some agents have been successfully renamed."
                      )}
                    </p>
                  </div>
                </div>
              )}
              <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
                {t(
                  "market.install.rename.warning",
                  "The agent name or display name conflicts with existing agents. Please rename to proceed."
                )}
              </p>
              <p className="text-xs text-yellow-800 dark:text-yellow-200">
                {t(
                  "market.install.rename.oneClickDesc",
                  "You can manually edit the names, or click one-click rename to let the selected model regenerate names for all conflicted agents."
                )}
              </p>
              <p className="text-xs text-yellow-800 dark:text-yellow-200">
                {t(
                  "market.install.rename.note",
                  "Note: If you proceed without renaming, the agent will be created but marked as unavailable due to name conflicts. You can rename it later in the agent list."
                )}
              </p>
              <Button
                type="primary"
                onClick={handleRegenerateAll}
                loading={regeneratingAll}
                disabled={regeneratingAll}
              >
                {t("market.install.rename.oneClick", "One-click Rename")}
              </Button>
            </div>
          )}

          <div className="space-y-6">
            {allAgentsWithConflicts.map(([agentKey, conflict]) => {
              const agentInfo = initialData?.agent_info?.[agentKey] as any;
              const agentDisplayName =
                agentInfo?.display_name ||
                agentInfo?.name ||
                `${t("market.install.agent.defaultName", "Agent")} ${agentKey}`;
              const isMainAgent = agentKey === String(initialData?.agent_id);
              const originalName = agentInfo?.name || "";
              const originalDisplayName = agentInfo?.display_name || "";

              return (
                <div
                  key={agentKey}
                  className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-4"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <h4 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                      {isMainAgent && (
                        <span className="text-purple-600 dark:text-purple-400 mr-2">
                          {t("market.install.agent.main", "Main")}
                        </span>
                      )}
                      {agentDisplayName}
                    </h4>
                  </div>

                  {successfullyRenamedAgents.has(agentKey) ? (
                    <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded p-2 mb-3">
                      <div className="flex items-center gap-2">
                        <CircleCheck className="text-green-600 dark:text-green-400 text-sm" size={16} />
                        <p className="text-xs text-green-700 dark:text-green-300">
                          {t(
                            "market.install.rename.agentResolved",
                            "This agent's name conflict has been resolved."
                          )}
                        </p>
                      </div>
                    </div>
                  ) : (
                    conflict.hasConflict &&
                    conflict.conflictAgents.length > 0 && (
                      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-2 mb-3">
                        <p className="text-xs text-red-700 dark:text-red-300 mb-1">
                          {t(
                            "market.install.rename.conflictAgents",
                            "Conflicting agents:"
                          )}
                        </p>
                        <ul className="list-disc list-inside text-xs text-red-700 dark:text-red-300">
                          {conflict.conflictAgents.map(
                            (agent: { name?: string; display_name?: string }, idx: number) => (
                              <li key={idx}>
                                {[agent.name, agent.display_name]
                                  .filter(Boolean)
                                  .join(" / ")}
                              </li>
                            )
                          )}
                        </ul>
                      </div>
                    )
                  )}

                  <div>
                    <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 block">
                      {t("market.install.rename.name", "Agent Name")}
                    </label>
                    <Input
                      value={conflict.renamedName}
                      onChange={(e) => {
                        const newName = e.target.value;
                        setAgentNameConflicts((prev) => {
                          const updated = {
                            ...prev,
                            [agentKey]: {
                              ...prev[agentKey],
                              renamedName: newName,
                            },
                          };

                          // Clear existing timer
                          if (nameCheckTimerRef.current) {
                            clearTimeout(nameCheckTimerRef.current);
                          }

                          // Set new timer for debounced check (500ms delay)
                          nameCheckTimerRef.current = setTimeout(() => {
                            // Read latest value from ref when timer fires
                            const currentConflict =
                              agentNameConflictsRef.current[agentKey];
                            if (currentConflict) {
                              checkSingleAgentConflict(
                                agentKey,
                                currentConflict.renamedName,
                                currentConflict.renamedDisplayName
                              );
                            }
                          }, 500);

                          agentNameConflictsRef.current = updated;
                          return updated;
                        });
                      }}
                      placeholder={originalName}
                      size="large"
                      disabled={regeneratingAll}
                    />
                  </div>

                  <div>
                    <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 block">
                      {t("market.install.rename.displayName", "Display Name")}
                    </label>
                    <Input
                      value={conflict.renamedDisplayName}
                      onChange={(e) => {
                        const newDisplayName = e.target.value;
                        setAgentNameConflicts((prev) => {
                          const updated = {
                            ...prev,
                            [agentKey]: {
                              ...prev[agentKey],
                              renamedDisplayName: newDisplayName,
                            },
                          };

                          // Clear existing timer
                          if (nameCheckTimerRef.current) {
                            clearTimeout(nameCheckTimerRef.current);
                          }

                          // Set new timer for debounced check (500ms delay)
                          nameCheckTimerRef.current = setTimeout(() => {
                            // Read latest value from ref when timer fires
                            const currentConflict =
                              agentNameConflictsRef.current[agentKey];
                            if (currentConflict) {
                              checkSingleAgentConflict(
                                agentKey,
                                currentConflict.renamedName,
                                currentConflict.renamedDisplayName
                              );
                            }
                          }, 500);

                          agentNameConflictsRef.current = updated;
                          return updated;
                        });
                      }}
                      placeholder={originalDisplayName}
                      size="large"
                      disabled={regeneratingAll}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    } else if (currentStepKey === "tools") {
      return (
        <div className="space-y-4">
          {/* Top-level warning, keep same yellow style as rename step */}
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 space-y-2">
            <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
              {t(
                "market.install.tools.missingDescTitle",
                "The imported agent uses tools that do not exist in this system"
              )}
            </p>
            <p className="text-xs text-yellow-800 dark:text-yellow-200">
              {t(
                "market.install.tools.missingDescBody",
                "Please review the missing tools below and install or configure them first. If you continue without fixing them, the agent may not work correctly or some capabilities may be unavailable."
              )}
            </p>
          </div>

          {loadingTools ? (
            <div className="flex items-center justify-center py-8">
              <Spin />
              <span className="ml-3 text-gray-600 dark:text-gray-300">
                {t("market.install.tools.loading", "Loading tools...")}
              </span>
            </div>
          ) : (
            <div className="space-y-3">
              {missingTools.map((tool, idx) => (
                <div
                  key={`${tool.name}-${idx}`}
                  className="border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 rounded-lg p-4"
                >
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <Wrench className="text-red-500" size={18} />
                      <span className="font-medium text-gray-900 dark:text-gray-100">
                        {tool.name}
                      </span>
                    </div>
                    {tool.source && (
                      <Tag color="gold" className="text-xs">
                        {t("market.install.tools.source", "Source")}:{" "}
                        {tool.source}
                      </Tag>
                    )}
                  </div>
                  {tool.usage && (
                    <p className="text-xs text-gray-700 dark:text-gray-300 mb-2">
                      {t("market.install.tools.usage", "Usage")}: {tool.usage}
                    </p>
                  )}
                  {tool.agents && tool.agents.length > 0 && (
                    <p className="text-xs text-gray-600 dark:text-gray-400">
                      {t("market.install.tools.usedBy", "Used by")}:{" "}
                      {tool.agents.join(", ")}
                    </p>
                  )}
                  <p className="text-xs text-amber-700 dark:text-amber-200 mt-2">
                    {t(
                      "market.install.tools.missingHint",
                      "If you continue without installing or configuring this tool, the agent may lose part of its capabilities or fail when calling this tool."
                    )}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    } else if (currentStepKey === "model") {
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
      // Group config fields by agent first, then by tool within each agent
      const groupedFields = configFields.reduce((acc, field) => {
        if (!acc[field.agentKey]) {
          acc[field.agentKey] = {
            agentDisplayName: field.agentDisplayName,
            tools: {} as Record<string, { toolName: string; fields: ConfigField[] }>,
            basicFields: [] as ConfigField[]
          };
        }

        // Parse fieldPath to determine if it's a tool parameter or basic field
        const toolMatch = field.fieldPath.match(/^tools\[(\d+)\]\.params\.(.+)$/);

        if (toolMatch) {
          // It's a tool parameter
          const toolIndex = parseInt(toolMatch[1]);
          const toolKey = `tool_${toolIndex}`;

          // Get tool info from agent data
          const agentInfo = initialData?.agent_info?.[field.agentKey];
          const tool = agentInfo?.tools?.[toolIndex];
          const toolName = tool?.name || tool?.class_name || `Tool ${toolIndex}`;

          if (!acc[field.agentKey].tools[toolKey]) {
            acc[field.agentKey].tools[toolKey] = {
              toolName,
              fields: []
            };
          }
          acc[field.agentKey].tools[toolKey].fields.push(field);
        } else {
          // It's a basic field
          acc[field.agentKey].basicFields.push(field);
        }

        return acc;
      }, {} as Record<string, {
        agentDisplayName: string;
        tools: Record<string, { toolName: string; fields: ConfigField[] }>;
        basicFields: ConfigField[];
      }>);

      return (
        <div className="space-y-4">
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            {t("market.install.config.description", "Please configure the following required fields for this agent and its sub-agents.")}
          </p>

          {Object.keys(groupedFields).length > 0 ? (
            <div className="space-y-6">
              {Object.entries(groupedFields)
                .sort(([keyA], [keyB]) => {
                  // Main agent first
                  const mainAgentId = String(initialData?.agent_id);
                  if (keyA === mainAgentId) return -1;
                  if (keyB === mainAgentId) return 1;
                  return 0;
                })
                .map(([agentKey, agentGroup]) => (
                <div
                  key={agentKey}
                  className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-4"
                >
                  {/* Agent Header */}
                  <div className="flex items-center gap-2 mb-2">
                    <h4 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                      {agentKey === String(initialData?.agent_id) && (
                        <span className="text-purple-600 dark:text-purple-400 mr-2">
                          {t("market.install.agent.main", "Main")}
                        </span>
                      )}
                      {agentGroup.agentDisplayName}
                    </h4>
                  </div>

                  {/* Basic Fields */}
                  {agentGroup.basicFields.length > 0 && (
                    <>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                          {t("market.install.config.basicFields", "Basic Configuration")}
                        </span>
                      </div>
                      <div className="space-y-3 ml-4">
                        {agentGroup.basicFields.map((field) => {
                          const paramLabel = field.fieldLabel.replace(`${agentGroup.agentDisplayName} - `, "");
                          return (
                            <div key={field.valueKey}>
                              <div className="flex items-center gap-2 mb-2">
                                <span className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                                  {paramLabel}:
                                </span>
                                <Input
                                  value={configValues[field.valueKey] || ""}
                                  onChange={(e) => {
                                    setConfigValues(prev => ({
                                      ...prev,
                                      [field.valueKey]: e.target.value,
                                    }));
                                  }}
                                  placeholder={t("market.install.config.placeholderWithParam", { param: paramLabel })}
                                  size="middle"
                                  style={{ flex: 1 }}
                                  className={needsConfig(field.currentValue) ? "bg-gray-50 dark:bg-gray-800" : ""}
                                />
                              </div>
                              {/* Show hint with clickable links if available */}
                              {field.promptHint && (
                                <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 max-w-md">
                                  <span className="text-gray-600 dark:text-gray-400 inline-flex flex-wrap items-center gap-1">
                                    {parseMarkdownLinks(field.promptHint)}
                                  </span>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </>
                  )}

                  {/* Tools */}
                  {Object.entries(agentGroup.tools).map(([toolKey, toolGroup]) => (
                    <div key={toolKey} className="space-y-3">
                      {/* Tool Header */}
                      <div className="flex items-center gap-2">
                        <Wrench className="h-4 w-4 text-blue-500" />
                        <span className="text-base font-semibold text-gray-900 dark:text-gray-100">
                          {toolGroup.toolName}
                        </span>
                      </div>

                      {/* Tool Parameters */}
                      <div className="space-y-3 ml-6">
                        {toolGroup.fields.map((field) => {
                          const toolMatch = field.fieldPath.match(/^tools\[\d+\]\.params\.(.+)$/);
                          const paramKey = toolMatch ? toolMatch[1] : field.fieldPath;
                          const paramLabel = paramKey.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

                          return (
                            <div key={field.valueKey}>
                              <div className="flex items-center gap-2 mb-2">
                                <span className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                                  {paramLabel}:
                                </span>
                                <Input
                                  value={configValues[field.valueKey] || ""}
                                  onChange={(e) => {
                                    setConfigValues(prev => ({
                                      ...prev,
                                      [field.valueKey]: e.target.value,
                                    }));
                                  }}
                                  placeholder={t("market.install.config.placeholderWithParam", { param: paramLabel })}
                                  size="middle"
                                  style={{ flex: 1 }}
                                  className={needsConfig(field.currentValue) ? "bg-gray-50 dark:bg-gray-800" : ""}
                                />
                              </div>
                              {/* Show hint with clickable links if available */}
                              {field.promptHint && (
                                <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 max-w-md">
                                  <span className="text-gray-600 dark:text-gray-400 inline-flex flex-wrap items-center gap-1">
                                    {parseMarkdownLinks(field.promptHint)}
                                  </span>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
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
                        <Tag
                          icon={<CircleCheck size={14} />}
                          color="success"
                          className="inline-flex items-center gap-1 text-xs"
                        >
                          {t("market.install.mcp.installed", "Installed")}
                        </Tag>
                      ) : (
                        <Tag
                          icon={<CircleX size={14} />}
                          color="default"
                          className="inline-flex items-center gap-1 text-xs"
                        >
                          {t("market.install.mcp.notInstalled", "Not Installed")}
                        </Tag>
                      )}
                    </div>

                    {!mcp.isInstalled && (
                      <Button
                        type="primary"
                        size="middle"
                        icon={<Plus size={16} />}
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
          <Download size={20} />
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
                icon={<Download size={16} />}
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

        <div className="min-h-[300px] max-h-[70vh] overflow-y-auto pr-1">
          {renderStepContent()}
        </div>
      </div>
    </Modal>
  );
}

