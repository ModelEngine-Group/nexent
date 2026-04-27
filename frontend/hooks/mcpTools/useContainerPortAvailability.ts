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

  // 检查端口
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

  // 防抖自动检查
  useEffect(() => {
    if (!enabled || !isValidPort(containerPort)) {
      // 不合法或未启用，清空状态
      setPortAvailable(null);
      setPortCheckLoading(false);
      return;
    }

    // 合法端口，防抖后检查
    setPortCheckLoading(true);
    timerRef.current = setTimeout(() => {
      checkPort(containerPort);
    }, 500);

    return () => {
      clearTimeout(timerRef.current);
    };
  }, [containerPort, enabled, checkPort]);

  // 建议端口
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