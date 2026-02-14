import { useState, useEffect } from "react";
import { fetchTools } from "@/services/agentConfigService";
import log from "@/lib/logger";

export interface LocalTool {
  id: string;
  name: string;
  origin_name?: string;
  description: string;
  description_zh?: string;
  source?: string;
  initParams: any[];
  inputs?: string;
  category?: string;
}

export const useLocalTools = () => {
  const [localTools, setLocalTools] = useState<Record<string, LocalTool>>({});
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const loadLocalTools = async () => {
      try {
        setIsLoading(true);
        const result = await fetchTools();
        if (result.success && result.data) {
          const toolsMap: { [key: string]: LocalTool } = {};
          result.data.forEach((tool: LocalTool) => {
            if (tool.source === "local") {
              toolsMap[tool.name] = tool;
            }
          });
          setLocalTools(toolsMap);
        }
      } catch (error) {
        log.error("Failed to load local tools:", error);
      } finally {
        setIsLoading(false);
      }
    };

    loadLocalTools();
  }, []);

  return { localTools, isLoading };
};
