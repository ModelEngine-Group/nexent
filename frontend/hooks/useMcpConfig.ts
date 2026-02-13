"use client";

import { useState, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  addMcpServer,
  updateMcpServer,
  deleteMcpServer,
  getMcpTools,
  updateToolList,
  checkMcpServerHealth,
  addMcpFromConfig,
  uploadMcpImage,
  getMcpContainerLogs,
  deleteMcpContainer,
} from "@/services/mcpService";
import { McpServer, McpContainer } from "@/types/agentConfig";
import log from "@/lib/logger";
import { MCP_SERVERS_QUERY_KEY, useMcpServerList } from "@/hooks/mcp/useMcpServerList";
import { useMcpContainerList } from "@/hooks/mcp/useMcpContainerList";

export interface UseMcpConfigOptions {
  enabled?: boolean;
  tenantId?: string | null;
  onServerAdded?: () => void;
  onServerDeleted?: () => void;
  onServerUpdated?: () => void;
  onContainerAdded?: () => void;
  onContainerDeleted?: () => void;
  onToolsRefreshed?: () => void;
}

// Message keys for i18n
export interface McpMessageKeys {
  addSuccess: string;
  addError: string;
  deleteSuccess: string;
  deleteError: string;
  updateSuccess: string;
  updateError: string;
  healthChecking: string;
  healthCheckSuccess: string;
  healthCheckError: string;
  getToolsError: string;
  containerAddSuccess: string;
  containerAddError: string;
  containerDeleteSuccess: string;
  containerDeleteError: string;
  uploadImageSuccess: string;
  uploadImageError: string;
  getLogsError: string;
  loadServerError: string;
  loadContainerError: string;
}

