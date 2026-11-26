// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
export const aidpChannels = [
  "vector_search",
  "full_text_search",
  "graph_search",
];
export const aidpAllChannels = aidpChannels.join("|");
const CHANNEL_FIELDS: Record<string, string[]> = {
  vector_search: ["vector_candidates", "vector_score_threshold"],
  full_text_search: ["full_text_candidates", "full_text_score_threshold"],
  graph_search: [
    "graph_top_k",
    "graph_score_threshold",
    "graph_reranking_enable",
  ],
};
export const aidpDefaults: Record<string, unknown> = {
  search_method: aidpAllChannels,
  top_k: 10,
  score_threshold: 0,
  reranking_enable: true,
  reranking_mode: "performance",
  rewrite_enable: false,
  query_expansion_enable: false,
  related_search_enable: false,
  multi_modal: true,
  vector_candidates: 10,
  full_text_candidates: 10,
  hybrid_top_k: 5,
  graph_top_k: 5,
  vector_score_threshold: 0,
  full_text_score_threshold: 0,
  graph_score_threshold: 0,
  graph_reranking_enable: true,
};
export const isAidpTool = (name?: string | null) =>
  name === "aidp_search" || name === "ind_aidp_search";
export function mergeAidpConfig(
  ...layers: (Record<string, unknown> | undefined | null)[]
) {
  const result: Record<string, unknown> = {};
  for (const layer of layers) {
    for (const [key, value] of Object.entries(layer ?? {})) {
      if (Object.hasOwn(aidpDefaults, key) && value != null)
        result[key] = value;
    }
  }
  return result;
}
export function aidpMethods(method: unknown): string[] {
  return method === "hybrid_search"
    ? [...aidpChannels]
    : typeof method === "string"
      ? [...new Set(method.split("|"))]
      : [];
}
export function resolveAidpConfig(raw: Record<string, unknown>) {
  const result = { ...aidpDefaults, ...mergeAidpConfig(raw) };
  if (!result.reranking_enable) result.graph_reranking_enable = false;
  // Legacy zero caps mean "not set"; treat them as the default.
  if (result.hybrid_top_k === 0)
    result.hybrid_top_k = aidpDefaults.hybrid_top_k;
  if (result.graph_top_k === 0) result.graph_top_k = aidpDefaults.graph_top_k;
  return result;
}
export function aidpErrors(
  raw: Record<string, unknown>
): Record<string, string> {
  const c = resolveAidpConfig(raw),
    errors: Record<string, string> = {};
  const methods = aidpMethods(c.search_method);
  const hybrid = methods.some((m) => m !== "graph_search"),
    graph = methods.includes("graph_search");
  if (!methods.length || methods.some((m) => !aidpChannels.includes(m)))
    errors.search_method = "method";
  const ranges: Record<string, [number, number]> = {
    top_k: [1, 100],
    vector_candidates: [1, 500],
    full_text_candidates: [1, 500],
    hybrid_top_k: [1, 100],
    graph_top_k: [1, 100],
  };
  for (const [key, value] of Object.entries(c)) {
    if (key in ranges) {
      const [min, max] = ranges[key];
      if (
        typeof value !== "number" ||
        !Number.isInteger(value) ||
        value < min ||
        value > max
      )
        errors[key] = "integer";
    } else if (key.endsWith("score_threshold")) {
      if (
        typeof value !== "number" ||
        !Number.isFinite(value) ||
        value < 0 ||
        value > 1
      )
        errors[key] = "threshold";
    } else if (
      typeof aidpDefaults[key] === "boolean" ||
      key === "graph_reranking_enable"
    ) {
      if (typeof value !== "boolean") errors[key] = "boolean";
    }
  }
  if (
    typeof c.reranking_mode !== "string" ||
    !["performance", "high_accuracy", "jargon_coverage"].includes(
      c.reranking_mode
    )
  )
    errors.reranking_mode = "mode";
  if (c.graph_reranking_enable && graph && !c.reranking_enable)
    errors.graph_reranking_enable = "reranking";
  const h = Number(c.hybrid_top_k),
    g = Number(c.graph_top_k),
    k = Number(c.top_k);
  if (hybrid && h > k) errors.hybrid_top_k = "cap";
  if (graph && g > k) errors.graph_top_k = "cap";
  // Omitted caps are filled by AIDP, so the sum check only fires when at
  // least one cap is explicitly customized away from the default.
  if (
    hybrid &&
    graph &&
    (h !== aidpDefaults.hybrid_top_k || g !== aidpDefaults.graph_top_k) &&
    h + g > k
  ) {
    errors.hybrid_top_k = "sum";
    errors.graph_top_k = "sum";
  }
  for (const [method, key] of [
    ["vector_search", "vector_candidates"],
    ["full_text_search", "full_text_candidates"],
  ]) {
    if (methods.includes(method) && h > Number(c[key]))
      errors[key] = "candidates";
  }
  // Hidden fields are not part of the request; stale values must not block save.
  for (const [channel, fields] of Object.entries(CHANNEL_FIELDS))
    if (!methods.includes(channel))
      for (const key of fields) delete errors[key];
  if (!hybrid) delete errors.hybrid_top_k;
  return errors;
}
