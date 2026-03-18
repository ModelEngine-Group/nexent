import { useCallback, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import type { UploadFile } from "antd/es/upload/interface";
import log from "@/lib/logger";
import { MCP_SERVER_TYPE, MCP_TAB } from "@/const/mcpTools";
import { addMcpToolService, resolveContainerServerInfo } from "@/services/mcpToolsService";
import {
  type AddMcpLocalActions,
  type AddMcpLocalState,
  type McpServerType,
  type McpTab,
} from "@/types/mcpTools";

type UseMcpToolsAddLocalParams = {
  addModalTab: McpTab;
  t: (key: string) => string;
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
  const [newServerType, setNewServerType] = useState<McpServerType>(MCP_SERVER_TYPE.HTTP);
  const [containerConfigJson, setContainerConfigJson] = useState("");
  const [containerUploadFileList, setContainerUploadFileList] = useState<UploadFile[]>([]);
  const [containerPort, setContainerPort] = useState<number | undefined>(undefined);
  const [containerServiceName, setContainerServiceName] = useState("");
  const [newTagDrafts, setNewTagDrafts] = useState<string[]>([]);
  const [newTagInputValue, setNewTagInputValue] = useState("");
  const [addingService, setAddingService] = useState(false);

  const addMutation = useMutation({ mutationFn: addMcpToolService });

  const reset = useCallback(() => {
    setNewServiceName("");
    setNewServiceUrl("");
    setNewServiceDesc("");
    setNewServiceAuthorizationToken("");
    setNewServerType(MCP_SERVER_TYPE.HTTP);
    setContainerConfigJson("");
    setContainerUploadFileList([]);
    setContainerPort(undefined);
    setContainerServiceName("");
    setNewTagDrafts([]);
    setNewTagInputValue("");
    setAddingService(false);
  }, []);

  const validateLocalAdd = () => {
    if (!newServiceName.trim()) return t("mcpTools.add.validate.nameRequired");
    if ((newServerType === MCP_SERVER_TYPE.HTTP || newServerType === MCP_SERVER_TYPE.SSE) && !newServiceUrl.trim()) {
      return t("mcpTools.add.validate.httpUrlRequired");
    }
    if (newServerType === MCP_SERVER_TYPE.CONTAINER) {
      const hasConfig = containerConfigJson.trim().length > 0 || containerUploadFileList.length > 0;
      if (!hasConfig) return t("mcpTools.add.validate.containerConfigRequired");
      if (!containerServiceName.trim() || !containerPort) {
        return t("mcpTools.add.validate.containerRequired");
      }
    }
    if (addModalTab !== MCP_TAB.LOCAL) return t("mcpTools.add.validate.localTabOnly");
    return null;
  };

  const handleAddService = async () => {
    const validationError = validateLocalAdd();
    if (validationError) {
      log.error("[useMcpToolsAddLocal] Local add validation failed", {
        validationError,
        addModalTab,
        serverType: newServerType,
      });
      message.error(validationError);
      return;
    }

    const tags = newTagDrafts.map((tag) => tag.trim()).filter((tag) => tag.length > 0);
    const normalizedToken = newServiceAuthorizationToken.trim() || undefined;

    setAddingService(true);
    try {
      const resolvedServerInfo = await resolveContainerServerInfo({
        serverType: newServerType,
        serviceUrl: newServiceUrl,
        containerServiceName,
        containerPort,
        containerConfigJson,
        containerUploadFileList,
        authorizationToken: normalizedToken,
        t,
      });
      if (!resolvedServerInfo.success || !resolvedServerInfo.data) {
        throw new Error(resolvedServerInfo.message || t("mcpTools.add.failed"));
      }

      const result = await addMutation.mutateAsync({
        name: newServiceName.trim(),
        description: newServiceDesc.trim() || t("mcpTools.service.defaultDescription"),
        source: addModalTab,
        server_type: newServerType,
        server_url: resolvedServerInfo.data.finalServerUrl,
        tags,
        authorization_token: normalizedToken,
        container_config: resolvedServerInfo.data.containerConfig,
      });

      if (!result.success) throw new Error(result.message || t("mcpTools.add.failed"));
      await onServiceAdded();
      message.success(t("mcpTools.add.success"));
      onClose();
    } catch (error) {
      const msg = error instanceof Error ? error.message : t("mcpTools.add.failed");
      log.error("[useMcpToolsAddLocal] Failed to add MCP service", {
        error,
        serviceName: newServiceName,
        serverType: newServerType,
        addModalTab,
      });
      message.error(msg === "MCP connection failed" ? t("mcpTools.error.connectionFailed") : msg);
    } finally {
      setAddingService(false);
    }
  };

  const addNewTag = () => {
    const nextTag = newTagInputValue.trim();
    if (!nextTag) return;
    setNewTagDrafts((prev) => (prev.includes(nextTag) ? prev : [...prev, nextTag]));
    setNewTagInputValue("");
  };

  const removeNewTag = useCallback((index: number) => {
    setNewTagDrafts((prev) => prev.filter((_, idx) => idx !== index));
  }, []);

  const state: AddMcpLocalState = useMemo(
    () => ({
      newServiceName,
      newServiceDesc,
      newServerType,
      newServiceUrl,
      newServiceAuthorizationToken,
      containerUploadFileList,
      containerConfigJson,
      containerPort,
      containerServiceName,
      newTagDrafts,
      newTagInputValue,
      addingService,
    }),
    [
      newServiceName,
      newServiceDesc,
      newServerType,
      newServiceUrl,
      newServiceAuthorizationToken,
      containerUploadFileList,
      containerConfigJson,
      containerPort,
      containerServiceName,
      newTagDrafts,
      newTagInputValue,
      addingService,
    ]
  );

  const actions: AddMcpLocalActions = useMemo(
    () => ({
      onNewServiceNameChange: setNewServiceName,
      onNewServiceDescChange: setNewServiceDesc,
      onNewServerTypeChange: setNewServerType,
      onNewServiceUrlChange: setNewServiceUrl,
      onNewServiceAuthorizationTokenChange: setNewServiceAuthorizationToken,
      onContainerUploadFileListChange: setContainerUploadFileList,
      onContainerConfigJsonChange: setContainerConfigJson,
      onContainerPortChange: setContainerPort,
      onContainerServiceNameChange: setContainerServiceName,
      onAddNewTag: addNewTag,
      onRemoveNewTag: removeNewTag,
      onNewTagInputChange: setNewTagInputValue,
      onSaveAndAdd: handleAddService,
    }),
    [removeNewTag]
  );

  return {
    state,
    actions,
    reset,
  };
}
