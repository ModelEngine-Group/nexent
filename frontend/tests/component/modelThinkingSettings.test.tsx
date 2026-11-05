// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import zh from "../../public/locales/zh/common.json";
import en from "../../public/locales/en/common.json";
import type { ModelParameterRule } from "../../types/modelProfile";
import {
  ModelThinkingSettings,
  thinkingEnabled,
} from "../../components/model/ModelThinkingSettings";
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
          toggleRule,
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
const toggleRule: ModelParameterRule = {
  ...effort,
  key: "enable_thinking",
  schema: { type: "boolean" },
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
        rules={[toggleRule, effort, budget]}
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
    rules: [
      toggleRule,
      { ...budget, schema: { type: "integer", minimum: 128 } },
    ],
    outputLimit: 16001,
  });
  expect(screen.getByRole("spinbutton")).toHaveValue("8000");
  expect(changed).toHaveBeenCalledWith("reasoning_budget_tokens", 8000);
});

it("UI-THINKING-09 respects the declared budget minimum", () => {
  const changed = showThinking({
    rules: [
      toggleRule,
      { ...budget, schema: { type: "integer", minimum: 1024, maximum: 1600 } },
    ],
  });
  expect(changed).toHaveBeenCalledWith("reasoning_budget_tokens", 1024);
});

it("UI-THINKING-09 does not invent a budget without either limit", () => {
  const changed = showThinking({
    rules: [toggleRule, { ...budget, schema: { type: "integer" } }],
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

it.each([
  [true, false],
  [false, false],
  [false, true],
])(
  "AEU-01 distinguishes declared budget support from a saved manual preset (declared=%s, limited=%s)",
  (declared, limited) => {
    render(
      <App>
        <ModelThinkingSettings
          rules={[
            toggleRule,
            {
              key: "reasoning_budget_tokens",
              schema: { type: "integer", minimum: 1 },
              source: {
                ref: declared
                  ? "provider_budget_v1"
                  : "operator_thinking_degree_v1",
              },
              visible: true,
              editable: true,
              required: false,
              allowed_scopes: ["outlet"],
              ui_group: "reasoning",
            },
          ]}
          values={{ enable_thinking: true, reasoning_budget_tokens: 1024 }}
          mode="budget_tokens"
          declaredControlsOnly={limited}
          onToggle={vi.fn()}
          onModeChange={vi.fn()}
          onValueChange={vi.fn()}
        />
      </App>
    );
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "modelProfile.thinkingMode" })
    );
    expect(
      screen.getAllByText("modelProfile.thinkingModeOption.budget_tokens")
        .length
    ).toBeGreaterThan(0);
    if (declared || limited) {
      expect(
        screen.queryByText("modelProfile.thinkingModeOption.effort")
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText("modelProfile.manualThinkingHint")
      ).not.toBeInTheDocument();
    } else {
      expect(
        screen.getAllByText("modelProfile.thinkingModeOption.effort").length
      ).toBeGreaterThan(0);
      expect(screen.getByText("modelProfile.manualThinkingHint")).toBeVisible();
    }
  }
);

it("SYNC-02 exposes a declared degree-only profile without an editable toggle", () => {
  render(
    <App>
      <ModelThinkingSettings
        declaredControlsOnly
        rules={[{ ...effort, allowed_scopes: ["outlet", "conversation"] }]}
        values={{}}
        defaults={{ reasoning_effort: "high" }}
        onToggle={vi.fn()}
        onModeChange={vi.fn()}
        onValueChange={vi.fn()}
      />
    </App>
  );
  expect(screen.getByRole("switch")).toBeChecked();
  expect(screen.getByRole("switch")).toBeDisabled();
  expect(
    screen.queryByText("modelProfile.thinkingAlwaysOn")
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("combobox", { name: "modelProfile.thinkingDegree" })
  ).toBeEnabled();
});

it("SYNC-02 preserves explicit off, declared toggle defaults and inactive degree conditions", () => {
  expect(
    thinkingEnabled([toggleRule, effort], {
      enable_thinking: false,
      reasoning_effort: "high",
    })
  ).toBe(false);
  expect(
    thinkingEnabled(
      [
        effort,
        { ...effort, key: "enable_thinking", schema: { type: "boolean" } },
      ],
      { reasoning_effort: "high" }
    )
  ).toBe(false);
  expect(
    thinkingEnabled(
      [{ ...effort, condition: { key: "mode", op: "eq", value: "thinking" } }],
      { mode: "other" }
    )
  ).toBe(false);
});

it.each([false, true])(
  "TD-01 shows the same always-on GLM state in management and Agent (limited=%s)",
  (limited) => {
    const changed = showThinking({
      declaredControlsOnly: limited,
      rules: [
        {
          ...effort,
          schema: { type: "string", enum: ["low", "high", "max"] },
          allowed_scopes: ["outlet", "conversation"],
        },
      ],
      values: { reasoning_effort: "low" },
      defaults: {},
    });
    expect(
      screen.queryByText("modelProfile.thinkingAlwaysOn")
    ).not.toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeChecked();
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByText("低")).toBeVisible();
    fireEvent.click(screen.getByRole("switch"));
    expect(changed).not.toHaveBeenCalled();
  }
);

