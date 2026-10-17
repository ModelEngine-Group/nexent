// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ModelThinkingSettings } from "../../components/model/ModelThinkingSettings";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it("starts custom thinking off and hides both degree inputs", () => {
  const toggle = vi.fn();
  render(
    <App>
      <ModelThinkingSettings
        rules={[]}
        values={{}}
        onToggle={toggle}
        onModeChange={vi.fn()}
        onValueChange={vi.fn()}
      />
    </App>
  );
  expect(screen.getByRole("switch")).not.toBeChecked();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("switch"));
  expect(toggle).toHaveBeenCalledWith(true);
});

it("prefills the declared budget and respects its domain", () => {
  render(
    <App>
      <ModelThinkingSettings
        rules={[
          {
            key: "reasoning_budget_tokens",
            schema: { type: "integer", minimum: 128, maximum: 81920 },
            ui_group: "reasoning",
          visible: true,
            editable: true,
            required: false,
            allowed_scopes: ["outlet"],
          },
        ]}
        values={{}}
        defaults={{ enable_thinking: true, reasoning_budget_tokens: 4096 }}
        onToggle={vi.fn()}
        onModeChange={vi.fn()}
        onValueChange={vi.fn()}
      />
    </App>
  );
  expect(screen.getByRole("switch")).toBeChecked();
  expect(
    screen.getByRole("spinbutton", { name: "modelProfile.thinkingDegree" })
  ).toHaveValue("4096");
  expect(screen.getByRole("spinbutton")).toHaveAttribute(
    "aria-valuemin",
    "128"
  );
  expect(screen.getByRole("spinbutton")).toHaveAttribute(
    "aria-valuemax",
    "81920"
  );
});

it("keeps a profile-fixed thinking switch disabled", () => {
  render(
    <App>
      <ModelThinkingSettings
        rules={[
          {
            key: "enable_thinking",
            schema: { type: "boolean" },
            ui_group: "reasoning",
          visible: true,
            editable: false,
            required: false,
            allowed_scopes: ["outlet"],
          },
        ]}
        values={{ enable_thinking: true }}
        onToggle={vi.fn()}
        onModeChange={vi.fn()}
        onValueChange={vi.fn()}
      />
    </App>
  );
  expect(screen.getByRole("switch")).toBeDisabled();
});
