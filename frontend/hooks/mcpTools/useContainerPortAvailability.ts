import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import {
  checkMcpContainerPortConflictService,
  suggestMcpContainerPortService,
} from "@/services/mcpToolsService";

type UseContainerPortAvailabilityParams = {
  scope: string;
  enabled: boolean;
  containerPort: number | undefined;
  setContainerPort: (value: number | undefined) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
  message: MessageInstance;
  logTag: string;
};

type EnsureContainerPortAvailableParams = {
  containerPort: number | undefined;
  message: MessageInstance;
  t: (key: string, params?: Record<string, unknown>) => string;
};

export async function ensureContainerPortAvailableOnce({
  containerPort,
  message,
  t,
}: EnsureContainerPortAvailableParams): Promise<boolean> {
  if (typeof containerPort !== "number") {
    return false;
  }

  const portCheck = await checkMcpContainerPortConflictService({
    port: containerPort,
  });

  if (!portCheck.data.available) {
    message.error(t("mcpTools.addModal.portOccupied", { port: containerPort }));
    return false;
  }

  return true;
}

export function useContainerPortAvailability({
  scope,
  enabled,
  containerPort,
  setContainerPort,
  t,
  message,
  logTag,
}: UseContainerPortAvailabilityParams) {
  const [debouncedContainerPort, setDebouncedContainerPort] = useState<number | undefined>(undefined);
  const [containerPortSuggesting, setContainerPortSuggesting] = useState(false);

  useEffect(() => {
    if (!(enabled && typeof containerPort === "number")) {
      setDebouncedContainerPort(undefined);
      return;
    }

    const timer = window.setTimeout(() => {
      setDebouncedContainerPort(containerPort);
    }, 350);

    return () => window.clearTimeout(timer);
  }, [containerPort, enabled]);

  const containerPortCheckQuery = useQuery({
    queryKey: ["mcp-tools", `${scope}-container-port-check`, debouncedContainerPort],
    enabled: enabled && typeof debouncedContainerPort === "number",
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

  const isCurrentPortChecked =
    typeof containerPort === "number" &&
    debouncedContainerPort === containerPort &&
    typeof containerPortCheckQuery.data?.available === "boolean";

  const containerPortCheckLoading =
    enabled &&
    typeof containerPort === "number" &&
    !isCurrentPortChecked &&
    !containerPortCheckQuery.isError;

  const containerPortAvailable = containerPortCheckQuery.data?.available === true;

  const ensureContainerPortAvailable = useCallback(async () => {
    return ensureContainerPortAvailableOnce({
      containerPort,
      message,
      t,
    });
  }, [containerPort, message, t]);

  const handleSuggestContainerPort = useCallback(async () => {
    setContainerPortSuggesting(true);
    try {
      const result = await suggestMcpContainerPortService();
      setContainerPort(result.data.port);
      message.success(t("mcpTools.addModal.portSuggested", { port: result.data.port }));
    } catch (error) {
      log.error(`[${logTag}] Failed to suggest container port`, { error });
      message.error(t("mcpTools.addModal.portSuggestFailed"));
    } finally {
      setContainerPortSuggesting(false);
    }
  }, [logTag, message, setContainerPort, t]);

  return {
    containerPortCheckLoading,
    containerPortAvailable,
    containerPortSuggesting,
    handleSuggestContainerPort,
    ensureContainerPortAvailable,
  };
}
