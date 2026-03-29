import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSkills } from "@/services/agentConfigService";
import { useMemo } from "react";
import { Skill, SkillGroup } from "@/types/agentConfig";

export function useSkillList(options?: { enabled?: boolean; staleTime?: number }) {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: ["skills"],
		queryFn: async () => {
			const res = await fetchSkills();
			if (!res || !res.success) {
				throw new Error(res?.message || "Failed to fetch skills");
			}
			return res.data || [];
		},
		staleTime: options?.staleTime ?? 60_000,
		enabled: options?.enabled ?? true,
	});

	const skills = query.data ?? [];

	const availableSkills = useMemo(() => {
		return skills;
	}, [skills]);

	const groupedSkills = useMemo(() => {
		const groups: SkillGroup[] = [];
		const groupMap = new Map<string, Skill[]>();

		availableSkills.forEach((skill: Skill) => {
			const source = skill.source || "custom";
			const groupKey = source;

			if (!groupMap.has(groupKey)) {
				groupMap.set(groupKey, []);
			}
			groupMap.get(groupKey)!.push(skill);
		});

		groupMap.forEach((groupSkills, key) => {
			const sortedSkills = groupSkills.sort((a, b) => {
				if (!a.update_time && !b.update_time) return 0;
				if (!a.update_time) return 1;
				if (!b.update_time) return -1;
				return b.update_time.localeCompare(a.update_time);
			});

			let label = key;

			groups.push({
				key,
				label,
				skills: sortedSkills,
			});
		});

		return groups.sort((a, b) => {
			const getPriority = (key: string) => {
				if (key === "official") return 1;
				if (key === "custom") return 2;
				if (key === "partner") return 3;
				return 4;
			};
			return getPriority(a.key) - getPriority(b.key);
		});
	}, [availableSkills]);

	return {
		...query,
		skills,
		availableSkills,
		groupedSkills,
		invalidate: () => queryClient.invalidateQueries({ queryKey: ["skills"] }),
	};
}
