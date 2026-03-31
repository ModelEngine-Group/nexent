import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSkillInstances } from "@/services/agentConfigService";
import { Skill } from "@/types/agentConfig";

export function useAgentSkillInstances(agentId: number | null, options?: { staleTime?: number }) {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["agentSkillInstances", agentId],
		queryFn: async () => {
			if (!agentId) return [];
			const res = await fetchSkillInstances(agentId);
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch skill instances");
			}
			// Filter only enabled instances and convert to Skill format
			const enabledInstances = (res.data || []).filter(
				(instance: { skill_id: string; enabled: boolean }) => instance.enabled
			);
			// Convert to Skill format for consistency with store
			const skills: Skill[] = enabledInstances.map(
				(instance: { skill_id: string; skill_name?: string; skill_description?: string }) => ({
					skill_id: instance.skill_id,
					name: instance.skill_name || "",
					description: instance.skill_description || "",
					source: "custom",
					tags: [],
					content: "",
				})
			);
			return skills;
		},
		enabled: !!agentId,
		staleTime: options?.staleTime ?? 60_000,
	});

	const skillInstances = query.data ?? [];

	return {
		...query,
		skillInstances,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["agentSkillInstances"] }),
	};
}
