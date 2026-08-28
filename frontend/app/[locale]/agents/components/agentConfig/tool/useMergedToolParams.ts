import { useCallback } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";

import { searchToolConfig } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type { Tool, ToolParam } from "@/types/agentConfig";
import log from "@/lib/logger";
import { mergeToolParamValues } from "./utils";

export function useMergedToolParams(currentAgentId?: number) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  return useCallback(
    async (tool: Tool): Promise<ToolParam[] | null> => {
      const params = tool.initParams || [];
      const selectedTools = useAgentStore.getState().editedAgent?.tools ?? [];
      const selectedTool = selectedTools.find(
        (item) => parseInt(item.id) === parseInt(tool.id)
      );
      if (selectedTool) {
        return mergeToolParamValues(
          params,
          Object.fromEntries(
            selectedTool.initParams.map((param) => [param.name, param.value])
          )
        );
      }
      if (!currentAgentId) return params;

      const instance = await searchToolConfig(
        parseInt(tool.id),
        currentAgentId
      );
      if (!instance.success || !instance.data) {
        log.error(
          "Failed to load existing tool configuration:",
          instance.message
        );
        message.error(
          t(
            "nl2agent.resourceBinding.loadExistingConfigFailed",
            "Failed to load the current resource configuration."
          )
        );
        return null;
      }
      return mergeToolParamValues(params, instance.data.params);
    },
    [currentAgentId, message, t]
  );
}
