import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAgentList as fetchAgentListService } from "@/services/agentConfigService";
import { useMemo } from "react";

export function useAgentList(options?: { enabled?: boolean; staleTime?: number }) {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["agents"],
		queryFn: async () => {
			const res = await fetchAgentListService();
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch agents");
			}
			return res.data || [];
		},
		staleTime: options?.staleTime ?? 60_000,
		enabled: options?.enabled ?? true,
	});

	const agents = query.data ?? [];

	const availableAgents = useMemo(() => {
		return (agents as any[]).filter((a) => a.is_available !== false);
	}, [agents]);


	return {
		...query,
		agents,
		availableAgents,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
	};
}


