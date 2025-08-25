import { Tool } from '@/types/agentAndToolConst';
import { convertParamType } from '@/lib/utils';
import { API_ENDPOINTS } from './api';
import { getAuthHeaders } from '@/lib/auth';


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
      throw new Error(`请求失败: ${response.status}`);
    }
    const data = await response.json();
    
    // convert backend Tool format to frontend Tool format
    const formattedTools = data.map((tool: any) => ({
      id: String(tool.tool_id),
      name: tool.name,
      description: tool.description,
      source: tool.source,
      is_available: tool.is_available,
      create_time: tool.create_time,
      usage: tool.usage, // 新增：处理usage字段
      initParams: tool.params.map((param: any) => {
        return {
          name: param.name,
          type: convertParamType(param.type),
          required: !param.optional,
          value: param.default,
          description: param.description
        };
      })
    }));
    
    return {
      success: true,
      data: formattedTools,
      message: ''
    };
  } catch (error) {
    console.error('获取工具列表出错:', error);
    return {
      success: false,
      data: [],
      message: '获取工具列表失败，请稍后重试'
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
      throw new Error(`请求失败: ${response.status}`);
    }
    const data = await response.json();
    
    // convert backend data to frontend format (basic info only)
    const formattedAgents = data.map((agent: any) => ({
      id: String(agent.agent_id),
      name: agent.name,
      display_name: agent.display_name || agent.name,
      description: agent.description,
      is_available: agent.is_available
    }));
    
    return {
      success: true,
      data: formattedAgents,
      message: ''
    };
  } catch (error) {
    console.error('获取 agent 列表失败:', error);
    return {
      success: false,
      data: [],
      message: '获取 agent 列表失败，请稍后重试'
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
      method: 'GET',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: {
        agentId: data.agent_id,
        enabledToolIds: data.enable_tool_id_list || [],
        modelName: data.model_name,
        maxSteps: data.max_steps,
        businessDescription: data.business_description,
        dutyPrompt: data.duty_prompt,
        constraintPrompt: data.constraint_prompt,
        fewShotsPrompt: data.few_shots_prompt,
        sub_agent_id_list: data.sub_agent_id_list || []
      },
      message: ''
    };
  } catch (error) {
    console.error('获取创建子代理ID失败:', error);
    return {
      success: false,
      data: null,
      message: '获取创建子代理ID失败，请稍后重试'
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
    console.log({"tool_id":toolId, "agent_id":agentId, "params":params, "enabled":enable})

    const response = await fetch(API_ENDPOINTS.tool.update, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        tool_id: toolId,
        agent_id: agentId,
        params: params,
        enabled: enable
      }),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data,
      message: '工具配置更新成功'
    };
  } catch (error) {
    console.error('更新工具配置失败:', error);
    return {
      success: false,
      data: null,
      message: '更新工具配置失败，请稍后重试'
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
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        tool_id: toolId,
        agent_id: agentId
      }),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: {
        params: data.params,
        enabled: data.enabled
      },
      message: ''
    };
  } catch (error) {
    console.error('搜索工具配置失败:', error);
    return {
      success: false,
      data: null,
      message: '搜索工具配置失败，请稍后重试'
    };
  }
};

/**
 * 更新 Agent 信息
 * @param agentId agent id
 * @param name agent 名称
 * @param description agent 描述
 * @param modelName 模型名称
 * @param maxSteps 最大步骤数
 * @param provideRunSummary 是否提供运行摘要
 * @returns 更新结果
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
  displayName?: string
) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.update, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        agent_id: agentId,
        name: name,
        description: description,
        display_name: displayName,
        model_name: modelName,
        max_steps: maxSteps,
        provide_run_summary: provideRunSummary,
        enabled: enabled,
        business_description: businessDescription,
        duty_prompt: dutyPrompt,
        constraint_prompt: constraintPrompt,
        few_shots_prompt: fewShotsPrompt
      }),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data,
      message: 'Agent 更新成功'
    };
  } catch (error) {
    console.error('更新 Agent 失败:', error);
    return {
      success: false,
      data: null,
      message: '更新 Agent 失败，请稍后重试'
    };
  }
};

/**
 * 删除 Agent
 * @param agentId agent id
 * @returns 删除结果
 */
