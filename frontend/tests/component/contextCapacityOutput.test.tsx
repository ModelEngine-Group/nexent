// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import {
  createNexentOutputAdapter,
  normalizeNexentHistory,
} from "@/lib/nexentOutputAdapter";

const capacity = {
  context_window_tokens: 65536,
  token_threshold: 24000,
  effective_input_limit_tokens: 32000,
  context_processing_mode: "passthrough",
};
const event = {
  type: "step_observation",
  content: "",
  schema_version: 1,
  runtime_mode: "native_agent",
  turn_id: "turn",
  sequence: 1,
  step_number: 1,
  duration: 0.2,
  context_capacity: capacity,
  usage: { input_tokens: 24, output_tokens: 3 },
};

it.each(["passthrough", "adaptive_compact"])(
  "maps shared capacity in live and saved %s output",
  (mode) => {
    const e = {
      ...event,
      context_capacity: { ...capacity, context_processing_mode: mode },
    };
    const live = createNexentOutputAdapter()
      .push(e)
      .find((e) => e.type === "token_count")!;
    const saved = normalizeNexentHistory([
      { type: e.type, content: JSON.stringify(e) },
    ]).events.find((e) => e.type === "token_count")!;
    const expected = {
      ...capacity,
      context_processing_mode: mode,
      step_input_tokens: 24,
      step_output_tokens: 3,
    };
    expect(JSON.parse(live.content)).toMatchObject(expected);
    expect(JSON.parse(saved.content)).toMatchObject(expected);
  }
);

it("keeps legacy missing capacity unknown instead of inventing another run's values", () => {
  const adapter = createNexentOutputAdapter();
  adapter.push(event);
  const e = adapter
    .push({ ...event, turn_id: "other", context_capacity: undefined })
    .find((e) => e.type === "token_count")!;
  expect(JSON.parse(e.content)).toMatchObject({
    context_window_tokens: null,
    token_threshold: null,
  });
});
