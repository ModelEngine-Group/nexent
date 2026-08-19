// ========== Tool Parameter Range Constraints ==========
//
// Numeric range constraints for local tool parameters, mirroring the backend
// table in ``backend/consts/tool_param_constraints.py``.
//
// Keyed by tool name; each entry maps a param name to { type, min, max }.
// min/max use `null` to indicate an unbounded side.
//
// Keep in sync with the matching ``Field(...)`` declarations in the SDK tools
// under ``sdk/nexent/core/tools/`` and the backend constraint table.

export type ToolParamConstraintType = "int" | "float";

export interface ToolParamConstraint {
  type: ToolParamConstraintType;
  min: number | null;
  max: number | null;
}

export type ToolParamRangeConstraints = Record<
  string,
  Record<string, ToolParamConstraint>
>;

export const TOOL_PARAM_RANGE_CONSTRAINTS: ToolParamRangeConstraints = {
  knowledge_base_search: {
    top_k: { type: "int", min: 1, max: 100 },
  },
  dify_search: {
    top_k: { type: "int", min: 1, max: 100 },
  },
  datamate_search: {
    top_k: { type: "int", min: 1, max: 100 },
    threshold: { type: "float", min: 0, max: 1 },
    kb_page: { type: "int", min: 1, max: null },
    kb_page_size: { type: "int", min: 1, max: 100 },
  },
  haotian_search: {
    top_k: { type: "int", min: 1, max: 100 },
    keyword_weight: { type: "float", min: 0, max: 1 },
    vector_weight: { type: "float", min: 0, max: 1 },
  },
  ragflow_search: {
    top_k: { type: "int", min: 1, max: 100 },
    similarity_threshold: { type: "float", min: 0, max: 1 },
    vector_similarity_weight: { type: "float", min: 0, max: 1 },
  },
  idata_search: {
    top_k: { type: "int", min: 1, max: 100 },
    similarity_threshold: { type: "float", min: null, max: 1 },
    keyword_similarity_weight: { type: "float", min: 0, max: 1 },
    vector_similarity_weight: { type: "float", min: 0, max: 1 },
  },
  tavily_search: {
    max_results: { type: "int", min: 1, max: 100 },
  },
  exa_search: {
    max_results: { type: "int", min: 1, max: 100 },
  },
  linkup_search: {
    max_results: { type: "int", min: 1, max: 100 },
  },
  terminal: {
    ssh_port: { type: "int", min: 1, max: 65535 },
  },
  get_email: {
    timeout: { type: "int", min: 1, max: null },
  },
};

/**
 * Get the range constraint for a specific tool and parameter.
 * Returns undefined when no constraint is declared.
 */
export function getToolParamConstraint(
  toolName: string,
  paramName: string
): ToolParamConstraint | undefined {
  const toolConstraints = TOOL_PARAM_RANGE_CONSTRAINTS[toolName];
  if (!toolConstraints) return undefined;
  return toolConstraints[paramName];
}
