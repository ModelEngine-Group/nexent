import { API_ENDPOINTS } from './api';
import i18n from 'i18next';

// 翻译函数
const t = (key: string, options?: any): string => {
  return i18n.t(key, options) as string;
};

// 获取授权头的辅助函数
const getAuthHeaders = () => {
  const session = typeof window !== "undefined" ? localStorage.getItem("session") : null;
  const sessionObj = session ? JSON.parse(session) : null;

  return {
    'Content-Type': 'application/json',
    'User-Agent': 'AgentFrontEnd/1.0',
    ...(sessionObj?.access_token && { "Authorization": `Bearer ${sessionObj.access_token}` }),
  };
};

// MCP服务器接口定义
export interface McpServer {
  service_name: string;
  mcp_url: string;
  status: boolean;
  remote_mcp_server_name?: string;
  remote_mcp_server?: string;
}

// MCP工具接口定义
export interface McpTool {
  name: string;
  description: string;
  parameters?: any;
}

/**
 * 获取MCP服务器列表
 */
export const getMcpServerList = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.mcp.list, {
      headers: getAuthHeaders(),
    });

    const data = await response.json();
    
    if (response.ok && data.status === 'success') {
      
      // 转换后端字段名称为前端期望的格式
      const formattedData = (data.remote_mcp_server_list || []).map((server: any) => {
        return {
          service_name: server.remote_mcp_server_name,
          mcp_url: server.remote_mcp_server,
          status: server.status || false 
        };
      });
      
      return {
        success: true,
        data: formattedData,
        message: ''
      };
    } else {
      // 根据HTTP状态码处理具体的错误信息
      let errorMessage = data.message || t('mcpService.message.getServerListFailed');
      
      switch (response.status) {
        case 400:
          errorMessage = t('mcpService.message.getRemoteProxyFailed');
          break;
        case 404:
          errorMessage = t('mcpService.message.resourceNotFound');
          break;
        case 500:
          errorMessage = t('mcpService.message.serverInternalError');
          break;
        case 503:
          errorMessage = t('mcpService.message.serviceUnavailable');
          break;
        default:
          errorMessage = data.message || t('mcpService.message.getServerListFailed');
      }
      
      return {
        success: false,
        data: [],
        message: errorMessage
      };
    }
  } catch (error) {
    console.error(t('mcpService.debug.getServerListFailed'), error);
    return {
      success: false,
      data: [],
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * 添加MCP服务器
 */
export const addMcpServer = async (mcpUrl: string, serviceName: string) => {
  try {
    const response = await fetch(
      `${API_ENDPOINTS.mcp.add}?mcp_url=${encodeURIComponent(mcpUrl)}&service_name=${encodeURIComponent(serviceName)}`,
      {
        method: 'POST',
        headers: getAuthHeaders(),
      }
    );

    const data = await response.json();
    
    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.addServerSuccess')
      };
    } else {
      // 处理具体的错误状态码和错误信息
      let errorMessage = data.message || t('mcpService.message.addServerFailed');
      
      if (response.status === 409) {
        errorMessage = t('mcpService.message.nameAlreadyUsed');
      } else if (response.status === 503) {
        errorMessage = t('mcpService.message.cannotConnectToServer');
      } else {
          errorMessage = t('mcpService.message.addProxyFailed');
      }
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error(t('mcpService.debug.addServerFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * 删除MCP服务器
 */
export const deleteMcpServer = async (mcpUrl: string, serviceName: string) => {
  try {
    const response = await fetch(
      `${API_ENDPOINTS.mcp.delete}?mcp_url=${encodeURIComponent(mcpUrl)}&service_name=${encodeURIComponent(serviceName)}`,
      {
        method: 'DELETE',
        headers: getAuthHeaders(),
      }
    );

    const data = await response.json();
    
    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.deleteServerSuccess')
      };
    } else {
      // 根据HTTP状态码处理具体的错误信息
      let errorMessage = data.message || t('mcpService.message.deleteServerFailed');
      
      switch (response.status) {
        case 400:
          errorMessage = t('mcpService.message.deleteProxyFailed');
          break;
        case 404:
          errorMessage = t('mcpService.message.serverNotFound');
          break;
        case 500:
          errorMessage = t('mcpService.message.serverInternalError');
          break;
        default:
          errorMessage = data.message || t('mcpService.message.deleteServerFailed');
      }
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error(t('mcpService.debug.deleteServerFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * 获取远程MCP服务器的工具列表
 */
export const getMcpTools = async (serviceName: string, mcpUrl: string) => {
  try {
    const response = await fetch(
      `${API_ENDPOINTS.mcp.tools}?service_name=${encodeURIComponent(serviceName)}&mcp_url=${encodeURIComponent(mcpUrl)}`,
      {
        method: 'POST',
        headers: getAuthHeaders(),
      }
    );

    const data = await response.json();
    
    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data.tools || [],
        message: ''
      };
    } else {
      // 根据HTTP状态码处理具体的错误信息
      let errorMessage = data.message || t('mcpService.message.getToolsFailed');
      
      switch (response.status) {
        case 400:
          errorMessage = t('mcpService.message.getToolsFromServerFailed');
          break;
        case 404:
          errorMessage = t('mcpService.message.serverNotFound');
          break;
        case 500:
          errorMessage = t('mcpService.message.serverInternalError');
          break;
        case 503:
          errorMessage = t('mcpService.message.cannotConnectToServer');
          break;
        default:
          errorMessage = data.message || t('mcpService.message.getToolsFailed');
      }
      
      return {
        success: false,
        data: [],
        message: errorMessage
      };
    }
  } catch (error) {
    console.error(t('mcpService.debug.getToolsFailed'), error);
    return {
      success: false,
      data: [],
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * 更新工具列表及状态
 */
export const updateToolList = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.tool.updateTool, {
      headers: getAuthHeaders(),
    });

    const data = await response.json();
    
    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.updateToolListSuccess')
      };
    } else {
      // 根据HTTP状态码处理具体的错误信息
      let errorMessage = data.message || t('mcpService.message.updateToolListFailed');
      
      switch (response.status) {
        case 400:
          errorMessage = t('mcpService.message.updateToolListBadRequest');
          break;
        case 404:
          errorMessage = t('mcpService.message.resourceNotFound');
          break;
        case 500:
          errorMessage = t('mcpService.message.serverInternalError');
          break;
        case 503:
          errorMessage = t('mcpService.message.serviceUnavailable');
          break;
        default:
          errorMessage = data.message || t('mcpService.message.updateToolListFailed');
      }
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error(t('mcpService.debug.updateToolListFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * 重新挂载所有MCP服务器
 */
export const recoverMcpServers = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.mcp.recover, {
      headers: getAuthHeaders(),
    });

    const data = await response.json();
    
    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.recoverServersSuccess')
      };
    } else {
      // 根据HTTP状态码处理具体的错误信息
      let errorMessage = data.message || t('mcpService.message.recoverServersFailed');
      
      switch (response.status) {
        case 400:
          errorMessage = t('mcpService.message.recoverServerssBadRequest');
          break;
        case 404:
          errorMessage = t('mcpService.message.resourceNotFound');
          break;
        case 500:
          errorMessage = t('mcpService.message.serverInternalError');
          break;
        case 503:
          errorMessage = t('mcpService.message.serviceUnavailable');
          break;
        default:
          errorMessage = data.message || t('mcpService.message.recoverServersFailed');
      }
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error(t('mcpService.debug.recoverServersFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};