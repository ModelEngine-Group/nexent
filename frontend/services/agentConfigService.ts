import { API_ENDPOINTS } from "./api";

import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { getAuthHeaders } from "@/lib/auth";
import { convertParamType } from "@/lib/utils";
import log from "@/lib/logger";

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
 * @returns list of agents with basic info (id, name, description, is_available)
 */
export const fetchAgentList = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.list, {
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
      is_available: agent.is_available,
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
export const updateAgent = async (
  agentId: number,
  name?: string,
  description?: string,
  modelName?: string,
  maxSteps?: number,
  provideRunSummary?: boolean,
  enabled?: boolean,
  businessDescription?: string,
  dutyPrompt?: string,
  constraintPrompt?: string,
  fewShotsPrompt?: string,
  displayName?: string,
  modelId?: number
) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.update, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        agent_id: agentId,
        name: name,
        description: description,
        display_name: displayName,
        model_name: modelName,
        model_id: modelId,
        max_steps: maxSteps,
        provide_run_summary: provideRunSummary,
        enabled: enabled,
        business_description: businessDescription,
        duty_prompt: dutyPrompt,
        constraint_prompt: constraintPrompt,
        few_shots_prompt: fewShotsPrompt,
      }),
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
 * @returns delete result
 */
export const deleteAgent = async (agentId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.delete, {
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
export const importAgent = async (agentInfo: any) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.import, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        agent_info: agentInfo,
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
 * search agent info by agent id
 * @param agentId agent id
 * @returns agent detail info
 */
export const searchAgentInfo = async (agentId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.searchInfo, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(agentId),
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
      model: data.model_name,
      model_id: data.model_id,
      max_step: data.max_steps,
      duty_prompt: data.duty_prompt,
      constraint_prompt: data.constraint_prompt,
      few_shots_prompt: data.few_shots_prompt,
      business_description: data.business_description,
      provide_run_summary: data.provide_run_summary,
      enabled: data.enabled,
      is_available: data.is_available,
      sub_agent_id_list: data.sub_agent_id_list || [], // Add sub_agent_id_list
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
                  }))
                : [],
            };
          })
        : [],
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
      is_available: agent.is_available,
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
 * add related agent relationship
 * @param parentAgentId parent agent id
 * @param childAgentId child agent id
 * @returns success status
 */
export const addRelatedAgent = async (
  parentAgentId: number,
  childAgentId: number
) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.relatedAgent, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        parent_agent_id: parentAgentId,
        child_agent_id: childAgentId,
      }),
    });

    const data = await response.json();

    if (response.ok) {
      return {
        success: true,
        data: data,
        message: data[0] || "Successfully added related Agent",
        status: response.status,
      };
    } else {
      const errorMessage =
        data.detail || data[0] || `Failed to add related Agent: ${response.statusText}`;
      return {
        success: false,
        data: null,
        message: errorMessage,
        status: response.status,
      };
    }
  } catch (error) {
    log.error("Failed to add related Agent:", error);
    return {
      success: false,
      data: null,
      message: "Failed to add related Agent, please try again later",
      status: 500, // or a custom error code
    };
  }
};

/**
 * delete related agent relationship
 * @param parentAgentId parent agent id
 * @param childAgentId child agent id
 * @returns success status
 */
export const deleteRelatedAgent = async (
  parentAgentId: number,
  childAgentId: number
) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.deleteRelatedAgent, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        parent_agent_id: parentAgentId,
        child_agent_id: childAgentId,
      }),
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
    log.error("Failed to delete related Agent:", error);
    return {
      success: false,
      data: null,
      message: "Failed to delete related Agent, please try again later",
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
