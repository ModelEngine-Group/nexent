// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AgentSuggestionItem } from "@/types/agentSuggestion";

/** Cap shown on the welcome suggestion cards. */
const MAX_SUGGESTIONS = 4;

/**
 * Derive the welcome suggestion cards: preset suggestions win when provided,
 * otherwise fall back to the agent's example questions. Blank entries
 * (empty strings, whitespace, or i18n values resolving to empty text) are
 * dropped before the cap so they never occupy a card slot or render an
 * empty, clickable card.
 */
export function deriveWelcomeSuggestions(
  welcomeSuggestions: readonly AgentSuggestionItem[] | undefined,
  exampleQuestions: readonly string[] | undefined
): AgentSuggestionItem[] {
  if (welcomeSuggestions?.length) {
    return welcomeSuggestions
      .filter((item) => item.title.trim() && item.prompt.trim())
      .slice(0, MAX_SUGGESTIONS);
  }
  return (exampleQuestions || [])
    .filter((question) => question.trim())
    .slice(0, MAX_SUGGESTIONS)
    .map((question, index) => ({
      id: `question-${index}`,
      title: question,
      prompt: question,
    }));
}
