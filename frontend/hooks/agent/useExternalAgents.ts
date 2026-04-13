import { useQuery, useQueryClient } from "@tanstack/react-query";
import { a2aClientService, A2AExternalAgent } from "@/services/a2aService";

export function useExternalAgents() {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["externalAgents"],
		queryFn: async () => {
			const res = await a2aClientService.listAgents({ is_available: true });
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch available external agents");
			}
			return res.data || [];
		},
		staleTime: 60_000,
		enabled: true,
	});

	const agents = query.data ?? [];

	const availableAgents = agents.filter((a) => a.is_available !== false);

	return {
		...query,
		agents,
		availableAgents,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["externalAgents"] }),
	};
}
