import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAgentList as fetchAgentListService } from "@/services/agentConfigService";
import { useMemo, useEffect } from "react";

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
	// Listen for cross-tab agent updates via BroadcastChannel
	useEffect(() => {
		let bc: BroadcastChannel | null = null;
		try {
			bc = new BroadcastChannel("nexent-agent-updates");
			bc.onmessage = (ev) => {
				if (ev?.data?.type === "agents_updated") {
					queryClient.invalidateQueries({ queryKey: ["agents"] });
				}
			};
		} catch (e) {
			// ignore if unsupported
		}
		return () => {
			if (bc) bc.close();
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);
	return {
		...query,
		agents,
		availableAgents,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
	};
}


