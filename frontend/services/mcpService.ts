import { API_ENDPOINTS } from './api';

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
  // 后端返回的字段名称
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
      console.log('MCP服务器列表原始数据:', data);
      
      // 转换后端字段名称为前端期望的格式
      const formattedData = (data.remote_mcp_server_list || []).map((server: any) => {
        console.log('处理服务器数据:', server);
        return {
          service_name: server.remote_mcp_server_name,
          mcp_url: server.remote_mcp_server
        };
      });
      
      console.log('格式化后的数据:', formattedData);
      
      return {
        success: true,
        data: formattedData,
        message: ''
      };
    } else {
      // 处理具体的错误信息
      let errorMessage = data.message || '获取MCP服务器列表失败';
      
      if (data.message === 'Failed to get remote MCP proxy') {
        errorMessage = '获取远程MCP代理列表失败，请稍后重试';
      } else if (data.message) {
        errorMessage = data.message;
      }
      
      return {
        success: false,
        data: [],
        message: errorMessage
      };
    }
  } catch (error) {
    console.error('获取MCP服务器列表失败:', error);
    return {
      success: false,
      data: [],
      message: '网络请求失败，请检查网络连接并重试'
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
        message: data.message || '添加MCP服务器成功'
      };
    } else {
      // 处理具体的错误状态码和错误信息
      let errorMessage = data.message || '添加MCP服务器失败';
      
      if (response.status === 409) {
        errorMessage = '服务名称已存在，请使用其他名称';
      } else if (response.status === 503) {
        errorMessage = '无法连接到远程MCP服务器，请检查URL是否正确且服务器正在运行';
      } else {
          errorMessage = '添加MCP代理失败，请检查服务器配置';
      }
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error('添加MCP服务器失败:', error);
    return {
      success: false,
      data: null,
      message: '网络请求失败，请检查网络连接并重试'
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
        message: data.message || '删除MCP服务器成功'
      };
    } else {
      // 处理具体的错误状态码和错误信息
      let errorMessage = data.message || '删除MCP服务器失败';
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error('删除MCP服务器失败:', error);
    return {
      success: false,
      data: null,
      message: '网络请求失败，请检查网络连接并重试'
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
      // 处理具体的错误信息
      let errorMessage = data.message || '获取MCP工具列表失败';
      
      return {
        success: false,
        data: [],
        message: errorMessage
      };
    }
  } catch (error) {
    console.error('获取MCP工具列表失败:', error);
    return {
      success: false,
      data: [],
      message: '网络请求失败，请检查网络连接并重试'
    };
  }
};

/**
 * 更新工具列表及状态
 */
export const updateToolList = async () => {
  try {
    const response = await fetch(API_ENDPOINTS.mcp.updateTool, {
      headers: getAuthHeaders(),
    });

    const data = await response.json();
    
    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || '更新工具列表成功'
      };
    } else {
      // 处理具体的错误信息
      let errorMessage = data.message || '更新工具列表失败';
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error('更新工具列表失败:', error);
    return {
      success: false,
      data: null,
      message: '网络请求失败，请检查网络连接并重试'
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
        message: data.message || '重新挂载MCP服务器成功'
      };
    } else {
      // 处理具体的错误信息
      let errorMessage = data.message || '重新挂载MCP服务器失败';
      
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    console.error('重新挂载MCP服务器失败:', error);
    return {
      success: false,
      data: null,
      message: '网络请求失败，请检查网络连接并重试'
    };
  }
};