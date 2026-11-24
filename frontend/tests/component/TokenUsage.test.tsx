// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
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

it("shows peak request context instead of cumulative usage across steps", () => {
  state.steps = [
    {
      stepNumber: 1,
      stepInputTokens: 12000,
      stepOutputTokens: 1000,
      contextWindowTokens: 16000,
      tokenThreshold: 12800,
      inputKnown: true,
      outputKnown: true,
    },
    {
      stepNumber: 2,
      stepInputTokens: 12000,
      stepOutputTokens: 2000,
      contextWindowTokens: 16000,
      tokenThreshold: 12800,
      inputKnown: true,
      outputKnown: true,
    },
  ];

  render(<SingleTurnTokenUsage />);

  expect(screen.getByRole("button")).toHaveTextContent("75%");
  expect(screen.getByRole("button")).not.toHaveTextContent("150%");
});

it("compares each request with its own context window", () => {
  state.steps = [
    {
      stepNumber: 1,
      stepInputTokens: 6000,
      stepOutputTokens: 0,
      contextWindowTokens: 8000,
      tokenThreshold: null,
      inputKnown: true,
      outputKnown: true,
    },
    {
      stepNumber: 2,
      stepInputTokens: 12000,
      stepOutputTokens: 0,
      contextWindowTokens: 32000,
      tokenThreshold: null,
      inputKnown: true,
      outputKnown: true,
    },
  ];

  render(<SingleTurnTokenUsage />);

  expect(screen.getByRole("button")).toHaveTextContent("75%");
  fireEvent.click(screen.getByRole("button"));
  expect(screen.getByText("6,000 / 8,000")).toBeVisible();
});

it("does not treat generated output as request context input", () => {
  Object.assign(state.steps![0] as Record<string, unknown>, {
    contextWindowTokens: 16000,
    stepInputTokens: 4000,
    stepOutputTokens: 12000,
    inputKnown: true,
    outputKnown: true,
  });

  render(<SingleTurnTokenUsage />);

  expect(screen.getByRole("button")).toHaveTextContent("25%");
});

it("uses known requests when another step has unknown usage", () => {
  state.steps = [
    {
      stepNumber: 1,
      stepInputTokens: 8000,
      stepOutputTokens: 0,
      contextWindowTokens: 16000,
      tokenThreshold: null,
      inputKnown: true,
      outputKnown: false,
    },
    {
      stepNumber: 2,
      stepInputTokens: 0,
      stepOutputTokens: 0,
      contextWindowTokens: 16000,
      tokenThreshold: null,
      inputKnown: false,
      outputKnown: false,
    },
  ];

  render(<SingleTurnTokenUsage />);

  expect(screen.getByRole("button")).toHaveTextContent("50%");
});
