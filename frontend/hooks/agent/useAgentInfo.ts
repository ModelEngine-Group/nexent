import { useCallback, useEffect, useState } from "react";

import { searchAgentInfo } from "@/services/agentConfigService";
import type { Agent } from "@/types/agentConfig";

type UseAgentInfoResult = {
  agentInfo: Agent | null;
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<Agent | null>;
};

export function useAgentInfo(
  agentId: number | null | undefined
): UseAgentInfoResult {
  const [agentInfo, setAgentInfo] = useState<Agent | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async (): Promise<Agent | null> => {
    if (!agentId) {
      setAgentInfo(null);
      setError(null);
      return null;
    }

    setIsLoading(true);
    setError(null);

    try {
      const result = await searchAgentInfo(agentId);
      if (!result?.success || !result.data) {
        throw new Error(result?.message || "Failed to fetch agent info");
      }
      setAgentInfo(result.data);
      return result.data;
    } catch (requestError) {
      const nextError =
        requestError instanceof Error
          ? requestError
          : new Error("Failed to fetch agent info");
      setError(nextError);
      throw nextError;
    } finally {
      setIsLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    let isActive = true;

    if (!agentId) {
      setAgentInfo(null);
      setError(null);
      setIsLoading(false);
      return () => {
        isActive = false;
      };
    }

    setIsLoading(true);
    setError(null);

    void searchAgentInfo(agentId)
      .then((result) => {
        if (!isActive) return;
        if (!result?.success || !result.data) {
          throw new Error(result?.message || "Failed to fetch agent info");
        }
        setAgentInfo(result.data);
      })
      .catch((requestError: unknown) => {
        if (!isActive) return;
        setError(
          requestError instanceof Error
            ? requestError
            : new Error("Failed to fetch agent info")
        );
      })
      .finally(() => {
        if (isActive) setIsLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [agentId]);

  return { agentInfo, isLoading, error, refetch };
}
