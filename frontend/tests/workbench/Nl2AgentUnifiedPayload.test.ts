// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { parseNl2aMessage } from "@/app/newchat/adapter/remote-chat-model-adapter";

const card = {
  protocol_version: 2,
  subtype: "requirement_resources",
  purpose: "generate",
  agent_id: 42,
  conversation_id: "c",
  run_id: "r",
  card_id: "card",
  state_version: 1,
  requirements: [],
  resources: [
    {
      candidate: { candidate_ref: "tool:1", resource_type: "tool" },
      recommendation: "recommended",
      is_bound: false,
      readiness: "unbound",
      config: [],
    },
  ],
};

it("accepts the new card only with its purpose and current identity", () => {
  const parse = (value: unknown) =>
    parseNl2aMessage({ type: "nl2a", content: JSON.stringify(value) });
  expect(parse(card)?.content.subtype).toBe("requirement_resources");
  expect(parse({ ...card, purpose: "publish" })).toBeNull();
  expect(parse({ ...card, protocol_version: undefined })).toBeNull();
  expect(parse({ ...card, conversation_id: "" })).toBeNull();
});

it("rejects private configuration and invalid readiness in an initial card payload", () => {
  for (const resource of [
    { ...card.resources[0], config: [{ name: "token", value: "private" }] },
    { ...card.resources[0], readiness: "assumed-ready" },
  ]) {
    expect(
      parseNl2aMessage({
        type: "nl2a",
        content: JSON.stringify({ ...card, resources: [resource] }),
      })
    ).toBeNull();
  }
});

it.each(["requirement_coverage", "resource_recommendation"])(
  "ignores retired %s payloads during live rendering and history replay",
  (subtype) => {
    expect(
      parseNl2aMessage({
        type: "nl2a",
        content: JSON.stringify({ ...card, subtype }),
      })
    ).toBeNull();
  }
);