export const deleteAgent = async (agentId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.delete, {
      method: 'DELETE',
      headers: getAuthHeaders(),
      body: JSON.stringify({ agent_id: agentId }),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    return {
      success: true,
      message: 'Agent 删除成功'
    };
  } catch (error) {
    console.error('删除 Agent 失败:', error);
    return {
      success: false,
      message: '删除 Agent 失败，请稍后重试'
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
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ agent_id: agentId }),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    
    if (data.code === 0) {
      return {
        success: true,
        data: data.data,
        message: data.message
      };
    } else {
      return {
        success: false,
        data: null,
        message: data.message || '导出失败'
      };
    }
  } catch (error) {
    console.error('导出 Agent 失败:', error);
    return {
      success: false,
      data: null,
      message: '导出失败，请稍后重试'
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
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ 
        agent_info: agentInfo 
      }),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      data: data,
      message: 'Agent 导入成功'
    };
  } catch (error) {
    console.error('导入 Agent 失败:', error);
    return {
      success: false,
      data: null,
      message: '导入 Agent 失败，请稍后重试'
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
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(agentId),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    
    // convert backend data to frontend format
    const formattedAgent = {
      id: data.agent_id,
      name: data.name,
      display_name: data.display_name,
      description: data.description,
      model: data.model_name,
      max_step: data.max_steps,
      duty_prompt: data.duty_prompt,
      constraint_prompt: data.constraint_prompt,
      few_shots_prompt: data.few_shots_prompt,
      business_description: data.business_description,
      provide_run_summary: data.provide_run_summary,
      enabled: data.enabled,
      is_available: data.is_available,
      sub_agent_id_list: data.sub_agent_id_list || [], // 添加sub_agent_id_list
      tools: data.tools ? data.tools.map((tool: any) => {
        const params = typeof tool.params === 'string' ? JSON.parse(tool.params) : tool.params;
        return {
          id: String(tool.tool_id),
          name: tool.name,
          description: tool.description,
          source: tool.source,
          is_available: tool.is_available,
          usage: tool.usage, // 新增：处理usage字段
          initParams: Array.isArray(params) ? params.map((param: any) => ({
            name: param.name,
            type: convertParamType(param.type),
            required: !param.optional,
            value: param.default,
            description: param.description
          })) : []
        };
      }) : []
    };

    return {
      success: true,
      data: formattedAgent,
      message: ''
    };
  } catch (error) {
    console.error('获取Agent详情失败:', error);
    return {
      success: false,
      data: null,
      message: '获取Agent详情失败，请稍后重试'
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
      throw new Error(`请求失败: ${response.status}`);
    }
    const data = await response.json();
    
    // convert backend data to frontend format
    const formattedAgents = data.map((agent: any) => ({
      agent_id: agent.agent_id,
      name: agent.name,
      display_name: agent.display_name || agent.name,
      description: agent.description,
      is_available: agent.is_available
    }));
    
    return {
      success: true,
      data: formattedAgents,
      message: ''
    };
  } catch (error) {
    console.error('获取所有Agent列表失败:', error);
    return {
      success: false,
      data: [],
      message: '获取Agent列表失败，请稍后重试'
    };
  }
};

/**
 * add related agent relationship
 * @param parentAgentId parent agent id
 * @param childAgentId child agent id
 * @returns success status
 */
export const addRelatedAgent = async (parentAgentId: number, childAgentId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.relatedAgent, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        parent_agent_id: parentAgentId,
        child_agent_id: childAgentId
      }),
    });

    const data = await response.json();

    if (response.ok) {
      return {
        success: true,
        data: data,
        message: data[0] || '添加关联Agent成功',
        status: response.status,
      };
    } else {
      const errorMessage = data.detail || data[0] || `添加关联Agent失败: ${response.statusText}`;
      return {
        success: false,
        data: null,
        message: errorMessage,
        status: response.status,
      };
    }
  } catch (error) {
    console.error('添加关联Agent失败:', error);
    return {
      success: false,
      data: null,
      message: '添加关联Agent失败，请稍后重试',
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
export const deleteRelatedAgent = async (parentAgentId: number, childAgentId: number) => {
  try {
    const response = await fetch(API_ENDPOINTS.agent.deleteRelatedAgent, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        parent_agent_id: parentAgentId,
        child_agent_id: childAgentId
      }),
    });

    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();
    
    return {
      success: true,
      data: data,
      message: ''
    };
  } catch (error) {
    console.error('删除关联Agent失败:', error);
    return {
      success: false,
      data: null,
      message: '删除关联Agent失败，请稍后重试'
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
      throw new Error(`请求失败: ${response.status}`);
    }

    const data = await response.json();

    return {
      success: true,
      data: data,
      message: ''
    };
  } catch (error) {
    console.error('获取Agent调用关系失败:', error);
    return {
      success: false,
      data: null,
      message: '获取Agent调用关系失败，请稍后重试'
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
): Promise<{status: string, action?: string}> => {
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
    const existingAgent = data.find((agent: any) =>
      agent[fieldName] === fieldValue &&
      (!excludeAgentId || agent.agent_id !== excludeAgentId)
    );

    if (existingAgent) {
      return { status: 'exists_in_tenant' };
    }
    return { status: 'available' };
  } catch (error) {
    return { status: 'check_failed' };
  }
};

/**
 * Check if agent name exists in the current tenant
 * @param agentName agent name to check
 * @param excludeAgentId optional agent id to exclude from the check
 * @returns check result with status
 */
export const checkAgentName = async (agentName: string, excludeAgentId?: number): Promise<{status: string, action?: string}> => {
  return checkAgentField(agentName, 'name', excludeAgentId);
};

/**
 * Check if agent display name exists in the current tenant
 * @param displayName agent display name to check
 * @param excludeAgentId optional agent id to exclude from the check
 * @returns check result with status
 */
export const checkAgentDisplayName = async (displayName: string, excludeAgentId?: number): Promise<{status: string, action?: string}> => {
  return checkAgentField(displayName, 'display_name', excludeAgentId);
};
