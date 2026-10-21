// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import zh from "../../public/locales/zh/common.json";
import en from "../../public/locales/en/common.json";
import type { ModelParameterRule } from "../../types/modelProfile";
import { ModelThinkingSettings } from "../../components/model/ModelThinkingSettings";
const locale = vi.hoisted(() => ({ value: "zh" }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => {
      if (!key.startsWith("modelProfile.thinkingLevel.")) return key;
      const levels = (locale.value === "zh" ? zh : en).modelProfile
        .thinkingLevel as Record<string, string>;
      return levels[key.split(".").at(-1)!] ?? options?.defaultValue ?? key;
    },
  }),
}));
beforeEach(() => {
  locale.value = "zh";
});

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

const effort: ModelParameterRule = {
  key: "reasoning_effort",
  schema: { type: "string", enum: ["low", "medium", "high"] },
  ui_group: "reasoning",
  visible: true,
  editable: true,
  required: false,
  allowed_scopes: ["outlet"],
};
const budget: ModelParameterRule = {
  ...effort,
  key: "reasoning_budget_tokens",
  schema: { type: "integer", minimum: 128, maximum: 81920 },
};
function showThinking(
  props: Partial<React.ComponentProps<typeof ModelThinkingSettings>> = {}
) {
  const changed = vi.fn();
  render(
    <App>
      <ModelThinkingSettings
        rules={[effort, budget]}
        values={{ enable_thinking: true }}
        onToggle={vi.fn()}
        onModeChange={vi.fn()}
        onValueChange={changed}
        {...props}
      />
    </App>
  );
  return changed;
}

it("UI-THINKING-09 prefers effort when both modes are supported and materializes low in the draft", () => {
  const changed = showThinking();
  expect(screen.getByText("低")).toBeInTheDocument();
  expect(changed).toHaveBeenCalledWith("reasoning_effort", "low");
  expect(
    screen.queryByText("modelProfile.thinkingModeOption.default")
  ).not.toBeInTheDocument();
});

it.each(["zh", "en"])(
  "UI-THINKING-09 translates %s effort labels but submits the original enum",
  async (language) => {
    locale.value = language;
    const changed = showThinking({ rules: [effort] });
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "modelProfile.thinkingDegree" })
    );
    fireEvent.click(await screen.findByText(language === "zh" ? "高" : "High"));
    expect(changed).toHaveBeenLastCalledWith("reasoning_effort", "high");
  }
);

it("UI-THINKING-09 preserves experience budget preference instead of selecting effort", () => {
  const changed = showThinking({ defaults: { reasoning_budget_tokens: 4096 } });
  expect(screen.getByRole("spinbutton")).toHaveValue("4096");
  expect(changed).not.toHaveBeenCalled();
});

it("UI-THINKING-09 preserves saved effort over experience defaults", () => {
  const changed = showThinking({
    values: { enable_thinking: true, reasoning_effort: "high" },
    defaults: { reasoning_effort: "low" },
  });
  expect(screen.getByText("高")).toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
});

it("UI-THINKING-09 fills half the declared budget limit before the output limit", () => {
  const changed = showThinking({ rules: [budget], outputLimit: 16000 });
  expect(screen.getByRole("spinbutton")).toHaveValue("40960");
  expect(changed).toHaveBeenCalledWith("reasoning_budget_tokens", 40960);
});

it("UI-THINKING-09 uses half the output limit when the budget limit is missing", () => {
  const changed = showThinking({
    rules: [{ ...budget, schema: { type: "integer", minimum: 128 } }],
    outputLimit: 16001,
  });
  expect(screen.getByRole("spinbutton")).toHaveValue("8000");
  expect(changed).toHaveBeenCalledWith("reasoning_budget_tokens", 8000);
});

it("UI-THINKING-09 respects the declared budget minimum", () => {
  const changed = showThinking({
    rules: [
      { ...budget, schema: { type: "integer", minimum: 1024, maximum: 1600 } },
    ],
  });
  expect(changed).toHaveBeenCalledWith("reasoning_budget_tokens", 1024);
});

it("UI-THINKING-09 does not invent a budget without either limit", () => {
  const changed = showThinking({
    rules: [{ ...budget, schema: { type: "integer" } }],
  });
  expect(screen.getByRole("spinbutton")).toHaveValue("");
  expect(changed).not.toHaveBeenCalled();
});

it("UI-THINKING-09 does not add degree parameters while thinking is off", () => {
  const changed = showThinking({
    values: { enable_thinking: false },
    layout: "panel",
  });
  expect(
    screen.queryByRole("combobox", { name: "modelProfile.thinkingDegree" })
  ).not.toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
});

it("UI-THINKING-09 waits for the current preview before materializing fallback values", () => {
  const changed = showThinking({ prefillReady: false });
  expect(changed).not.toHaveBeenCalled();
  expect(screen.queryByText("低")).not.toBeInTheDocument();
});
