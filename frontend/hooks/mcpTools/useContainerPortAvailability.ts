import { useCallback, useEffect, useState } from "react";
import { App } from "antd";
import { useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  checkMcpContainerPortConflictService,
  suggestMcpContainerPortService,
} from "@/services/mcpToolsService";

const PORT_CHECK_DEBOUNCE_MS = 350;
const PORT_CHECK_STALE_TIME_MS = 10_000;

type EnsureContainerPortAvailableParams = {
  containerPort: number | undefined;
  message: MessageInstance;
  translate: (key: string, params?: Record<string, unknown>) => string;
};

/**
 * Standalone helper to validate a container port right before a submit. Callers
 * pass the already-bound `message` and translator so this can run outside of a
 * component render cycle.
 */
export async function ensureContainerPortAvailableOnce({
  containerPort,
  message,
  translate,
}: EnsureContainerPortAvailableParams): Promise<boolean> {
  if (typeof containerPort !== "number") {
    return false;
  }

  const portCheck = await checkMcpContainerPortConflictService({
    port: containerPort,
  });

  if (!portCheck.data.available) {
    message.error(
      translate("mcpTools.addModal.portOccupied", { port: containerPort })
    );
    return false;
  }

  return true;
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
 * Keeps i18n and toasts internal so the component only renders state.
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
