import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPublishedAgentList as fetchPublishedAgentListService } from "@/services/agentConfigService";
import { useMemo, useState, useCallback } from "react";
import { Agent } from "@/types/agentConfig";

interface UsePublishedAgentListOptions {
	page?: number;
	pageSize?: number;
}

export function usePublishedAgentList({
	page = 1,
	pageSize = Number.MAX_SAFE_INTEGER,
}: UsePublishedAgentListOptions = {}) {
	const queryClient = useQueryClient();
	const [search, setSearch] = useState("");

	const query = useQuery({
		queryKey: ["publishedAgentsList"],
		queryFn: async () => {
			const res = await fetchPublishedAgentListService();
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch published agents");
			}
			return (res.data || []) as Agent[];
		},
		staleTime: 60_000,
		refetchOnMount: "always",
		enabled: true,
	});

	const agents = query.data ?? [];

	const filteredAgents = useMemo(() => {
		const trimmedSearch = search.trim();
		const searchFiltered = (() => {
			if (!trimmedSearch) {
				return agents;
			}
			const searchLower = trimmedSearch.toLowerCase();
			return agents.filter((agent) => {
				const name = agent.name?.toLowerCase() || "";
				const displayName = agent.display_name?.toLowerCase() || "";
				const description = agent.description?.toLowerCase() || "";
				const author = agent.author?.toLowerCase() || "";
				return (
					name.includes(searchLower) ||
					displayName.includes(searchLower) ||
					description.includes(searchLower) ||
					author.includes(searchLower)
				);
			});
		})();
		return searchFiltered;
	}, [agents, search]);

	const totalPages = useMemo(() => {
		return Math.max(1, Math.ceil(filteredAgents.length / pageSize));
	}, [filteredAgents.length, pageSize]);

	const paginatedAgents = useMemo(() => {
		const startIndex = (page - 1) * pageSize;
		return filteredAgents.slice(startIndex, startIndex + pageSize);
	}, [filteredAgents, page, pageSize]);

	const availableAgents = useMemo(() => {
		return agents.filter((a) => a.is_available !== false);
	}, [agents]);

	const updateSearch = useCallback((value: string) => {
		setSearch(value);
	}, []);

	return {
		...query,
		agents,
		availableAgents,
		paginatedAgents,
		filteredAgents,
		page,
		totalPages,
		pageSize,
		search,
		updateSearch,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["publishedAgentsList"] }),
	};
}