export function useMcpConfig(options: UseMcpConfigOptions = {}) {
  const queryClient = useQueryClient();

  const {
    serverList,
    enableUploadImage,
    isLoading: loadingServers,
    refetch: refetchMcpServers,
    invalidate: invalidateMcpServers,
  } = useMcpServerList({ enabled: options.enabled ?? true, staleTime: 60_000, tenantId: options.tenantId });

  const {
    containerList,
    isLoading: loadingContainers,
    refetch: refetchMcpContainers,
    invalidate: invalidateMcpContainers,
  } = useMcpContainerList({ enabled: options.enabled ?? true, staleTime: 60_000, tenantId: options.tenantId });

  const loading = loadingServers || loadingContainers;

  // Loading states
  const [updatingTools, setUpdatingTools] = useState(false);
  const [healthCheckLoading, setHealthCheckLoading] = useState<{ [key: string]: boolean }>({});
  const delayedContainerRefreshRef = useRef<number | undefined>(undefined);

  // Helper function to refresh tools and agents
  const refreshToolsAndAgents = useCallback(async () => {
    setUpdatingTools(true);
    try {
      await updateToolList();
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      options.onToolsRefreshed?.();
    } catch (error) {
      log.error("Failed to refresh tools and agents:", error);
    } finally {
      setUpdatingTools(false);
    }
  }, [options, queryClient]);

  // Load MCP server list
  const loadServerList = useCallback(async () => {
    try {
      await refetchMcpServers();
      return { success: true };
    } catch (error) {
      log.error("Failed to load server list:", error);
      return { success: false, message: "Failed to load server list", messageKey: "mcpConfig.message.loadServerListFailed" };
    }
  }, [refetchMcpServers]);

  // Load container list
  const loadContainerList = useCallback(async () => {
    try {
      await refetchMcpContainers();
      return { success: true };
    } catch (error) {
      log.error("Failed to load container list:", error);
      return { success: false, message: "Failed to load container list", messageKey: "mcpConfig.message.loadContainerListFailed" };
    }
  }, [refetchMcpContainers]);

  // Add MCP server
  const handleAddServer = useCallback(async (url: string, name: string) => {
    try {
      const result = await addMcpServer(url, name, options.tenantId);
      if (result.success) {
        invalidateMcpServers();
        await refreshToolsAndAgents();
        options.onServerAdded?.();
        return { success: true, messageKey: "mcpService.message.addServerSuccess" };
      } else {
        return { success: false, message: result.message, messageKey: "mcpService.message.addServerFailed" };
      }
    } catch (error) {
      log.error("Failed to add server:", error);
      return { success: false, message: "Failed to add server", messageKey: "mcpConfig.message.addServerFailed" };
    }
  }, [invalidateMcpServers, refreshToolsAndAgents, options]);

  // Delete MCP server
  const handleDeleteServer = useCallback(async (server: McpServer) => {
    try {
      const result = await deleteMcpServer(server.mcp_url, server.service_name, options.tenantId);
      if (result.success) {
        invalidateMcpServers();
        refreshToolsAndAgents().catch(e => log.error("Refresh failed:", e));
        options.onServerDeleted?.();
        return { success: true, messageKey: "mcpService.message.deleteServerSuccess" };
      } else {
        return { success: false, message: result.message, messageKey: "mcpConfig.message.deleteServerFailed" };
      }
    } catch (error) {
      log.error("Failed to delete server:", error);
      return { success: false, message: "Failed to delete server", messageKey: "mcpConfig.message.deleteServerFailed" };
    }
  }, [invalidateMcpServers, refreshToolsAndAgents, options]);

  // View server tools
  const handleViewTools = useCallback(async (server: McpServer) => {
    try {
      const result = await getMcpTools(server.service_name, server.mcp_url);
      if (result.success) {
        return { success: true, data: result.data };
      } else {
        return { success: false, data: [], message: result.message, messageKey: "mcpConfig.message.getToolsFailed" };
      }
    } catch (error) {
      log.error("Failed to get tools:", error);
      return { success: false, data: [], message: "Failed to get tools", messageKey: "mcpConfig.message.getToolsFailed" };
    }
  }, []);

  // Check server health
  const handleCheckHealth = useCallback(async (server: McpServer) => {
    const key = `${server.service_name}__${server.mcp_url}`;
    setHealthCheckLoading(prev => ({ ...prev, [key]: true }));
    try {
      const result = await checkMcpServerHealth(server.mcp_url, server.service_name, options.tenantId);
      invalidateMcpServers();
      invalidateMcpContainers();
      await refreshToolsAndAgents();
      if (result.success) {
        return { success: true, messageKey: "mcpConfig.message.healthCheckSuccess" };
      } else {
        return { success: false, message: result.message, messageKey: "mcpConfig.message.healthCheckFailed" };
      }
    } catch (error) {
      log.error("Health check failed:", error);
      invalidateMcpServers();
      invalidateMcpContainers();
      await refreshToolsAndAgents();
      return { success: false, message: "Health check failed", messageKey: "mcpConfig.message.healthCheckFailed" };
    } finally {
      setHealthCheckLoading(prev => ({ ...prev, [key]: false }));
    }
  }, [invalidateMcpServers, invalidateMcpContainers, refreshToolsAndAgents, options.tenantId]);

  // Update MCP server
  const handleUpdateServer = useCallback(async (
    oldName: string,
    oldUrl: string,
    newName: string,
    newUrl: string
  ) => {
    try {
      const result = await updateMcpServer(oldName, oldUrl, newName, newUrl, options.tenantId);
      if (result.success) {
        // Best-effort optimistic status update for UI responsiveness
        queryClient.setQueryData([...MCP_SERVERS_QUERY_KEY, options.tenantId], (prev: any) => {
          if (!prev?.data) return prev;
          return {
            ...prev,
            data: (prev.data as McpServer[]).map((s) =>
              s.service_name === newName && s.mcp_url === newUrl ? { ...s, status: true } : s
            ),
          };
        });
        invalidateMcpServers();
        await refreshToolsAndAgents();
        options.onServerUpdated?.();
        return { success: true, messageKey: "mcpService.message.updateServerSuccess" };
      } else {
        return { success: false, message: result.message, messageKey: "mcpService.message.updateServerFailed" };
      }
    } catch (error) {
      log.error("Failed to update server:", error);
      return { success: false, message: "Failed to update server", messageKey: "mcpService.message.updateServerFailed" };
    }
  }, [invalidateMcpServers, refreshToolsAndAgents, queryClient, options]);

  // Add container
  const handleAddContainer = useCallback(async (config: any, port: number) => {
    // Correctly process the mcpServers object from the config
    const mcpServers = config.mcpServers || {};
    const configWithPorts = {
      mcpServers: Object.fromEntries(
        Object.entries(mcpServers as Record<string, any>).map(([key, value]) => [
          key,
          { ...value, port },
        ])
      ),
    };

    if (delayedContainerRefreshRef.current) {
      window.clearTimeout(delayedContainerRefreshRef.current);
    }
    delayedContainerRefreshRef.current = window.setTimeout(() => {
      invalidateMcpContainers().catch(e => log.error("Failed to refresh containers:", e));
    }, 3000);

    try {
      const result = await addMcpFromConfig(configWithPorts as any, options.tenantId);
      if (result.success) {
        invalidateMcpContainers();
        invalidateMcpServers();
        await refreshToolsAndAgents();
        options.onContainerAdded?.();
        return { success: true, messageKey: "mcpService.message.addContainerSuccess" };
      } else {
        return { success: false, message: result.message, messageKey: "mcpConfig.message.addContainerFailed" };
      }
    } catch (error) {
      log.error("Failed to add container:", error);
      return { success: false, message: "Failed to add container", messageKey: "mcpConfig.message.addContainerFailed" };
    }
  }, [invalidateMcpContainers, invalidateMcpServers, refreshToolsAndAgents, options]);

  // Upload MCP image
  const handleUploadImage = useCallback(async (
    file: File,
    port: number,
    serviceName?: string
  ) => {
    try {
      const result = await uploadMcpImage(file, port, serviceName, undefined, options.tenantId);
      if (result.success) {
        invalidateMcpContainers();
        invalidateMcpServers();
        await refreshToolsAndAgents();
        return { success: true, messageKey: "mcpService.message.uploadImageSuccess" };
      } else {
        return { success: false, message: result.message, messageKey: "mcpConfig.message.uploadImageFailed" };
      }
    } catch (error) {
      log.error("Failed to upload image:", error);
      return { success: false, message: "Failed to upload image", messageKey: "mcpConfig.message.uploadImageFailed" };
    }
  }, [invalidateMcpContainers, invalidateMcpServers, refreshToolsAndAgents, options.tenantId]);

  // Delete container
  const handleDeleteContainer = useCallback(async (container: McpContainer) => {
    try {
      const result = await deleteMcpContainer(container.container_id, options.tenantId);
      if (result.success) {
        invalidateMcpContainers();
        invalidateMcpServers();
        refreshToolsAndAgents().catch(e => log.error("Refresh failed:", e));
        options.onContainerDeleted?.();
        return { success: true, messageKey: "mcpService.message.deleteContainerSuccess" };
      } else {
        return { success: false, message: result.message, messageKey: "mcpConfig.message.deleteContainerFailed" };
      }
    } catch (error) {
      log.error("Failed to delete container:", error);
      return { success: false, message: "Failed to delete container", messageKey: "mcpConfig.message.deleteContainerFailed" };
    }
  }, [invalidateMcpContainers, invalidateMcpServers, refreshToolsAndAgents, options]);

  // View container logs
  const handleViewLogs = useCallback(async (containerId: string, maxLines: number = 500) => {
    try {
      const result = await getMcpContainerLogs(containerId, maxLines, options.tenantId);
      if (result.success) {
        return { success: true, data: result.data };
      } else {
        return { success: false, data: result.message, messageKey: "mcpConfig.message.getContainerLogsFailed" };
      }
    } catch (error) {
      log.error("Failed to get logs:", error);
      return { success: false, data: "Failed to get logs", messageKey: "mcpConfig.message.getContainerLogsFailed" };
    }
  }, [options.tenantId]);

  return {
    // State
    serverList,
    loading,
    containerList,
    enableUploadImage,
    updatingTools,
    healthCheckLoading,

    // Data loading functions
    loadServerList,
    loadContainerList,
    refreshToolsAndAgents,

    // Handler functions
    handleAddServer,
    handleDeleteServer,
    handleViewTools,
    handleCheckHealth,
    handleUpdateServer,
    handleAddContainer,
    handleUploadImage,
    handleDeleteContainer,
    handleViewLogs,
  };
}
