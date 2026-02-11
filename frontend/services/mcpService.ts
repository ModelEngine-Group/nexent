import i18n from 'i18next';

import { API_ENDPOINTS } from './api';
import log from "@/lib/logger";

// Translation function
const t = (key: string, options?: any): string => {
  return i18n.t(key, options) as string;
};

// TODO: Use fetchWithAuth instead
// Get authorization headers helper function
const getAuthHeaders = () => {
  const session = typeof window !== "undefined" ? localStorage.getItem("session") : null;
  const sessionObj = session ? JSON.parse(session) : null;

  return {
    'Content-Type': 'application/json',
    'User-Agent': 'AgentFrontEnd/1.0',
    ...(sessionObj?.access_token && { "Authorization": `Bearer ${sessionObj.access_token}` }),
  };
};

/**
 * Get MCP server list
 */
export const getMcpServerList = async (tenantId?: string | null) => {
  try {
    const url = tenantId 
      ? `${API_ENDPOINTS.mcp.list}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.mcp.list;
    const response = await fetch(url, {
      headers: getAuthHeaders(),
    });

    const data = await response.json();

    if (response.ok && data.status === 'success') {

      // Convert backend field names to frontend expected format
      const formattedData = (data.remote_mcp_server_list || []).map((server: any) => {
        return {
          service_name: server.remote_mcp_server_name,
          mcp_url: server.remote_mcp_server,
          status: server.status || false,
          permission: server.permission,
        };
      });

      return {
        success: true,
        data: formattedData,
        enable_upload_image: data.enable_upload_image || false,
        message: ''
      };
    } else {
      // Handle specific error information based on HTTP status code
      let errorMessage = data.message || t('mcpService.message.getServerListFailed');

      switch (response.status) {
        case 500:
          errorMessage = t('mcpService.message.getRemoteProxyFailed');
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
    log.error(t('mcpService.debug.getServerListFailed'), error);
    return {
      success: false,
      data: [],
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Add MCP server
 */
export const addMcpServer = async (mcpUrl: string, serviceName: string, tenantId?: string | null) => {
  try {
    const params = new URLSearchParams({
      mcp_url: mcpUrl,
      service_name: serviceName,
    });
    if (tenantId) {
      params.append('tenant_id', tenantId);
    }
    const response = await fetch(
      `${API_ENDPOINTS.mcp.add}?${params.toString()}`,
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
      // Handle specific error status codes and error information
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
    log.error(t('mcpService.debug.addServerFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Update MCP server
 */
export const updateMcpServer = async (
  currentServiceName: string,
  currentMcpUrl: string,
  newServiceName: string,
  newMcpUrl: string,
  tenantId?: string | null
) => {
  try {
    const url = tenantId 
      ? `${API_ENDPOINTS.mcp.update}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.mcp.update;
    const response = await fetch(url, {
      method: "PUT",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        current_service_name: currentServiceName,
        current_mcp_url: currentMcpUrl,
        new_service_name: newServiceName,
        new_mcp_url: newMcpUrl,
      }),
    });

    const data = await response.json();

    if (response.ok && data.status === "success") {
      return {
        success: true,
        data: data,
        message: data.message || t("mcpService.message.updateServerSuccess"),
      };
    } else {
      // Handle specific error status codes and error information
      let errorMessage =
        data.message || t("mcpService.message.updateServerFailed");

      if (response.status === 409) {
        errorMessage = t("mcpService.message.nameAlreadyUsed");
      } else if (response.status === 503) {
        errorMessage = t("mcpService.message.cannotConnectToServer");
      } else {
        errorMessage = t("mcpService.message.updateProxyFailed");
      }

      return {
        success: false,
        data: null,
        message: errorMessage,
      };
    }
  } catch (error) {
    log.error(t("mcpService.debug.updateServerFailed"), error);
    return {
      success: false,
      data: null,
      message: t("mcpService.message.networkError"),
    };
  }
};

/**
 * Delete MCP server
 */
