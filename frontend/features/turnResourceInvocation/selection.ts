import type { Skill } from "@/types/agentConfig";

import type {
  TurnResourceCommandDefinition,
  TurnResourceRequest,
  TurnResourceSelection,
} from "./types";

export const MAX_TURN_RESOURCES = 5;

export function createCommandSelection(
  definition: TurnResourceCommandDefinition,
  label: string,
  description: string
): TurnResourceSelection {
  return {
    key: `command:${definition.id}`,
    resourceType: definition.resourceType,
    mode: definition.mode,
    label,
    description,
    command: definition,
  };
}

export function createSkillSelection(skill: Skill): TurnResourceSelection {
  return {
    key: `skill:${skill.skill_id}`,
    resourceType: "skill",
    mode: "augment",
    label: skill.name,
    description: skill.description,
    reference: {
      resource_type: "skill",
      resource_id: String(skill.skill_id),
      name: skill.name,
    },
  };
}

export function addTurnResourceSelection(
  current: TurnResourceSelection[],
  selection: TurnResourceSelection
): TurnResourceSelection[] {
  if (selection.mode === "intercept") return [selection];

  const augmentSelections = current.filter((item) => item.mode === "augment");
  if (augmentSelections.some((item) => item.key === selection.key)) {
    return augmentSelections;
  }
  return [...augmentSelections, selection].slice(0, MAX_TURN_RESOURCES);
}

export function buildTurnResourceRequest(
  selections: TurnResourceSelection[]
): TurnResourceRequest | undefined {
  const resources = selections.flatMap((selection) =>
    selection.mode === "augment" && selection.reference
      ? [selection.reference]
      : []
  );
  return resources.length > 0 ? { mode: "required", resources } : undefined;
}

export function getInterceptSelection(
  selections: TurnResourceSelection[]
): TurnResourceSelection | undefined {
  return selections.find((selection) => selection.mode === "intercept");
}
