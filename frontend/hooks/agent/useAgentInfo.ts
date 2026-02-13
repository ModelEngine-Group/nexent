import { useQuery } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { searchAgentInfo } from "@/services/agentConfigService";

export function useAgentInfo(agentId: number | null) {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["agentInfo", agentId],
		queryFn: async () => {
			if (!agentId) return null;
			const res = await searchAgentInfo(agentId);
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch agent info");
			}
			return res.data;
		},
		enabled: !!agentId,
		staleTime: 60_000,
	});

	const agentInfo = query.data ?? null;

	return {
		...query,
		agentInfo,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["agentInfo"] }),
	};
}
