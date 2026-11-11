// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelSelector } from "../../app/[locale]/newchat/ui/model-selector";
const context = vi.hoisted(() => ({
  register: vi.fn((_entry: unknown) => vi.fn()),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ modelContext: () => context }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
beforeEach(() => context.register.mockClear());
it.each([1, undefined])(
  "SU-AC-07 model context carries identity only, never a parallel parameter snapshot (schema=%s)",
  async (schema) => {
    render(
      <ModelSelector
        models={[{ id: "42", name: "Model", profileSchemaVersion: schema }]}
        value="42"
      />
    );
    await waitFor(() => expect(context.register).toHaveBeenCalled());
    const entry = context.register.mock.calls.at(-1)![0] as {
      getModelContext: () => unknown;
    };
    expect(entry.getModelContext()).toEqual({ config: { modelName: "42" } });
  }
);
