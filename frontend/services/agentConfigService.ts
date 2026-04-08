import { API_ENDPOINTS } from "./api";

import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { getAuthHeaders } from "@/lib/auth";
import { convertParamType } from "@/lib/utils";
import log from "@/lib/logger";
import yaml from "js-yaml";

/**
 * Parse tool inputs string to extract parameter information
 * @param inputsString The inputs string from tool data
 * @returns Parsed inputs object with parameter names and descriptions
 */
export const parseToolInputs = (inputsString: string): Record<string, any> => {
  if (!inputsString || typeof inputsString !== "string") {
    return {};
  }

  try {
    return JSON.parse(inputsString);
  } catch (error) {
    try {
      const normalizedString = inputsString
        .replace(/"/g, "`")
        .replace(/'/g, '"')
        .replace(/\bTrue\b/g, "true")
        .replace(/\bFalse\b/g, "false")
        .replace(/\bNone\b/g, "null");
      return JSON.parse(normalizedString);
    } catch (error) {
      log.warn("Failed to parse tool inputs:", inputsString, error);
      return {};
    }
  }
};

/**
 * Extract parameter names from parsed inputs
 * @param parsedInputs Parsed inputs object
 * @returns Array of parameter names
 */
export const extractParameterNames = (
  parsedInputs: Record<string, any>
): string[] => {
  return Object.keys(parsedInputs);
};

/**
 * get tool list from backend
 * @returns converted tool list
 */
export const fetchTools = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.tool.list, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();

    // convert backend Tool format to frontend Tool format
    const formattedTools = data.map((tool: any) => ({
      id: String(tool.tool_id),
      name: tool.name,
      origin_name: tool.origin_name,
      description: tool.description,
      description_zh: tool.description_zh,
      source: tool.source,
      is_available: tool.is_available,
      create_time: tool.create_time,
      usage: tool.usage, // New: handle usage field
      category: tool.category,
      inputs: tool.inputs,
      initParams: tool.params.map((param: any) => {
        return {
          name: param.name,
          type: convertParamType(param.type),
          required: !param.optional,
          value: param.default,
          description: param.description,
          description_zh: param.description_zh,
        };
      }),
    }));

    return {
      success: true,
      data: formattedTools,
      message: "",
    };
  } catch (error) {
    log.error("Error fetching tool list:", error);
    return {
      success: false,
      data: [],
      message: "agentConfig.tools.fetchFailed",
    };
  }
};

/**
 * get agent list from backend (basic info only)
 * @param tenantId optional tenant ID for filtering
 * @returns list of agents with basic info (id, name, description, is_available)
 */
export const fetchAgentList = async (tenantId?: string) => {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.agent.list}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.agent.list;
    const response = await fetch(url, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();

    // convert backend data to frontend format (basic info only)
    const formattedAgents = data.map((agent: any) => ({
      id: String(agent.agent_id),
      name: agent.name,
      display_name: agent.display_name || agent.name,
      description: agent.description,
      author: agent.author,
      model_id: agent.model_id,
      model_name: agent.model_name,
      model_display_name: agent.model_display_name,
      is_available: agent.is_available,
      unavailable_reasons: agent.unavailable_reasons || [],
      group_ids: agent.group_ids || [],
      is_new: agent.is_new || false,
      permission: agent.permission,
      is_published: agent.is_published,
      current_version_no: agent.current_version_no,
    }));

    return {
      success: true,
      data: formattedAgents,
      message: "",
    };
  } catch (error) {
    log.error("Failed to fetch agent list:", error);
    return {
      success: false,
      data: [],
      message: "agentConfig.agents.listFetchFailed",
    };
  }
};

/**
 * Fetch published agent list - gets agents with their current published version info
 * First queries all agents with version_no=0, then retrieves the published version snapshot
 * for each agent that has current_version_no > 0
 * @returns list of published agents with version information
 */
export const fetchPublishedAgentList = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.publishedList, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();

    // Convert backend data to frontend format
    const formattedAgents = data.map((agent: any) => ({
      id: String(agent.agent_id),
      name: agent.name,
      display_name: agent.display_name || agent.name,
      description: agent.description,
      author: agent.author,
      model_id: agent.model_id,
      model_name: agent.model_name,
      model_display_name: agent.model_display_name,
      is_available: agent.is_available,
      unavailable_reasons: agent.unavailable_reasons || [],
      group_ids: agent.group_ids || [],
      is_new: agent.is_new || false,
      permission: agent.permission,
      published_version_no: agent.published_version_no,
    }));

    return {
      success: true,
      data: formattedAgents,
      message: "",
    };
  } catch (error) {
    log.error("Failed to fetch published agent list:", error);
    return {
      success: false,
      data: [],
      message: "agentConfig.agents.publishedListFetchFailed",
    };
  }
};

/**
 * get creating sub agent id
 * @param mainAgentId current main agent id
 * @returns new sub agent id
 */
export const getCreatingSubAgentId = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.getCreatingSubAgentId, {
      method: "GET",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: {
        agentId: data.agent_id,
        name: data.name,
        displayName: data.display_name,
        description: data.description,
        enabledToolIds: data.enable_tool_id_list || [],
        modelName: data.model_name,
        model_id: data.model_id,
        maxSteps: data.max_steps,
        businessDescription: data.business_description,
        dutyPrompt: data.duty_prompt,
        constraintPrompt: data.constraint_prompt,
        fewShotsPrompt: data.few_shots_prompt,
        sub_agent_id_list: data.sub_agent_id_list || [],
      },
      message: "",
    };
  } catch (error) {
    log.error("Failed to get creating sub agent ID:", error);
    return {
      success: false,
      data: null,
      message: "agentConfig.agents.createSubAgentIdFailed",
    };
  }
};

/**
 * update tool config
 * @param toolId tool id
 * @param agentId agent id
 * @param params tool params config
 * @param enable whether enable tool
 * @returns update result
 */
export const updateToolConfig = async (
  toolId: number,
  agentId: number,
  params: Record<string, any>,
  enable: boolean
) => {
  try {
    const response = await fetch(API_ENDPOINTS.tool.update, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        tool_id: toolId,
        agent_id: agentId,
        params: params,
        enabled: enable,
      }),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data,
      message: "Tool configuration updated successfully",
    };
  } catch (error) {
    log.error("Failed to update tool configuration:", error);
    return {
      success: false,
      data: null,
      message: "Failed to update tool configuration, please try again later",
    };
  }
};

/**
 * search tool config
 * @param toolId tool id
 * @param agentId agent id
 * @returns tool config info
 */
export const searchToolConfig = async (toolId: number, agentId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.tool.search, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        tool_id: toolId,
        agent_id: agentId,
      }),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: {
        params: data.params,
        enabled: data.enabled,
      },
      message: "",
    };
  } catch (error) {
    log.error("Failed to search tool configuration:", error);
    return {
      success: false,
      data: null,
      message: "Failed to search tool configuration, please try again later",
    };
  }
};

/**
 * load last tool config
 * @param toolId tool id
 * @returns last tool config info
 */
export const loadLastToolConfig = async (toolId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.tool.loadConfig(toolId), {
      method: "GET",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data.message, // Backend returns config in message field
      message: "",
    };
  } catch (error) {
    log.error("Failed to load last tool configuration:", error);
    return {
      success: false,
      data: null,
      message: "Failed to load last tool configuration, please try again later",
    };
  }
};

/**
 * Update Agent information
 * @param agentId agent id
 * @param name agent name
 * @param description agent description
 * @param modelName model name
 * @param maxSteps maximum steps
 * @param provideRunSummary whether to provide run summary
 * @returns update result
 */
export interface UpdateAgentInfoPayload {
  agent_id?: number;
  name?: string;
  display_name?: string;
  description?: string;
  author?: string;
  duty_prompt?: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;
  group_ids?: number[];
  model_name?: string;
  model_id?: number;
  max_steps?: number;
  provide_run_summary?: boolean;
  enabled?: boolean;
  business_description?: string;
  business_logic_model_name?: string;
  business_logic_model_id?: number;
  enabled_tool_ids?: number[];
  enabled_skill_ids?: number[];
  related_agent_ids?: number[];
  ingroup_permission?: string;
}

export const updateAgentInfo = async (payload: UpdateAgentInfoPayload) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.update, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data,
      message: "Agent updated successfully",
    };
  } catch (error) {
    log.error("Failed to update Agent:", error);
    return {
      success: false,
      data: null,
      message: "Failed to update Agent, please try again later",
    };
  }
};

/**
 * Delete Agent
 * @param agentId agent id
 * @param tenantId optional tenant ID for filtering (uses auth if not provided)
 * @returns delete result
 */
export const deleteAgent = async (agentId: number, tenantId?: string) => {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.agent.delete}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.agent.delete;
    const response = await fetch(url, {
      method: "DELETE",
      headers: getAuthHeaders(),
      body: JSON.stringify({ agent_id: agentId }),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    return {
      success: true,
      message: "Agent deleted successfully",
    };
  } catch (error) {
    log.error("Failed to delete Agent:", error);
    return {
      success: false,
      message: "Failed to delete Agent, please try again later",
    };
  }
};

/**
 * export agent configuration
 * @param agentId agent id to export
 * @returns export result
 */
export const exportAgent = async (agentId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.export, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ agent_id: agentId }),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();

    if (data.code === 0) {
      return {
        success: true,
        data: data.data,
        message: data.message,
      };
    } else {
      return {
        success: false,
        data: null,
        message: data.message || "Export failed",
      };
    }
  } catch (error) {
    log.error("Failed to export Agent:", error);
    return {
      success: false,
      data: null,
      message: "Export failed, please try again later",
    };
  }
};

/**
 * import agent configuration
 * @param agentId main agent id
 * @param agentInfo agent configuration data
 * @returns import result
 */
export const importAgent = async (
  agentInfo: any,
  options?: { forceImport?: boolean }
) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.import, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        agent_info: agentInfo,
        force_import: options?.forceImport ?? false,
      }),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data,
      message: "Agent imported successfully",
    };
  } catch (error) {
    log.error("Failed to import Agent:", error);
    return {
      success: false,
      data: null,
      message: "Failed to import Agent, please try again later",
    };
  }
};

/**
 * Clear NEW mark for an agent
 */
export const clearAgentNewMark = async (agentId: string | number) => {
  try {
    const url = typeof API_ENDPOINTS.agent.clearNew === 'function'
      ? API_ENDPOINTS.agent.clearNew(agentId)
      : `${API_ENDPOINTS.agent.clearNew}/${agentId}`;
    const response = await fetch(url, {
      method: "PUT",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data,
      message: "Agent NEW mark cleared successfully",
    };
  } catch (error) {
    log.error("Failed to clear agent NEW mark:", error);
    return {
      success: false,
      data: null,
      message: "Failed to clear agent NEW mark",
    };
  }
};

/**
 * check agent name/display_name duplication
 * @param payload name/displayName to check
 */
export const checkAgentNameConflictBatch = async (payload: {
  items: Array<{ name: string; display_name?: string; agent_id?: number }>;
}) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.checkNameBatch, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data,
      message: "",
    };
  } catch (error) {
    log.error("Failed to check agent name conflict batch:", error);
    return {
      success: false,
      data: null,
      message: "agentConfig.agents.checkNameFailed",
    };
  }
};

export const regenerateAgentNameBatch = async (payload: {
  items: Array<{
    name: string;
    display_name?: string;
    task_description?: string;
    language?: string;
    agent_id?: number;
  }>;
}) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.regenerateNameBatch, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data,
      message: "",
    };
  } catch (error) {
    log.error("Failed to regenerate agent name batch:", error);
    return {
      success: false,
      data: null,
      message: "agentConfig.agents.regenerateNameFailed",
    };
  }
};

/**
 * search agent info by agent id
 * @param agentId agent id
 * @param tenantId optional tenant ID for filtering
 * @param versionNo optional version number (default 0 for current/draft version)
 * @returns agent detail info
 */
export const searchAgentInfo = async (agentId: number, tenantId?: string, versionNo?: number) => {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.agent.searchInfo}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.agent.searchInfo;
    const response = await fetch(url, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        agent_id: agentId,
        version_no: versionNo ?? 0,
      }),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();

    // convert backend data to frontend format
    const formattedAgent = {
      id: data.agent_id,
      name: data.name,
      display_name: data.display_name,
      description: data.description,
      author: data.author,
      model: data.model_name,
      model_id: data.model_id,
      max_step: data.max_steps,
      duty_prompt: data.duty_prompt,
      constraint_prompt: data.constraint_prompt,
      few_shots_prompt: data.few_shots_prompt,
      business_description: data.business_description,
      business_logic_model_name: data.business_logic_model_name,
      business_logic_model_id: data.business_logic_model_id,
      provide_run_summary: data.provide_run_summary,
      enabled: data.enabled,
      is_available: data.is_available,
      unavailable_reasons: data.unavailable_reasons || [],
      sub_agent_id_list: data.sub_agent_id_list || [], // Add sub_agent_id_list
      group_ids: data.group_ids || [],
      ingroup_permission: data.ingroup_permission || "READ_ONLY",
      tools: data.tools
        ? data.tools.map((tool: any) => {
            const params =
              typeof tool.params === "string"
                ? JSON.parse(tool.params)
                : tool.params;
            return {
              id: String(tool.tool_id),
              name: tool.name,
              description: tool.description,
              description_zh: tool.description_zh,
              source: tool.source,
              is_available: tool.is_available,
              usage: tool.usage, // New: handle usage field
              category: tool.category,
              initParams: Array.isArray(params)
                ? params.map((param: any) => ({
                    name: param.name,
                    type: convertParamType(param.type),
                    required: !param.optional,
                    value: param.default,
                    description: param.description,
                    description_zh: param.description_zh,
                  }))
                : [],
            };
          })
        : [],
      current_version_no: data.current_version_no
    };

    return {
      success: true,
      data: formattedAgent,
      message: "",
    };
  } catch (error) {
    log.error("Failed to get Agent details:", error);
    return {
      success: false,
      data: null,
      message: "agentConfig.agents.detailsFetchFailed",
    };
  }
};

/**
 * fetch all available agents for chat
 * @returns list of available agents with agent_id, name, description, is_available
 */
export const fetchAllAgents = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.list, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();

    // convert backend data to frontend format
    const formattedAgents = data.map((agent: any) => ({
      agent_id: agent.agent_id,
      name: agent.name,
      display_name: agent.display_name || agent.name,
      description: agent.description,
      author: agent.author,
      is_available: agent.is_available,
      is_new: agent.is_new || false,
    }));

    return {
      success: true,
      data: formattedAgents,
      message: "",
    };
  } catch (error) {
    log.error("Failed to get all Agent list:", error);
    return {
      success: false,
      data: [],
      message: "agentConfig.agents.listFetchFailed",
    };
  }
};

/**
 * Get agent call relationship tree including tools and sub-agents
 * @param agentId agent id
 * @returns agent call relationship tree structure
 */
export const fetchAgentCallRelationship = async (agentId: number) => {
  try {
    const response = await fetch(`${API_ENDPOINTS.agent.callRelationship}/${agentId}`, {
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();

    return {
      success: true,
      data: data,
      message: ''
    };
  } catch (error) {
    log.error('Failed to fetch agent call relationship:', error);
    return {
      success: false,
      data: null,
      message: 'agentConfig.agents.callRelationshipFetchFailed'
    };
  }
};

/**
 * Check if agent field value exists in the current tenant
 * @param fieldValue value to check
 * @param fieldName field name to check
 * @param excludeAgentId optional agent id to exclude from the check
 * @returns check result with status
 */
const checkAgentField = async (
  fieldValue: string,
  fieldName: string,
  excludeAgentId?: number
): Promise<{ status: string; action?: string }> => {
  try {
    // Get all agents in current tenant
    const response = await fetch(API_ENDPOINTS.agent.list, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`request failed: ${response.status}`);
    }
    const data = await response.json();

    // Check if agent field value already exists, excluding the specified agent if provided
    const existingAgent = data.find(
      (agent: any) =>
        agent[fieldName] === fieldValue &&
        (!excludeAgentId || agent.agent_id !== excludeAgentId)
    );

    if (existingAgent) {
      return { status: NAME_CHECK_STATUS.EXISTS_IN_TENANT };
    }
    return { status: NAME_CHECK_STATUS.AVAILABLE };
  } catch (error) {
    return { status: NAME_CHECK_STATUS.CHECK_FAILED };
  }
};

/**
 * Check if agent name exists in the current tenant
 * @param agentName agent name to check
 * @param excludeAgentId optional agent id to exclude from the check
 * @returns check result with status
 */
export const checkAgentName = async (
  agentName: string,
  excludeAgentId?: number
): Promise<{ status: string; action?: string }> => {
  return checkAgentField(agentName, "name", excludeAgentId);
};

/**
 * Check if agent display name exists in the current tenant
 * @param displayName agent display name to check
 * @param excludeAgentId optional agent id to exclude from the check
 * @returns check result with status
 */
export const checkAgentDisplayName = async (
  displayName: string,
  excludeAgentId?: number
): Promise<{ status: string; action?: string }> => {
  return checkAgentField(displayName, "display_name", excludeAgentId);
};

/**
 * Validate tool using /tool/validate endpoint
 * @param name tool name
 * @param source tool source
 * @param usage tool usage URL
 * @param inputs tool inputs
 * @param params tool configuration parameters
 * @returns validation result
 */
export const validateTool = async (
  name: string,
  source: string,
  usage: string,
  inputs: Record<string, any> | null = null,
  params: Record<string, any> | null = null
) => {
  try {
    const requestBody = {
      name: name,
      source: source,
      usage: usage,
      inputs: inputs,
      params: params,
    };

    const response = await fetch(API_ENDPOINTS.tool.validate, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    const data = await response.json();

    // Return the raw backend response directly
    return data;
  } catch (error) {
    log.error("Tool validation failed:", error);
    return {
      valid: false,
      message: "Network error occurred during validation",
      error: error instanceof Error ? error.message : String(error),
    };
  }
};

/**
 * Fetch all available skills
 * @returns list of skills with skill_id, name, description, source, etc.
 */
export const fetchSkills = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.skills.list, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();

    const skills = data.skills || data || [];

    const formattedSkills = skills.map((skill: any) => ({
      skill_id: String(skill.skill_id),
      name: skill.name,
      description: skill.description || "",
      source: skill.source || "custom",
      tags: skill.tags || [],
      content: skill.content || "",
      params: skill.params ?? null,
      tool_ids: Array.isArray(skill.tool_ids) ? skill.tool_ids.map(Number) : [],
      update_time: skill.update_time,
      create_time: skill.create_time,
    }));

    return {
      success: true,
      data: formattedSkills,
      message: "",
    };
  } catch (error) {
    log.error("Error fetching skill list:", error);
    return {
      success: false,
      data: [],
      message: "agentConfig.skills.fetchFailed",
    };
  }
};

/**
 * Fetch skill instances for an agent
 * @param agentId agent ID
 * @param versionNo version number (default 0 for draft)
 * @returns list of skill instances with enabled status
 */
export const fetchSkillInstances = async (
  agentId: number,
  versionNo: number = 0
) => {
  try {
    const url = `${API_ENDPOINTS.skills.instanceList}?agent_id=${agentId}&version_no=${versionNo}`;
    const response = await fetch(url, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();

    const instances = data.instances || data || [];

    const formattedInstances = instances.map((instance: any) => ({
      skill_id: String(instance.skill_id),
      enabled: instance.enabled ?? true,
      skill_name: instance.skill_name,
      skill_description: instance.skill_description,
    }));

    return {
      success: true,
      data: formattedInstances,
      message: "",
    };
  } catch (error) {
    log.error("Error fetching skill instances:", error);
    return {
      success: false,
      data: [],
      message: "agentConfig.skills.instanceFetchFailed",
    };
  }
};

/**
 * Save (create/update) a skill instance for an agent
 * @param skillId skill ID
 * @param agentId agent ID
 * @param enabled whether the skill is enabled
 * @param versionNo version number (default 0 for draft)
 * @returns save result
 */
export const saveSkillInstance = async (
  skillId: number,
  agentId: number,
  enabled: boolean,
  versionNo: number = 0
) => {
  try {
    const requestBody = {
      skill_id: skillId,
      agent_id: agentId,
      enabled: enabled,
      version_no: versionNo,
    };

    const response = await fetch(API_ENDPOINTS.skills.instanceUpdate, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();

    return {
      success: true,
      data: data,
      message: "",
    };
  } catch (error) {
    log.error("Error saving skill instance:", error);
    return {
      success: false,
      data: null,
      message: "agentConfig.skills.saveFailed",
    };
  }
};

/**
 * Create a new skill
 * @param skillData skill data including name, description, source, tags, content
 * @returns created skill
 */
export const createSkill = async (skillData: {
  name: string;
  description?: string;
  source?: string;
  tags?: string[];
  content?: string;
}) => {
  try {
    const requestBody = {
      name: skillData.name,
      description: skillData.description || "",
      source: skillData.source || "custom",
      tags: skillData.tags || [],
      content: skillData.content || "",
    };

    const response = await fetch(API_ENDPOINTS.skills.create, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Request failed: ${response.status}`);
    }

    const data = await response.json();

    return {
      success: true,
      data: data,
      message: "",
    };
  } catch (error) {
    log.error("Error creating skill:", error);
    return {
      success: false,
      data: null,
      message: error instanceof Error ? error.message : "Failed to create skill",
    };
  }
};

