export interface ResourceGapRequirement {
  requirement_id: string;
  query: string;
  resource_name_hint: string | null;
  search_terms: string[];
}

export type ResourceGapRequirementStatus =
  | "unchanged"
  | "editing"
  | "revised"
  | "abandoned"
  | "skill_created"
  | "tool_configured";

export interface ResourceGapRequirementState {
  status: ResourceGapRequirementStatus;
  query: string;
  statusBeforeEditing?: "unchanged" | "revised";
  statusBeforeAbandoning?: "unchanged" | "revised";
}

export interface ResourceGapRequirementActions {
  requirement: Array<"edit" | "delete" | "restore">;
  solutions: Array<"create_skill" | "configure_tool">;
}

export function getResourceGapRequirementActions(
  status: ResourceGapRequirementStatus
): ResourceGapRequirementActions {
  if (status === "abandoned") {
    return { requirement: ["restore"], solutions: [] };
  }
  if (status === "unchanged" || status === "revised") {
    return {
      requirement: ["edit", "delete"],
      solutions: ["create_skill", "configure_tool"],
    };
  }
  return { requirement: [], solutions: [] };
}

export type ResourceGapRequirementStates = Record<
  string,
  ResourceGapRequirementState
>;

export function createResourceGapRequirementStates(
  requirements: ResourceGapRequirement[]
): ResourceGapRequirementStates {
  return Object.fromEntries(
    requirements.map((requirement) => [
      requirement.requirement_id,
      { status: "unchanged", query: requirement.query },
    ])
  );
}

function updateRequirementState(
  states: ResourceGapRequirementStates,
  requirementId: string,
  updater: (state: ResourceGapRequirementState) => ResourceGapRequirementState
): ResourceGapRequirementStates {
  const current = states[requirementId];
  if (!current) return states;
  return { ...states, [requirementId]: updater(current) };
}

export function startResourceGapRequirementEdit(
  states: ResourceGapRequirementStates,
  requirementId: string
): ResourceGapRequirementStates {
  return updateRequirementState(states, requirementId, (state) => {
    if (state.status !== "unchanged" && state.status !== "revised")
      return state;
    return {
      ...state,
      status: "editing",
      statusBeforeEditing: state.status,
    };
  });
}

export function saveResourceGapRequirementEdit(
  states: ResourceGapRequirementStates,
  requirementId: string,
  query: string
): ResourceGapRequirementStates {
  const normalizedQuery = query.trim();
  return updateRequirementState(states, requirementId, (state) => {
    if (state.status !== "editing" || !normalizedQuery) return state;
    return {
      status: "revised",
      query: normalizedQuery,
    };
  });
}

export function cancelResourceGapRequirementEdit(
  states: ResourceGapRequirementStates,
  requirementId: string
): ResourceGapRequirementStates {
  return updateRequirementState(states, requirementId, (state) => {
    if (state.status !== "editing") return state;
    return {
      status: state.statusBeforeEditing ?? "unchanged",
      query: state.query,
    };
  });
}

export function abandonResourceGapRequirement(
  states: ResourceGapRequirementStates,
  requirementId: string
): ResourceGapRequirementStates {
  return updateRequirementState(states, requirementId, (state) => {
    if (state.status !== "unchanged" && state.status !== "revised")
      return state;
    return {
      ...state,
      status: "abandoned",
      statusBeforeAbandoning: state.status,
    };
  });
}

export function restoreResourceGapRequirement(
  states: ResourceGapRequirementStates,
  requirementId: string
): ResourceGapRequirementStates {
  return updateRequirementState(states, requirementId, (state) => {
    if (state.status !== "abandoned") return state;
    return {
      status: state.statusBeforeAbandoning ?? "unchanged",
      query: state.query,
    };
  });
}

export function markResourceGapSkillCreated(
  states: ResourceGapRequirementStates,
  requirementId: string
): ResourceGapRequirementStates {
  return updateRequirementState(states, requirementId, (state) => {
    if (state.status !== "unchanged" && state.status !== "revised")
      return state;
    return { status: "skill_created", query: state.query };
  });
}

export function markResourceGapToolConfigured(
  states: ResourceGapRequirementStates,
  requirementId: string
): ResourceGapRequirementStates {
  return updateRequirementState(states, requirementId, (state) => {
    if (state.status !== "unchanged" && state.status !== "revised")
      return state;
    return { status: "tool_configured", query: state.query };
  });
}

export function canSubmitResourceGapResolution(
  states: ResourceGapRequirementStates
): boolean {
  const values = Object.values(states);
  return (
    !values.some((state) => state.status === "editing") &&
    values.some((state) => state.status !== "unchanged")
  );
}

export function buildResourceGapResolutionResult(
  requirements: ResourceGapRequirement[],
  states: ResourceGapRequirementStates
): {
  requirements: Array<
    | {
        requirement_id: string;
        resolution: "unchanged";
        query: string;
        resource_name_hint: string | null;
        search_terms: string[];
      }
    | { requirement_id: string; resolution: "revised"; query: string }
    | { requirement_id: string; resolution: "skill_created"; query: string }
    | { requirement_id: string; resolution: "tool_configured"; query: string }
  >;
  abandoned_requirement_ids: string[];
} {
  const result = {
    requirements: [] as Array<
      | {
          requirement_id: string;
          resolution: "unchanged";
          query: string;
          resource_name_hint: string | null;
          search_terms: string[];
        }
      | { requirement_id: string; resolution: "revised"; query: string }
      | { requirement_id: string; resolution: "skill_created"; query: string }
      | { requirement_id: string; resolution: "tool_configured"; query: string }
    >,
    abandoned_requirement_ids: [] as string[],
  };

  for (const requirement of requirements) {
    const state = states[requirement.requirement_id];
    if (!state) continue;
    if (state.status === "abandoned") {
      result.abandoned_requirement_ids.push(requirement.requirement_id);
      continue;
    }
    if (
      state.status === "revised" ||
      state.status === "skill_created" ||
      state.status === "tool_configured"
    ) {
      result.requirements.push({
        requirement_id: requirement.requirement_id,
        resolution: state.status,
        query: state.query,
      });
      continue;
    }
    result.requirements.push({
      requirement_id: requirement.requirement_id,
      resolution: "unchanged",
      query: requirement.query,
      resource_name_hint: requirement.resource_name_hint,
      search_terms: requirement.search_terms,
    });
  }

  return result;
}
