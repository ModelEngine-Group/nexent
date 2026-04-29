// hooks/useContainerPortAvailability.ts

import { useCallback, useEffect, useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { 
  checkMcpContainerPortConflictService, 
  suggestMcpContainerPortService 
} from "@/services/mcpToolsService";
import { isValidPort } from "@/lib/mcpTools";

export async function checkContainerPortAvailable(
  port: number | undefined
): Promise<boolean> {
  if (!isValidPort(port)) return false;
  const result = await checkMcpContainerPortConflictService({ port });
  return result.data.available;
}

interface UseContainerPortAvailabilityParams {
  enabled?: boolean;
  containerPort: number | undefined;
  setContainerPort: (value: number | undefined) => void;
}

export function useContainerPortAvailability({
  enabled = true,
  containerPort,
  setContainerPort,
}: UseContainerPortAvailabilityParams) {
  const { t } = useTranslation("common");
  const [portCheckLoading, setPortCheckLoading] = useState(false);
  const [portAvailable, setPortAvailable] = useState<boolean | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  // Check port
  const checkPort = useCallback(async (port: number) => {
    setPortCheckLoading(true);
    try {
      const result = await checkMcpContainerPortConflictService({ port });
      setPortAvailable(result.data.available);
    } catch (error) {
      setPortAvailable(false);
    } finally {
      setPortCheckLoading(false);
    }
  }, []);

  // Anti-shake Auto Check
  useEffect(() => {
    if (!enabled || !isValidPort(containerPort)) {
      // Illegal or not enabled, clear status
      setPortAvailable(null);
      setPortCheckLoading(false);
      return;
    }

    // Legal port, check after debounce

    setPortCheckLoading(true);
    timerRef.current = setTimeout(() => {
      checkPort(containerPort);
    }, 500);

    return () => {
      clearTimeout(timerRef.current);
    };
  }, [containerPort, enabled, checkPort]);

  // Suggest port
  const suggestPort = useCallback(async () => {
    setSuggesting(true);
    try {
      const result = await suggestMcpContainerPortService();
      const port = result.data.port;
      if (isValidPort(port)) {
        setContainerPort(port);
      }
    } catch (error) {
    } finally {
      setSuggesting(false);
    }
  }, [setContainerPort]);

  return {
    portCheckLoading,
    portAvailable,
    suggesting,
    suggestPort,
  };
}