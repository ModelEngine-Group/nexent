import { useState } from "react";
import {
  checkAgentNameConflictBatch,
  importAgent,
  regenerateAgentNameBatch,
} from "@/services/agentConfigService";
import log from "@/lib/logger";

export interface ImportAgentData {
  agent_id: number;
  agent_info: Record<string, any>;
  mcp_info?: Array<{
    mcp_server_name: string;
    mcp_url: string;
  }>;
  business_logic_model_id?: number | null;
  business_logic_model_name?: string | null;
}

export interface UseAgentImportOptions {
  onSuccess?: () => void;
  onError?: (error: Error) => void;
  forceImport?: boolean;
  /**
   * Optional: handle name/display_name conflicts before import
   * Caller can resolve by returning new name or choosing to continue/terminate
   */
  onNameConflictResolve?: (payload: {
    name: string;
    displayName?: string;
    conflictAgents: Array<{ id: string; name?: string; display_name?: string }>;
    regenerateWithLLM: () => Promise<{
      name?: string;
      displayName?: string;
    }>;
  }) => Promise<{ proceed: boolean; name?: string; displayName?: string }>;
}

export interface UseAgentImportResult {
  isImporting: boolean;
  importFromFile: (file: File) => Promise<void>;
  importFromData: (data: ImportAgentData) => Promise<void>;
  error: Error | null;
}

/**
 * Unified agent import hook
 * Handles agent import from both file upload and direct data
 * Used in:
 * - Agent development (SubAgentPool)
 * - Agent space (SpaceContent)
 * - Agent market (MarketContent)
 */
export function useAgentImport(
  options: UseAgentImportOptions = {}
): UseAgentImportResult {
  const { onSuccess, onError, forceImport = false } = options;

  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  /**
   * Import agent from uploaded file
   */
  const importFromFile = async (file: File): Promise<void> => {
    setIsImporting(true);
    setError(null);

    try {
      // Read file content
      const fileContent = await readFileAsText(file);
      
      // Parse JSON
      let agentData: ImportAgentData;
      try {
        agentData = JSON.parse(fileContent);
      } catch (parseError) {
        throw new Error("Invalid JSON file format");
      }

      // Validate structure
      if (!agentData.agent_id || !agentData.agent_info) {
        throw new Error("Invalid agent data structure");
      }

      // Import using unified logic
      await importAgentData(agentData);
      
      onSuccess?.();
    } catch (err) {
      const error = err instanceof Error ? err : new Error("Unknown error");
      log.error("Failed to import agent from file:", error);
      setError(error);
      onError?.(error);
      throw error;
    } finally {
      setIsImporting(false);
    }
  };

  /**
   * Import agent from data object (e.g., from market)
   */
  const importFromData = async (data: ImportAgentData): Promise<void> => {
    setIsImporting(true);
    setError(null);

    try {
      // Validate structure
      if (!data.agent_id || !data.agent_info) {
        throw new Error("Invalid agent data structure");
      }

      // Import using unified logic
      await importAgentData(data);
      
      onSuccess?.();
    } catch (err) {
      const error = err instanceof Error ? err : new Error("Unknown error");
      log.error("Failed to import agent from data:", error);
      setError(error);
      onError?.(error);
      throw error;
    } finally {
      setIsImporting(false);
    }
  };

  /**
   * Core import logic - calls backend API
   */
  const importAgentData = async (data: ImportAgentData): Promise<void> => {
    // Step 1: check name/display name conflicts before import (only check main agent name and display name)
    const mainAgent = data.agent_info?.[String(data.agent_id)];
    if (mainAgent?.name) {
      const conflictHandled = await ensureNameNotDuplicated(
        mainAgent.name,
        mainAgent.display_name,
        mainAgent.description || mainAgent.business_description
      );

      if (!conflictHandled.proceed) {
        throw new Error(
          "Agent name/display name conflicts with existing agent; import cancelled."
        );
      }

      // if user chooses to modify name, write back to import data
      if (conflictHandled.name) {
        mainAgent.name = conflictHandled.name;
      }
      if (conflictHandled.displayName) {
        mainAgent.display_name = conflictHandled.displayName;
      }
    }

    const result = await importAgent(data, { forceImport });
    
    if (!result.success) {
      throw new Error(result.message || "Failed to import agent");
    }
  };

  /**
   * Helper: Read file as text
   */
  const readFileAsText = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      
      reader.onload = (e) => {
        const content = e.target?.result;
        if (typeof content === "string") {
          resolve(content);
        } else {
          reject(new Error("Failed to read file content"));
        }
      };
      
      reader.onerror = () => {
        reject(new Error("Failed to read file"));
      };
      
      reader.readAsText(file);
    });
  };

  /**
   * Frontend side name conflict validation logic
   */
  const ensureNameNotDuplicated = async (
    name: string,
    displayName?: string,
    taskDescription?: string
  ): Promise<{ proceed: boolean; name?: string; displayName?: string }> => {
    try {
      const checkResp = await checkAgentNameConflictBatch({
        items: [
          {
            name,
            display_name: displayName,
          },
        ],
      });
      if (!checkResp.success || !Array.isArray(checkResp.data)) {
        log.warn("Skip name conflict check due to fetch failure");
        return { proceed: true };
      }

      const first = checkResp.data[0] || {};
      const { name_conflict, display_name_conflict, conflict_agents } = first;

      if (!name_conflict && !display_name_conflict) {
        return { proceed: true };
      }

      const regenerateWithLLM = async () => {
        const regenResp = await regenerateAgentNameBatch({
          items: [
            {
              name,
              display_name: displayName,
              task_description: taskDescription,
            },
          ],
        });
        if (!regenResp.success || !Array.isArray(regenResp.data) || !regenResp.data[0]) {
          throw new Error("Failed to regenerate agent name");
        }
        const item = regenResp.data[0];
        return {
          name: item.name,
          displayName: item.display_name ?? displayName,
        };
      };

      // let caller decide how to handle conflicts (e.g. show a dialog to let user choose whether to let LLM rename)
      if (options.onNameConflictResolve) {
        return await options.onNameConflictResolve({
          name,
          displayName,
          conflictAgents: (conflict_agents || []).map((c: any) => ({
            id: String(c.agent_id ?? c.id),
            name: c.name,
            display_name: c.display_name,
          })),
          regenerateWithLLM,
        });
      }

      // default behavior: directly call backend to rename to keep import available
      const regenerated = await regenerateWithLLM();
      return { proceed: true, ...regenerated };
    } catch (error) {
      // if callback throws an error, prevent import
      throw error instanceof Error
        ? error
        : new Error("Name conflict handling failed");
    }
  };

  return {
    isImporting,
    importFromFile,
    importFromData,
    error,
  };
}

