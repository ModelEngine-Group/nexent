import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_TRANSPORT_TYPE, MCP_TAB } from "@/const/mcpTools";
import {
  checkMcpContainerPortConflictService,
  addContainerMcpToolService,
  addMcpToolService,
  suggestMcpContainerPortService,
  resolveContainerServerInfo,
} from "@/services/mcpToolsService";
import { type McpTransportType, type McpTab } from "@/types/mcpTools";

type UseMcpToolsAddLocalParams = {
  addModalTab: McpTab;
  t: (key: string, params?: Record<string, unknown>) => string;
  message: MessageInstance;
  onServiceAdded: () => Promise<unknown>;
  onClose: () => void;
};

export function useMcpToolsAddLocal({
  addModalTab,
  t,
  message,
  onServiceAdded,
  onClose,
}: UseMcpToolsAddLocalParams) {
  const [newServiceName, setNewServiceName] = useState("");
  const [newServiceUrl, setNewServiceUrl] = useState("");
  const [newServiceDesc, setNewServiceDesc] = useState("");
  const [newServiceAuthorizationToken, setNewServiceAuthorizationToken] = useState("");
  const [newTransportType, setNewTransportType] = useState<McpTransportType>(MCP_TRANSPORT_TYPE.HTTP);
  const [containerConfigJson, setContainerConfigJson] = useState("");
  const [containerPort, setContainerPort] = useState<number | undefined>(undefined);
  const [debouncedContainerPort, setDebouncedContainerPort] = useState<number | undefined>(undefined);
  const [newTagDrafts, setNewTagDrafts] = useState<string[]>([]);
  const [newTagInputValue, setNewTagInputValue] = useState("");
  const [addingService, setAddingService] = useState(false);
  const [suggestingContainerPort, setSuggestingContainerPort] = useState(false);

  const addMutation = useMutation({ mutationFn: addMcpToolService });

  useEffect(() => {
    if (newTransportType !== MCP_TRANSPORT_TYPE.STDIO || !containerPort) {
      setDebouncedContainerPort(undefined);
      return;
    }

    const timer = window.setTimeout(() => {
      setDebouncedContainerPort(containerPort);
    }, 350);

    return () => window.clearTimeout(timer);
  }, [containerPort, newTransportType]);

  const containerPortCheckQuery = useQuery({
    queryKey: ["mcp-tools", "local-container-port-check", debouncedContainerPort],
    enabled: addModalTab === MCP_TAB.LOCAL && newTransportType === MCP_TRANSPORT_TYPE.STDIO && typeof debouncedContainerPort === "number",
    retry: false,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await checkMcpContainerPortConflictService({
        port: debouncedContainerPort as number,
      });
      return result.data;
    },
  });

  const isPortCheckEnabled =
    addModalTab === MCP_TAB.LOCAL &&
    newTransportType === MCP_TRANSPORT_TYPE.STDIO &&
    typeof containerPort === "number";
  const isCurrentPortChecked =
    typeof containerPort === "number" &&
    debouncedContainerPort === containerPort &&
    typeof containerPortCheckQuery.data?.available === "boolean";
  const containerPortCheckLoading = isPortCheckEnabled && !isCurrentPortChecked && !containerPortCheckQuery.isError;
  const containerPortAvailable = containerPortCheckQuery.data?.available === true;

  const handleSuggestContainerPort = useCallback(async () => {
    setSuggestingContainerPort(true);
    try {
      const startPort = Math.max((containerPort || 5500) + 1, 1);
      const result = await suggestMcpContainerPortService({ start_port: startPort });
      setContainerPort(result.data.port);
      message.success(t("mcpTools.addModal.portSuggested", { port: result.data.port }));
    } catch (error) {
      log.error("[useMcpToolsAddLocal] Failed to suggest container port", { error });
      message.error(t("mcpTools.addModal.portSuggestFailed"));
    } finally {
      setSuggestingContainerPort(false);
    }
  }, [containerPort, message, t]);

  const reset = useCallback(() => {
    setNewServiceName("");
    setNewServiceUrl("");
    setNewServiceDesc("");
    setNewServiceAuthorizationToken("");
    setNewTransportType(MCP_TRANSPORT_TYPE.HTTP);
    setContainerConfigJson("");
    setContainerPort(undefined);
    setNewTagDrafts([]);
    setNewTagInputValue("");
    setAddingService(false);
  }, []);

  const validateLocalAdd = useCallback(() => {
    if (!newServiceName.trim()) {
      return t("mcpTools.add.validate.nameRequired");
    }
    if ((newTransportType === MCP_TRANSPORT_TYPE.HTTP || newTransportType === MCP_TRANSPORT_TYPE.SSE) && !newServiceUrl.trim()) {
      return t("mcpTools.add.validate.httpUrlRequired");
    }
    if (newTransportType === MCP_TRANSPORT_TYPE.STDIO) {
      const hasConfig = containerConfigJson.trim().length > 0;
      if (!hasConfig) return t("mcpTools.add.validate.containerConfigRequired");
      if (!containerPort) {
        return t("mcpTools.add.validate.containerRequired");
      }
    }
    if (addModalTab !== MCP_TAB.LOCAL) return t("mcpTools.add.validate.localTabOnly");
    return null;
  }, [
    addModalTab,
    containerConfigJson,
    containerPort,
    newTransportType,
    newServiceName,
    newServiceUrl,
    t,
  ]);

  const handleAddService = useCallback(async () => {
    const validationError = validateLocalAdd();
    if (validationError) {
      log.error("[useMcpToolsAddLocal] Local add validation failed", {
        validationError,
        addModalTab,
        transportType: newTransportType,
      });
      message.error(validationError);
      return;
    }

    const tags = newTagDrafts.map((tag) => tag.trim()).filter((tag) => tag.length > 0);
    const normalizedToken = newServiceAuthorizationToken.trim() || undefined;

    setAddingService(true);
    try {
      const resolvedServerInfo = await resolveContainerServerInfo({
        transportType: newTransportType,
        serviceUrl: newServiceUrl,
        containerPort,
        containerConfigJson,
      });

      const resolvedServiceName = newServiceName.trim();

      if (newTransportType === MCP_TRANSPORT_TYPE.STDIO && resolvedServerInfo.data.mcpConfig) {
        const portCheck = await checkMcpContainerPortConflictService({
          port: containerPort as number,
        });
        if (!portCheck.data.available) {
          message.error(t("mcpTools.addModal.portOccupied", { port: containerPort }));
          return;
        }

        await addContainerMcpToolService({
          name: resolvedServiceName,
          description: newServiceDesc.trim(),
          tags,
          authorization_token: normalizedToken,
          port: containerPort as number,
          mcp_config: resolvedServerInfo.data.mcpConfig,
        });
      } else {
        await addMutation.mutateAsync({
          name: resolvedServiceName,
          description: newServiceDesc.trim(),
          source: addModalTab,
          transport_type: newTransportType,
          server_url: resolvedServerInfo.data.finalServerUrl,
          tags,
          authorization_token: normalizedToken,
          container_config: resolvedServerInfo.data.containerConfig,
        });
      }

      await onServiceAdded();
      message.success(t("mcpTools.add.success"));
      onClose();
    } catch (error) {
      log.error("[useMcpToolsAddLocal] Failed to add MCP service", {
        error,
        serviceName: newServiceName,
        transportType: newTransportType,
        addModalTab,
      });
      message.error(t("mcpTools.add.failed"));
    } finally {
      setAddingService(false);
    }
  }, [
    addModalTab,
    addMutation,
    containerConfigJson,
    containerPort,
    message,
    newTransportType,
    newServiceAuthorizationToken,
    newServiceDesc,
    newServiceName,
    newServiceUrl,
    newTagDrafts,
    onClose,
    onServiceAdded,
    t,
    validateLocalAdd,
  ]);

  const addNewTag = useCallback(() => {
    const nextTag = newTagInputValue.trim();
    if (!nextTag) return;
    setNewTagDrafts((prev) => (prev.includes(nextTag) ? prev : [...prev, nextTag]));
    setNewTagInputValue("");
  }, [newTagInputValue]);

  const removeNewTag = useCallback((index: number) => {
    setNewTagDrafts((prev) => prev.filter((_, idx) => idx !== index));
  }, []);

  return {
    newServiceName,
    newServiceDesc,
    newTransportType,
    newServiceUrl,
    newServiceAuthorizationToken,
    containerConfigJson,
    containerPort,
    newTagDrafts,
    newTagInputValue,
    addingService,
    setNewServiceName,
    setNewServiceDesc,
    setNewTransportType,
    setNewServiceUrl,
    setNewServiceAuthorizationToken,
    setContainerConfigJson,
    setContainerPort,
    addNewTag,
    removeNewTag,
    setNewTagInputValue,
    handleAddService,
    handleSuggestContainerPort,
    containerPortCheckLoading,
    containerPortSuggesting: suggestingContainerPort,
    containerPortAvailable,
    reset,
  };
}
