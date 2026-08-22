import { useQuery } from "@tanstack/react-query";
import { searchToolConfig } from "@/services/agentConfigService";

export function useToolInfo(toolId: number | null, agentId: number | null) {
	return useQuery({
		queryKey: ["toolInfo", toolId, agentId],
		queryFn: async () => {
			if (!toolId || !agentId) return null;
			const res = await searchToolConfig(toolId, agentId);
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch tool info");
			}
			return res.data;
		},
		enabled: !!toolId && !!agentId,
		staleTime: 60_000,
	});
}