/**
 * Update an existing skill
 * @param skillName skill name
 * @param skillData skill data to update
 * @returns updated skill
 */
export const updateSkill = async (
  skillName: string,
  skillData: {
    description?: string;
    source?: string;
    tags?: string[];
    content?: string;
    params?: Record<string, unknown>;
  }
) => {
  try {
    const requestBody: Record<string, any> = {};
    if (skillData.description !== undefined) requestBody.description = skillData.description;
    if (skillData.source !== undefined) requestBody.source = skillData.source;
    if (skillData.tags !== undefined) requestBody.tags = skillData.tags;
    if (skillData.content !== undefined) requestBody.content = skillData.content;
    if (skillData.params !== undefined) requestBody.params = skillData.params;

    const response = await fetch(API_ENDPOINTS.skills.update(skillName), {
      method: "PUT",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Request failed: ${response.status}`);
    }

    const data = await response.json();

    return {
      success: true,
      data: data,
      message: "",
    };
  } catch (error) {
    log.error("Error updating skill:", error);
    return {
      success: false,
      data: null,
      message: error instanceof Error ? error.message : "Failed to update skill",
    };
  }
};

/**
 * Create or update skill from file upload
 * @param skillName skill name (optional for new skill)
 * @param file file content
 * @param isUpdate whether this is an update operation
 * @returns created/updated skill
 */
export const createSkillFromFile = async (
  skillName: string | null,
  file: File | Blob,
  isUpdate: boolean = false
) => {
  try {
    const formData = new FormData();
    formData.append("file", file);
    if (skillName) {
      formData.append("skill_name", skillName);
    }

    const endpoint = isUpdate && skillName
      ? API_ENDPOINTS.skills.updateUpload(skillName)
      : API_ENDPOINTS.skills.upload;

    const method = isUpdate ? "PUT" : "POST";

    // Don't set Content-Type for FormData - browser needs to set multipart/form-data with boundary
    const headers: Record<string, string> = {
      "User-Agent": "AgentFrontEnd/1.0",
    };

    const response = await fetch(endpoint, {
      method: method,
      headers: headers,
      body: formData,
    });

    if (!response.ok) {
      let errorData: any = {};
      try {
        errorData = await response.json();
      } catch {
        // JSON parse failed
      }

      const errorMessage = typeof errorData.detail === 'string'
        ? errorData.detail
        : Array.isArray(errorData.detail)
          ? errorData.detail.map((e: any) => e.msg || JSON.stringify(e)).join('; ')
          : JSON.stringify(errorData.detail);
      throw new Error(errorMessage || `Request failed: ${response.status}`);
    }

    const data = await response.json();

    return {
      success: true,
      data: data,
      message: "",
    };
  } catch (error) {
    log.error("Error creating skill from file:", error);
    return {
      success: false,
      data: null,
      message: error instanceof Error ? error.message : "Failed to create skill from file",
    };
  }
};

/**
 * Search skills by name prefix for autocomplete
 * @param prefix name prefix to search
 * @param allSkills all available skills
 * @returns filtered skills matching the prefix
 */
export const searchSkillsByName = <T extends { name: string }>(
  prefix: string,
  allSkills: T[]
): T[] => {
  if (!prefix || prefix.trim() === "") {
    return [];
  }
  const lowerPrefix = prefix.toLowerCase();
  return allSkills
    .filter((skill) => skill.name.toLowerCase().startsWith(lowerPrefix))
    .slice(0, 10);
};

/**
 * Fetch skill directory structure (files and folders)
 * @param skillName skill name
 * @returns file/folder structure
 */
export interface SkillFileNode {
  name: string;
  type: "file" | "directory";
  children?: SkillFileNode[];
}

export const fetchSkillFiles = async (skillName: string): Promise<SkillFileNode[]> => {
  try {
    const response = await fetch(API_ENDPOINTS.skills.files(skillName), {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();
    return data.files || data || [];
  } catch (error) {
    log.error("Error fetching skill files:", error);
    return [];
  }
};

/**
 * Fetch skill file content
 * @param skillName skill name
 * @param filePath file path relative to skill directory
 * @returns file content
 */
export const getAgentByName = async (agentName: string): Promise<{
  agent_id: number;
  latest_version_no: number | null;
} | null> => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.byName(agentName), {
      method: "GET",
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();
    return {
      agent_id: data.agent_id,
      latest_version_no: data.latest_version_no ?? null,
    };
  } catch (error) {
    log.error("Error fetching agent by name:", error);
    return null;
  }
};

/**
 * Fetch skill file content
 * @param skillName skill name
 * @param filePath file path relative to skill directory
 * @returns file content
 */
export const fetchSkillFileContent = async (skillName: string, filePath: string): Promise<string | null> => {
  try {
    const encodedPath = encodeURIComponent(filePath);
    const response = await fetch(`${API_ENDPOINTS.skills.fileContent(skillName, encodedPath)}`, {
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();
    return data.content || data;
  } catch (error) {
    log.error("Error fetching skill file content:", error);
    return null;
  }
};

/**
 * Delete a specific file within a skill directory
 * @param skillName skill name
 * @param filePath file path relative to skill directory
 * @returns delete result
 */
export const deleteSkillTempFile = async (skillName: string, filePath: string): Promise<boolean> => {
  try {
    const encodedPath = encodeURIComponent(filePath);
    const response = await fetch(`${API_ENDPOINTS.skills.deleteFile(skillName, encodedPath)}`, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      log.warn(`Failed to delete skill temp file: ${response.status}`);
      return false;
    }
    return true;
  } catch (error) {
    log.error("Error deleting skill temp file:", error);
    return false;
  }
};

/**
 * Get skill configuration from config.yaml
 * @param skillName skill name
 * @returns skill config object or null
 */
/**
 * Fetch skill configuration (config.yaml)
 * @param skillName The skill name
 * @returns Parsed config object with temp_filename and progress info
 */
export const fetchSkillConfig = async (skillName: string): Promise<Record<string, unknown> | null> => {
  try {
    const response = await fetch(
      `${API_ENDPOINTS.skills.fileContent(skillName, "config.yaml")}`,
      { headers: getAuthHeaders() }
    );
    if (!response.ok) {
      log.warn(`Failed to fetch skill config: ${response.status}`);
      return null;
    }
    const data = await response.json();
    const yamlContent = data.content;
    if (!yamlContent) return null;

    // Parse YAML string to object using js-yaml
    const parsed = yaml.load(yamlContent) as Record<string, unknown>;
    return parsed || null;
  } catch (error) {
    log.error("Error fetching skill config:", error);
    return null;
  }
};

/**
 * Delete a skill by name
 * @param skillName skill name to delete
 * @returns delete result
 */
export const deleteSkill = async (skillName: string) => {
  try {
    const response = await fetch(API_ENDPOINTS.skills.delete(skillName), {
      method: "DELETE",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Request failed: ${response.status}`);
    }

    return {
      success: true,
      message: "",
    };
  } catch (error) {
    log.error("Error deleting skill:", error);
    return {
      success: false,
      message: error instanceof Error ? error.message : "Failed to delete skill",
    };
  }
};
