import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "@/services/groupService";
import type { Group } from "@/services/groupService";

export function useGroupList(tenantId: string | null, page?: number, pageSize?: number) {
  const query = useQuery({
    queryKey: ["groups", tenantId, page, pageSize],
    queryFn: () => listGroups(tenantId!, page, pageSize),
    enabled: tenantId !== null,
    staleTime: 1000 * 30,
    refetchOnMount: 'always',
  });

  const allGroupIds = useMemo(
    () => query.data?.groups.map((g) => g.group_id) ?? [],
    [query.data]
  );

  return { ...query, allGroupIds };
}

/**
 * Filter groups by IDs.
 * Takes the full group list from useGroupList and returns only the requested IDs.
 *
 * @param groups - Full group list from useGroupList
 * @param groupIds - Array of group IDs to filter by
 * @returns Filtered groups array in the same order as groupIds
 */
export function useGroupDetails(groups: Group[], groupIds: number[]) {
  const filteredGroups = useMemo(() => {
    const groupsById = new Map(groups.map((g) => [g.group_id, g]));
    return groupIds.map((id) => groupsById.get(id)).filter((g): g is Group => g !== undefined);
  }, [groups, groupIds]);

  return { groups: filteredGroups };
}
