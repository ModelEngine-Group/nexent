import { useMutation } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import { enableMcpToolService } from "@/services/mcpToolsService";
import { MCP_SERVICE_STATUS } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";

type UseMcpToolsToggleParams = {
  loadServerList: () => Promise<unknown>;
  setSelectedService: React.Dispatch<React.SetStateAction<McpServiceItem | null>>;
  t: (key: string) => string;
  message: MessageInstance;
};

export function useMcpToolsToggle({
  loadServerList,
  setSelectedService,
  t,
  message,
}: UseMcpToolsToggleParams) {
  const toggleMutation = useMutation({ mutationFn: enableMcpToolService });

  const toggleServiceStatus = async (service: McpServiceItem) => {
    const nextEnabled = service.status !== MCP_SERVICE_STATUS.ENABLED;
    const result = await toggleMutation.mutateAsync({
      name: service.name,
      enabled: nextEnabled,
    });

    if (!result.success) {
      throw new Error(t("mcpTools.service.toggleFailed"));
    }

    await loadServerList();
    setSelectedService((prev) =>
      prev && prev.name === service.name
        ? {
            ...prev,
            status: nextEnabled ? MCP_SERVICE_STATUS.ENABLED : MCP_SERVICE_STATUS.DISABLED,
          }
        : prev
    );

    message.success(nextEnabled ? t("mcpTools.service.enabled") : t("mcpTools.service.disabled"));
  };

  return {
    toggleServiceStatus,
    toggleMutation,
  };
}
