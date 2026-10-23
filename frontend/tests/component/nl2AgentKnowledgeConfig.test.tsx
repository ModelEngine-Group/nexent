// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import {
  knowledgeToolName,
  knowledgeSelectionIds,
  withKnowledgeSelection,
  mergeKnowledgeConfig,
} from "@/app/newchat/ui/nl2agent-knowledge-config";
import type { Nl2aResourceCandidate } from "@/app/newchat/adapter/remote-chat-model-adapter";
import type { KnowledgeBase } from "@/types/knowledgeBase";

const candidate = (name: string, resource_type = "tool") =>
  ({ name, resource_type }) as Nl2aResourceCandidate;

describe("NL2Agent knowledge presentation configuration", () => {
  it("recognizes managed identity and leaves independent tools and Skills unchanged", () => {
    expect(knowledgeToolName(candidate("knowledge_base_search"))).toBe(
      "knowledge_base_search"
    );
    expect(knowledgeToolName(candidate("aidp_search"))).toBe("aidp_search");
    expect(knowledgeToolName(candidate("ind_aidp_search"))).toBeNull();
    expect(knowledgeToolName(candidate("aidp_search", "skill"))).toBeNull();
    expect(
      knowledgeToolName(candidate("alias"), {
        id: "1",
        name: "alias",
        origin_name: "aidp_search",
        description: "",
        source: "local",
        initParams: [],
      })
    ).toBe("aidp_search");
    expect(
      knowledgeToolName(candidate("aidp_search"), {
        id: "1",
        name: "aidp_search",
        origin_name: "custom_search",
        description: "",
        source: "mcp",
        initParams: [],
      })
    ).toBeNull();
  });

  it.each([undefined, "", "[]", "[invalid", {}, false])(
    "treats missing or malformed selection %j as empty",
    (value) => {
      expect(
        knowledgeSelectionIds(
          [{ name: "kds_list", type: "string", required: false, value }],
          "aidp_search"
        )
      ).toEqual([]);
    }
  );

  it("normalizes local array and legacy CSV selections without losing string IDs", () => {
    expect(
      knowledgeSelectionIds(
        [
          {
            name: "index_names",
            type: "array",
            required: true,
            value: [" idx ", "idx", "", null, {}],
          },
        ],
        "knowledge_base_search"
      )
    ).toEqual(["idx"]);
    expect(
      knowledgeSelectionIds(
        [
          {
            name: "kds_list",
            type: "string",
            required: true,
            value: "001,002",
          },
        ],
        "aidp_search"
      )
    ).toEqual(["001", "002"]);
  });

  it("serializes concrete selections with the backend identity and preserves retrieval settings", () => {
    const kb = {
      id: "001",
      index_name: "stable_index",
      name: "Policy",
    } as KnowledgeBase;
    const params = [
      { name: "top_k", type: "number" as const, required: false, value: 5 },
    ];
    expect(
      withKnowledgeSelection(params, "knowledge_base_search", [kb, kb])
    ).toEqual([
      ...params,
      {
        name: "index_names",
        type: "array",
        required: true,
        value: ["stable_index"],
      },
    ]);
    const aidp = withKnowledgeSelection(
      [
        ...params,
        { name: "api_key", type: "string", required: true, value: "private" },
      ],
      "aidp_search",
      [kb]
    );
    expect(aidp).toEqual([
      ...params,
      { name: "kds_list", type: "string", required: true, value: '["001"]' },
    ]);
    expect(
      knowledgeSelectionIds(
        withKnowledgeSelection(params, "aidp_search", []),
        "aidp_search"
      )
    ).toEqual([]);
  });

  it("hydrates concrete bindings even when selection is absent from the config schema", () => {
    const params = mergeKnowledgeConfig([], "knowledge_base_search", {
      index_names: ["expense_index"],
    });
    expect(knowledgeSelectionIds(params, "knowledge_base_search")).toEqual([
      "expense_index",
    ]);
    expect(
      mergeKnowledgeConfig([], "aidp_search", { kds_list: '["001"]' })
    ).toEqual([
      { name: "kds_list", type: "string", required: true, value: '["001"]' },
    ]);
  });
});
