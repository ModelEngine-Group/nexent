// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import {
  outletSamplingRules,
  outletSamplingValues,
  samplingComplete,
} from "../../lib/modelSamplingParameters";

it("UI-SAMPLING-10 exposes both required controls without a provider or known capability", () => {
  const rules = outletSamplingRules([]);
  expect(rules.map((rule) => rule.key)).toEqual(["temperature", "top_p"]);
  expect(rules.every((rule) => rule.visible && rule.required)).toBe(true);
});

it("UI-SAMPLING-10 preserves an existing fixed parameter domain", () => {
  const original = {
    ...outletSamplingRules([])[0],
    visible: false,
    editable: false,
    schema: { type: "number", minimum: 0, maximum: 1 },
  };
  expect(outletSamplingRules([original])[0]).toMatchObject({
    visible: true,
    required: true,
    editable: false,
    schema: original.schema,
  });
  expect(original.visible).toBe(false);
});

it("UI-SAMPLING-10 preserves explicit zero and experience values above initial defaults", () => {
  expect(
    outletSamplingValues({ temperature: 0 }, { temperature: 0.8, top_p: 0.9 })
  ).toEqual({ temperature: 0, top_p: 0.9 });
  expect(outletSamplingValues({})).toEqual({ temperature: 0.7, top_p: 1 });
});

it.each([null, undefined, "0.7", Number.NaN, Number.POSITIVE_INFINITY])(
  "UI-SAMPLING-10 rejects missing or nonnumeric required values (%s)",
  (value) => {
    expect(samplingComplete({ temperature: value, top_p: 1 })).toBe(false);
    expect(samplingComplete({ temperature: 0.7, top_p: value })).toBe(false);
  }
);
