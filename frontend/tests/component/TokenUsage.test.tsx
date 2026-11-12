// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({ steps: [] as unknown[] | undefined }));
vi.mock("@assistant-ui/react", () => ({
  useAuiState: () => state.steps,
  useMessageTiming: () => null,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (key === "chat.tokenUsage.unknown" ? "Unknown" : key),
  }),
}));
import { SingleTurnTokenUsage } from "../../app/[locale]/newchat/ui/token-usage";
import {
  stepTokenCounts,
  type StepTokenCount,
} from "../../app/[locale]/newchat/adapter/remote-chat-model-adapter";
afterEach(() => {
  stepTokenCounts.length = 0;
});
beforeEach(() => {
  state.steps = [
    {
      stepNumber: 1,
      duration: 1,
      stepInputTokens: 0,
      stepOutputTokens: 0,
      totalOutputTokens: 0,
      estimatedContextTokens: 0,
      tokenThreshold: null,
      contextWindowTokens: null,
      inputKnown: false,
      outputKnown: false,
    },
  ];
});
it("shows unknown usage with the common component, without inventing zero", () => {
  render(<SingleTurnTokenUsage />);
  expect(screen.getByText(/input Unknown \/.*output Unknown/)).toBeVisible();
  expect(screen.queryByText("0%")).toBeNull();
});
it("keeps an explicit zero distinguishable from unknown", () => {
  (state.steps![0] as Record<string, unknown>).outputKnown = true;
  render(<SingleTurnTokenUsage />);
  expect(screen.getByText(/input Unknown \/.*output 0/)).toBeVisible();
});

it("renders no counters for an explicitly empty saved turn", () => {
  state.steps = [];
  const { container } = render(<SingleTurnTokenUsage />);
  expect(container).toBeEmptyDOMElement();
});

it("never borrows another turn's global usage when metadata is missing", () => {
  stepTokenCounts.push(state.steps![0] as StepTokenCount);
  state.steps = undefined;
  const { container } = render(<SingleTurnTokenUsage />);
  expect(container).toBeEmptyDOMElement();
});

it.each(["passthrough", "adaptive_compact"])(
  "uses the original percentage component with known capacity in %s",
  (mode) => {
    Object.assign(state.steps![0] as Record<string, unknown>, {
      contextWindowTokens: 65536,
      tokenThreshold: 24000,
      stepInputTokens: 655,
      stepOutputTokens: 0,
      inputKnown: true,
      outputKnown: true,
      contextProcessingMode: mode,
    });
    const { container } = render(<SingleTurnTokenUsage />);
    expect(screen.getByRole("button")).toHaveTextContent("1%");
    expect(container.querySelector('[data-token-usage="summary"]')).toBeNull();
  }
);
