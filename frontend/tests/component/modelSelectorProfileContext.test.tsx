// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelSelector } from "../../app/[locale]/newchat/ui/model-selector";

const context = vi.hoisted(() => ({
  register: vi.fn(
    (_entry: { getModelContext: () => { config: Record<string, unknown> } }) =>
      vi.fn()
  ),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ modelContext: () => context }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
beforeEach(() => context.register.mockClear());

it.each([true, false])(
  "retains legacy controls only for legacy selections (profile=%s)",
  async (profile) => {
    render(
      <ModelSelector
        models={[
          {
            id: "42",
            name: "Model",
            efforts: [{ id: "high", name: "high" }],
            profileSchemaVersion: profile ? 1 : undefined,
          },
        ]}
        value="42"
        showEffort={true}
        deepThinking={true}
        effort="high"
      />
    );
    await waitFor(() => expect(context.register).toHaveBeenCalled());
    const entry = context.register.mock.calls.at(-1)![0] as {
      getModelContext: () => { config: Record<string, unknown> };
    };
    const config = entry.getModelContext().config;
    expect(config.modelName).toBe("42");
    if (profile) {
      expect(
        screen.queryByText("chat.modelSelector.effort.high")
      ).not.toBeInTheDocument();
      expect(config).not.toHaveProperty("deepThinking");
      expect(config).not.toHaveProperty("reasoningEffort");
      expect(config).not.toHaveProperty("reasoningBudgetTokens");
    } else {
      expect(screen.getByText("chat.modelSelector.effort.high")).toBeVisible();
      expect(config.deepThinking).toBe(true);
      expect(config.reasoningEffort).toBe("high");
    }
  }
);
