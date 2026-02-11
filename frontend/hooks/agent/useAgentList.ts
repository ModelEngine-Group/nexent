import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAgentList as fetchAgentListService } from "@/services/agentConfigService";
import { useMemo, useEffect } from "react";
import { Agent } from "@/types/agentConfig";

export function useAgentList(tenantId: string | null) {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["agents", tenantId],
		queryFn: async () => {
			const res = await fetchAgentListService(tenantId ?? undefined);
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch agents");
			}
			return res.data || [];
		},
		staleTime: 60_000,
		enabled: !!tenantId,
	});

	const agents = query.data ?? [];

	const availableAgents = useMemo(() => {
		return (agents as Agent[]).filter((a) => a.is_available !== false);
	}, [agents]);

	return {
		...query,
		agents,
		availableAgents,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
	};
}