it("TD-02 treats an effort none as off without inventing a boolean", () => {
  expect(
    thinkingEnabled(
      [
        {
          ...effort,
          schema: { type: "string", enum: ["none", "low", "high"] },
        },
      ],
      { reasoning_effort: "none" }
    )
  ).toBe(false);
});

it("TD-02 maps an effort-only switch onto none and restores a non-off default", () => {
  const onToggle = vi.fn();
  const onValueChange = vi.fn();
  const rule = {
    ...effort,
    allowed_scopes: [
      "outlet",
      "conversation",
    ] as ModelParameterRule["allowed_scopes"],
    schema: { type: "string", enum: ["none", "low", "high"] },
  };
  const view = render(
    <ModelThinkingSettings
      declaredControlsOnly
      rules={[rule]}
      values={{ reasoning_effort: "high" }}
      defaults={{ reasoning_effort: "none" }}
      onToggle={onToggle}
      onModeChange={vi.fn()}
      onValueChange={onValueChange}
    />
  );
  fireEvent.click(screen.getByRole("switch"));
  expect(onValueChange).toHaveBeenLastCalledWith("reasoning_effort", "none");
  expect(onToggle).not.toHaveBeenCalled();
  view.rerender(
    <ModelThinkingSettings
      declaredControlsOnly
      rules={[rule]}
      values={{ reasoning_effort: "none" }}
      defaults={{ reasoning_effort: "none" }}
      onToggle={onToggle}
      onModeChange={vi.fn()}
      onValueChange={onValueChange}
    />
  );
  expect(screen.getByRole("switch")).not.toBeChecked();
  expect(
    screen.getByRole("combobox", { name: "modelProfile.thinkingDegree" })
  ).toBeEnabled();
  fireEvent.click(screen.getByRole("switch"));
  expect(onValueChange).toHaveBeenLastCalledWith("reasoning_effort", "low");
  expect(onToggle).not.toHaveBeenCalled();
});

it("TD-03 distinguishes confirmed always-on reasoning from unknown custom models", () => {
  expect(thinkingEnabled([], {}, true)).toBe(true);
  expect(thinkingEnabled([], {}, false)).toBe(false);
  expect(
    thinkingEnabled([effort], {
      enable_thinking: false,
      reasoning_effort: "low",
    })
  ).toBe(true);
  const changed = showThinking({
    rules: [],
    values: {},
    reasoningSupported: true,
  });
  expect(
    screen.queryByText("modelProfile.thinkingAlwaysOn")
  ).not.toBeInTheDocument();
  expect(screen.getByRole("switch")).toBeChecked();
  expect(screen.getByRole("switch")).toBeDisabled();
  expect(changed).not.toHaveBeenCalled();
});

it("TD-02 keeps a read-only none-effort rule read-only", () => {
  showThinking({
    declaredControlsOnly: true,
    rules: [
      {
        ...effort,
        editable: false,
        schema: { type: "string", enum: ["none", "low"] },
      },
    ],
    values: { reasoning_effort: "none" },
  });
  expect(screen.getByRole("switch")).toBeDisabled();
  expect(
    screen.getByRole("combobox", { name: "modelProfile.thinkingDegree" })
  ).toBeDisabled();
});
