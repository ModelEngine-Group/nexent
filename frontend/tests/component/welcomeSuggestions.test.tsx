// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";

import { deriveWelcomeSuggestions } from "../../app/[locale]/newchat/assistant-ui/welcome-suggestions";
import type { AgentSuggestionItem } from "@/types/agentSuggestion";

const suggestion = (
  overrides: Partial<AgentSuggestionItem>
): AgentSuggestionItem => ({
  id: "s1",
  title: "Title",
  prompt: "Prompt",
  ...overrides,
});

describe("deriveWelcomeSuggestions", () => {
  it("prefers preset suggestions when provided", () => {
    const presets = [suggestion({ id: "a" }), suggestion({ id: "b" })];

    expect(deriveWelcomeSuggestions(presets, ["Question 1"])).toEqual(presets);
  });

  it("drops blank preset suggestions before the cap", () => {
    // Blank cards must not consume the four card slots: a whitespace title
    // or an empty prompt (e.g. an i18n key resolving to empty text) would
    // otherwise render an empty, clickable card.
    const presets = [
      suggestion({ id: "blank-title", title: "   " }),
      suggestion({ id: "blank-prompt", prompt: "" }),
      ...Array.from({ length: 4 }, (_, i) => suggestion({ id: `ok-${i}` })),
    ];

    const result = deriveWelcomeSuggestions(presets, undefined);

    expect(result.map((item) => item.id)).toEqual([
      "ok-0",
      "ok-1",
      "ok-2",
      "ok-3",
    ]);
  });

  it("caps preset suggestions at four", () => {
    const presets = Array.from({ length: 6 }, (_, i) =>
      suggestion({ id: `s-${i}` })
    );

    expect(deriveWelcomeSuggestions(presets, undefined)).toHaveLength(4);
  });

  it("falls back to example questions, dropping blanks before the cap", () => {
    const result = deriveWelcomeSuggestions(undefined, [
      "",
      "   ",
      "Q1",
      "Q2",
      "Q3",
      "Q4",
      "Q5",
    ]);

    expect(result).toEqual([
      { id: "question-0", title: "Q1", prompt: "Q1" },
      { id: "question-1", title: "Q2", prompt: "Q2" },
      { id: "question-2", title: "Q3", prompt: "Q3" },
      { id: "question-3", title: "Q4", prompt: "Q4" },
    ]);
  });

  it("falls back to example questions when presets are empty", () => {
    expect(deriveWelcomeSuggestions([], ["Q"])).toEqual([
      { id: "question-0", title: "Q", prompt: "Q" },
    ]);
  });

  it("returns an empty list when nothing usable is provided", () => {
    expect(deriveWelcomeSuggestions(undefined, undefined)).toEqual([]);
    expect(deriveWelcomeSuggestions(undefined, [])).toEqual([]);
    expect(deriveWelcomeSuggestions([], [])).toEqual([]);
    expect(
      deriveWelcomeSuggestions([suggestion({ title: "", prompt: "" })], [""])
    ).toEqual([]);
  });
});
