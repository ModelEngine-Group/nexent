import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPublishedAgentList as fetchPublishedAgentListService } from "@/services/agentConfigService";
import { useMemo, useEffect } from "react";
import { Agent } from "@/types/agentConfig";

export function usePublishedAgentList() {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["publishedAgentsList"],
		queryFn: async () => {
			const res = await fetchPublishedAgentListService();
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch published agents");
			}
			return res.data || [];
		},
		staleTime: 60_000,
		enabled: true,
	});

	const agents = query.data ?? [];

	const availableAgents = useMemo(() => {
		return (agents as Agent[]).filter((a) => a.is_available !== false);
	}, [agents]);

	return {
		...query,
		agents,
		availableAgents,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["publishedAgents"] }),
	};
}
