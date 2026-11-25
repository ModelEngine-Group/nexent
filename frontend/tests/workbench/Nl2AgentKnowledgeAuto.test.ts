// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { expect, it } from "vitest";
import {
  reducer,
  initializeItems,
} from "@/app/newchat/ui/nl2agent-binding-state";
import { knowledgeSelectionIds } from "@/app/newchat/ui/nl2agent-knowledge-config";

it("seeds a default once but never overwrites a manual empty knowledge selection", () => {
  const items = initializeItems([
    {
      candidate: {
        candidate_ref: "tool:1",
        resource_type: "tool",
        source: "LOCAL_TOOL",
        name: "knowledge_base_search",
        description: "",
        requirement_ids: ["r1"],
        score: 0.9,
      },
      recommendation: "recommended",
      is_bound: false,
      form_kind: "TOOL_CONFIG",
      config: [],
    },
  ]);
  const prepared = {
    candidate_ref: "tool:1",
    tool_name: "knowledge_base_search" as const,
    recommendations: [],
    selected_values: ["expense"],
    selection_source: "recommended" as const,
    settings: { top_k: 8 },
    models: {},
    mode: "text" as const,
  };
  const action = {
    type: "knowledge_prepared" as const,
    ref: "tool:1",
    prepared,
    params: [
      { name: "top_k", type: "number" as const, required: false, value: 5 },
    ],
  };
  const seeded = reducer(items, action);
  expect(
    knowledgeSelectionIds(seeded[0].draftParams, "knowledge_base_search")
  ).toEqual(["expense"]);
  expect(
    seeded[0].draftParams.find((param) => param.name === "top_k")?.value
  ).toBe(8);
  const edited = reducer(seeded, {
    type: "save_config",
    ref: "tool:1",
    params: [{ name: "index_names", type: "array", required: true, value: [] }],
    knowledgeEdited: true,
  });
  const refreshed = reducer(edited, action);
  expect(
    knowledgeSelectionIds(refreshed[0].draftParams, "knowledge_base_search")
  ).toEqual([]);
});
