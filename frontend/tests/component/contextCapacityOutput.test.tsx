// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { parseStepTokenCount } from "@/app/newchat/adapter/remote-chat-model-adapter";

it.each(["passthrough", "adaptive_compact"])(
  "reads server capacity in %s mode",
  (mode) => {
    const value = parseStepTokenCount(
      JSON.stringify({
        step_number: 1,
        step_input_tokens: 0,
        step_output_tokens: null,
        context_window_tokens: 100000,
        token_threshold: 80000,
        effective_input_limit_tokens: 70000,
        context_processing_mode: mode,
      })
    );
    expect(value).toMatchObject({
      stepInputTokens: 0,
      inputKnown: true,
      outputKnown: false,
      contextWindowTokens: 100000,
      tokenThreshold: 80000,
    });
  }
);