export const deleteMcpServer = async (mcpUrl: string, serviceName: string, tenantId?: string | null) => {
  try {
    const params = new URLSearchParams({
      mcp_url: mcpUrl,
      service_name: serviceName,
    });
    if (tenantId) {
      params.append('tenant_id', tenantId);
    }
    const response = await fetch(
      `${API_ENDPOINTS.mcp.delete}?${params.toString()}`,
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
      // Handle specific error information based on HTTP status code
      let errorMessage = data.message || t('mcpService.message.deleteServerFailed');

      switch (response.status) {
        case 500:
          errorMessage = t('mcpService.message.deleteProxyFailed');
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
    log.error(t('mcpService.debug.deleteServerFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Get tool list from remote MCP server
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
      // Handle specific error information based on HTTP status code
      let errorMessage = data.message || t('mcpService.message.getToolsFailed');

      switch (response.status) {
        case 500:
          errorMessage = t('mcpService.message.getToolsFromServerFailed');
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
    log.error(t('mcpService.debug.getToolsFailed'), error);
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
      // Handle specific error information based on HTTP status code
      let errorMessage = data.message || t('mcpService.message.updateToolListFailed');

      switch (response.status) {
        case 500:
          errorMessage = t('mcpService.message.updateToolListBadRequest');
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
    log.error(t('mcpService.debug.updateToolListFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * checkMcpServerHealth
 */
export const checkMcpServerHealth = async (mcpUrl: string, serviceName: string, tenantId?: string | null) => {
  try {
    const params = new URLSearchParams({
      mcp_url: mcpUrl,
      service_name: serviceName,
    });
    if (tenantId) {
      params.append('tenant_id', tenantId);
    }
    const response = await fetch(
      `${API_ENDPOINTS.mcp.healthcheck}?${params.toString()}`,
      {
        headers: getAuthHeaders(),
      }
    );

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.healthCheckSuccess')
      };
    } else {
      let errorMessage = data.message || t('mcpService.message.healthCheckFailed');
      if (response.status === 503) {
        errorMessage = t('mcpService.message.cannotConnectToServer');
      }
      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    log.error(t('mcpService.debug.healthCheckFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Add MCP server from container configuration
 */
export const addMcpFromConfig = async (mcpConfig: { mcpServers: Record<string, { command: string; args?: string[]; env?: Record<string, string>; port?: number; image?: string }> }, tenantId?: string | null) => {
  try {
    const url = tenantId 
      ? `${API_ENDPOINTS.mcp.addFromConfig}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.mcp.addFromConfig;
    const response = await fetch(url, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(mcpConfig),
    });

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.addFromConfigSuccess')
      };
    } else {
      let errorMessage = data.detail || data.message || t('mcpService.message.addFromConfigFailed');

      if (response.status === 400) {
        errorMessage = data.detail || t('mcpService.message.invalidConfig');
      } else if (response.status === 503) {
        errorMessage = t('mcpService.message.dockerServiceUnavailable');
      }

      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    log.error(t('mcpService.debug.addFromConfigFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Get MCP container list
 */
export const getMcpContainers = async (tenantId?: string | null) => {
  try {
    const url = tenantId 
      ? `${API_ENDPOINTS.mcp.containers}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.mcp.containers;
    const response = await fetch(url, {
      headers: getAuthHeaders(),
    });

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data.containers || [],
        message: ''
      };
    } else {
      let errorMessage = data.detail || data.message || t('mcpService.message.getContainersFailed');

      if (response.status === 503) {
        errorMessage = t('mcpService.message.dockerServiceUnavailable');
      }

      return {
        success: false,
        data: [],
        message: errorMessage
      };
    }
  } catch (error) {
    log.error(t('mcpService.debug.getContainersFailed'), error);
    return {
      success: false,
      data: [],
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Get MCP container logs
 */
export const getMcpContainerLogs = async (containerId: string, tail: number = 100, tenantId?: string | null) => {
  try {
    const params = new URLSearchParams({
      tail: tail.toString(),
    });
    if (tenantId) {
      params.append('tenant_id', tenantId);
    }
    const response = await fetch(
      `${API_ENDPOINTS.mcp.containerLogs(containerId)}?${params.toString()}`,
      {
        headers: getAuthHeaders(),
      }
    );

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data.logs || '',
        message: ''
      };
    } else {
      let errorMessage = data.detail || data.message || t('mcpService.message.getContainerLogsFailed');

      if (response.status === 404) {
        errorMessage = t('mcpService.message.containerNotFound');
      } else if (response.status === 503) {
        errorMessage = t('mcpService.message.dockerServiceUnavailable');
      }

      return {
        success: false,
        data: '',
        message: errorMessage
      };
    }
  } catch (error) {
    log.error(t('mcpService.debug.getContainerLogsFailed'), error);
    return {
      success: false,
      data: '',
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Upload MCP image and start container
 */
export const uploadMcpImage = async (file: File, port: number, serviceName?: string, envVars?: string, tenantId?: string | null) => {
  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('port', port.toString());
    if (serviceName) {
      formData.append('service_name', serviceName);
    }
    if (envVars) {
      formData.append('env_vars', envVars);
    }
    if (tenantId) {
      formData.append('tenant_id', tenantId);
    }

    const authHeaders = getAuthHeaders();
    // Remove Content-Type header for FormData - let browser set it with boundary
    const headers = { ...authHeaders };
    delete headers['Content-Type'];

    const response = await fetch(API_ENDPOINTS.mcp.uploadImage, {
      method: 'POST',
      headers: headers,
      body: formData,
    });

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.uploadImageSuccess')
      };
    } else {
      let errorMessage = data.detail || data.message || t('mcpService.message.uploadImageFailed');

      if (response.status === 400) {
        errorMessage = data.detail || t('mcpService.message.invalidUploadParameters');
      } else if (response.status === 409) {
        errorMessage = t('mcpService.message.serviceNameAlreadyExists');
      } else if (response.status === 413) {
        errorMessage = t('mcpService.message.fileTooLarge');
      } else if (response.status === 503) {
        errorMessage = t('mcpService.message.dockerServiceUnavailable');
      }

      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    log.error(t('mcpService.debug.uploadImageFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};

/**
 * Delete MCP container
 */
export const deleteMcpContainer = async (containerId: string, tenantId?: string | null) => {
  try {
    const url = tenantId 
      ? `${API_ENDPOINTS.mcp.deleteContainer(containerId)}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.mcp.deleteContainer(containerId);
    const response = await fetch(url, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      return {
        success: true,
        data: data,
        message: data.message || t('mcpService.message.deleteContainerSuccess')
      };
    } else {
      let errorMessage = data.detail || data.message || t('mcpService.message.deleteContainerFailed');

      if (response.status === 404) {
        errorMessage = t('mcpService.message.containerNotFound');
      } else if (response.status === 503) {
        errorMessage = t('mcpService.message.dockerServiceUnavailable');
      }

      return {
        success: false,
        data: null,
        message: errorMessage
      };
    }
  } catch (error) {
    log.error(t('mcpService.debug.deleteContainerFailed'), error);
    return {
      success: false,
      data: null,
      message: t('mcpService.message.networkError')
    };
  }
};
