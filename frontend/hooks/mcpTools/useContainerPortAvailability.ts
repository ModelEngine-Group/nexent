import { useCallback, useEffect, useState } from "react";
import { App } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  checkMcpContainerPortConflictService,
  suggestMcpContainerPortService,
} from "@/services/mcpToolsService";

const PORT_CHECK_DEBOUNCE_MS = 350;
const PORT_CHECK_STALE_TIME_MS = 10_000;

/**
 * Checks whether a container port is available. Returns `false` when the port
 * is undefined or already occupied.
 */
export async function checkContainerPortAvailable(
  port: number | undefined
): Promise<boolean> {
  if (typeof port !== "number") return false;
  const result = await checkMcpContainerPortConflictService({ port });
  return result.data.available;
}

type UseContainerPortAvailabilityParams = {
  /** Unique scope so React Query caches port checks per form context. */
  scope: string;
  /** Whether the field is being shown/edited (skips queries when false). */
  enabled: boolean;
  containerPort: number | undefined;
  setContainerPort: (value: number | undefined) => void;
};

/**
 * Owns the port-availability query and the "suggest next free port" mutation.
 */
export function useContainerPortAvailability({
  scope,
  enabled,
  containerPort,
  setContainerPort,
}: UseContainerPortAvailabilityParams) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const [debouncedPort, setDebouncedPort] = useState<number | undefined>(
    undefined
  );
  const [suggesting, setSuggesting] = useState(false);

  useEffect(() => {
    if (!enabled || typeof containerPort !== "number") {
      setDebouncedPort(undefined);
      return;
    }
    const timer = window.setTimeout(
      () => setDebouncedPort(containerPort),
      PORT_CHECK_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [containerPort, enabled]);

  const portCheckQuery = useQuery({
    queryKey: ["mcp-tools", `${scope}-container-port-check`, debouncedPort],
    enabled: enabled && typeof debouncedPort === "number",
    retry: false,
    staleTime: PORT_CHECK_STALE_TIME_MS,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await checkMcpContainerPortConflictService({
        port: debouncedPort as number,
      });
      return result.data;
    },
  });

  const isPortChecked =
    typeof containerPort === "number" &&
    debouncedPort === containerPort &&
    typeof portCheckQuery.data?.available === "boolean";

  const portCheckLoading =
    enabled &&
    typeof containerPort === "number" &&
    !isPortChecked &&
    !portCheckQuery.isError;

  const suggestPort = useCallback(async () => {
    setSuggesting(true);
    try {
      const result = await suggestMcpContainerPortService();
      setContainerPort(result.data.port);
      message.success(
        t("mcpTools.addModal.portSuggested", { port: result.data.port })
      );
    } catch (error) {
      log.error(
        `[useContainerPortAvailability:${scope}] Failed to suggest container port`,
        { error }
      );
      message.error(t("mcpTools.addModal.portSuggestFailed"));
    } finally {
      setSuggesting(false);
    }
  }, [message, scope, setContainerPort, t]);

  return {
    portCheckLoading,
    portAvailable: portCheckQuery.data?.available === true,
    suggesting,
    suggestPort,
  };
}
