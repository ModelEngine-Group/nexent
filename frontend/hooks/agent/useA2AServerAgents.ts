import { useQuery, useQueryClient } from "@tanstack/react-query";
import { a2aClientService, A2AServerAgent } from "@/services/a2aService";

export function useA2AServerAgents() {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["a2aServerAgents"],
		queryFn: async () => {
			const res = await a2aClientService.listServerAgents();
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch A2A server agents");
			}
			return res.data || [];
		},
		staleTime: 60_000,
		enabled: true,
	});

	const agents: A2AServerAgent[] = query.data ?? [];

	return {
		...query,
		agents,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["a2aServerAgents"] }),
	};
}

export function useA2AAgentByAgentId(agentId: number | null) {
	const { agents, ...rest } = useA2AServerAgents();

	const matchingAgent = agentId != null
		? agents.find((a) => a.agent_id === agentId)
		: undefined;

	return {
		...rest,
		a2aAgent: matchingAgent,
		isA2AAgent: !!matchingAgent,
	};
}

export function isAgentA2AServer(agentId: string | number, serverAgents: A2AServerAgent[]): boolean {
	const numericId = typeof agentId === "string" ? Number(agentId) : agentId;
	return serverAgents.some((a) => a.agent_id === numericId);
}
