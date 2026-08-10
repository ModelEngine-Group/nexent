import type { Group } from "@/services/groupService";

export interface GroupSelectOption {
  label: string;
  value: number;
}

/**
 * Build Select options for user groups, including fallback labels for deleted groups
 * that are still referenced by the current selection.
 */
export function buildGroupSelectOptions(params: {
  groups: Group[];
  allGroups: Group[];
  selectedGroupIds: number[] | undefined;
  deletedGroupLabel: string;
}): GroupSelectOption[] {
  const { groups, allGroups, selectedGroupIds, deletedGroupLabel } = params;
  const existingGroupIds = new Set(allGroups.map((group) => group.group_id));
  const baseOptions = groups.map((group) => ({
    label: group.group_name,
    value: group.group_id,
  }));
  const baseValueSet = new Set(baseOptions.map((option) => option.value));
  const orphanOptions = (selectedGroupIds ?? [])
    .filter(
      (id): id is number =>
        typeof id === "number" &&
        !existingGroupIds.has(id) &&
        !baseValueSet.has(id)
    )
    .map((id) => ({
      label: deletedGroupLabel,
      value: id,
    }));

  return [...baseOptions, ...orphanOptions];
}
