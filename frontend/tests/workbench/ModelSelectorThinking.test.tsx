// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
import { ModelSelector } from "@/app/newchat/ui/model-selector";

const register = vi.hoisted(() =>
  vi.fn((entry: { getModelContext: () => unknown }) => {
    void entry;
    return () => undefined;
  })
);
const modelApi = vi.hoisted(() => ({
  modelContext: () => ({ register }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => modelApi,
}));
vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  PopoverContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@/components/ui/command", () => ({
  Command: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CommandInput: () => <input />,
  CommandList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CommandEmpty: () => null,
  CommandGroup: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  CommandItem: ({
    children,
    onSelect,
    value,
  }: {
    children: ReactNode;
    onSelect?: (value: string) => void;
    value: string;
  }) => (
    <button type="button" onClick={() => onSelect?.(value)}>
      {children}
    </button>
  ),
  CommandSeparator: () => null,
}));

const models = [{ id: "12", name: "Qwen", efforts: true }];

it("does not fabricate options when the selected model has no supported effort controls", async () => {
  render(
    <ModelSelector
      models={[{ id: "12", name: "Plain Model" }]}
      value="12"
      effort="high"
      showEffort
    />
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("switch"));
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByText("High")).toBeNull();
  expect(register.mock.lastCall?.[0].getModelContext()).toMatchObject({
    config: { modelName: "12", deepThinking: false },
  });
  const config = register.mock.lastCall?.[0].getModelContext() as {
    config: Record<string, unknown>;
  };
  expect(config.config).not.toHaveProperty("reasoningEffort");
});

const localizedEfforts = [
  ["auto", "自动", "auto"],
  ["none", "无", "None"],
  ["minimal", "最低", "Minimal"],
  ["low", "低", "Low"],
  ["medium", "中", "Medium"],
  ["high", "高", "High"],
  ["xhigh", "极高", "Extra high"],
  ["max", "最高", "Maximum"],
] as const;

it.each(["zh", "en"] as const)(
  "localizes every supported effort in %s without changing model context or callbacks",
  async (language) => {
    const i18n = createInstance();
    await i18n.init({
      lng: language,
      fallbackLng: false,
      keySeparator: false,
      resources: { zh: { translation: zh }, en: { translation: en } },
    });
    const changed = vi.fn();
    const capability = {
      status: "supported" as const,
      control: "effort" as const,
      levels: localizedEfforts.map(([id]) => id),
      source: "catalog" as const,
    };
    const choices = [
      {
        id: "12",
        name: "Qwen",
        efforts: localizedEfforts.map(([id]) => ({ id, name: id })),
        reasoningCapability: capability,
      },
    ];
    const view = (thinking: boolean) => (
      <I18nextProvider i18n={i18n}>
        <ModelSelector
          models={choices}
          value="12"
          defaultEffort="max"
          deepThinking={thinking}
          onEffortChange={changed}
        />
      </I18nextProvider>
    );
    const { rerender } = render(view(true));
    const user = userEvent.setup();
    for (const [id, chinese, english] of localizedEfforts) {
      const label = language === "zh" ? chinese : english;
      await user.click(screen.getByRole("combobox"));
      await user.click(screen.getByText(label, { exact: true }));
      expect(changed).toHaveBeenLastCalledWith(id);
      expect(screen.getByRole("combobox")).toHaveTextContent(label);
      expect(register.mock.lastCall?.[0].getModelContext()).toEqual({
        config: {
          modelName: "12",
          deepThinking: true,
          reasoningCapability: capability,
          reasoningEffort: id,
        },
      });
    }
    rerender(view(false));
    expect(register.mock.lastCall?.[0].getModelContext()).toEqual({
      config: {
        modelName: "12",
        deepThinking: false,
        reasoningCapability: capability,
      },
    });
  }
);

it("keeps an unknown provider effort's fallback label and raw value", async () => {
  const i18n = createInstance();
  await i18n.init({
    lng: "zh",
    keySeparator: false,
    resources: { zh: { translation: zh } },
  });
  const changed = vi.fn();
  render(
    <I18nextProvider i18n={i18n}>
      <ModelSelector
        value="12"
        deepThinking
        onEffortChange={changed}
        models={[
          {
            id: "12",
            name: "Qwen",
            efforts: [
              { id: "low", name: "low" },
              { id: "provider-custom", name: "Provider custom effort" },
            ],
          },
        ]}
      />
    </I18nextProvider>
  );
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByText("Provider custom effort"));
  expect(changed).toHaveBeenLastCalledWith("provider-custom");
  expect(register.mock.lastCall?.[0].getModelContext()).toMatchObject({
    config: { reasoningEffort: "provider-custom" },
  });
});

it("shared advanced settings remains available with and without controlled values, outside model context", () => {
  const parameterSettings = {
    value: { temperature: 0.5, top_p: 0.9 },
    defaultValue: { temperature: 0.5, top_p: 0.9 },
    onChange: vi.fn(),
  };
  const { rerender } = render(
    <ModelSelector
      models={models}
      value="12"
      parameterSettings={parameterSettings}
    />
  );
  const advanced = screen.getByRole("button", { name: "高级设置" });
  expect(advanced.querySelector(".lucide-settings")).toBeNull();
  expect(
    screen.getByRole("switch").compareDocumentPosition(advanced) &
      Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
  const config = register.mock.lastCall?.[0].getModelContext() as {
    config: Record<string, unknown>;
  };
  expect(config.config).toMatchObject({ temperature: 0.5, top_p: 0.9 });
  rerender(<ModelSelector models={models} value="12" />);
  expect(
    screen.queryByRole("button", { name: "高级设置" })
  ).toBeInTheDocument();
});

it("does not re-register model context when equivalent model objects rerender", () => {
  register.mockClear();
  const { rerender } = render(
    <ModelSelector models={[{ ...models[0] }]} value="12" deepThinking />
  );
  const firstRegistrationCount = register.mock.calls.length;
  rerender(
    <ModelSelector models={[{ ...models[0] }]} value="12" deepThinking />
  );
  expect(register).toHaveBeenCalledTimes(firstRegistrationCount);
});

it("shows settings even without a selected model and forwards the first selection", async () => {
  const user = userEvent.setup();
  const onValueChange = vi.fn();
  const { container } = render(
    <ModelSelector models={models} value="" onValueChange={onValueChange} />
  );

  expect(
    container.querySelector('[data-slot="model-selector-value"]')
  ).not.toHaveTextContent("Qwen");
  expect(screen.getByRole("switch")).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Qwen" }));
  expect(onValueChange).toHaveBeenCalledExactlyOnceWith("12");
});

it("lets Start Chat toggle deep thinking and choose an effort in the shared selector", async () => {
  const user = userEvent.setup();
  render(<ModelSelector models={models} value="12" />);
  const thinking = screen.getByRole("switch");
  expect(thinking).toHaveAttribute("aria-checked", "false");
  await user.click(thinking);
  expect(thinking).toHaveAttribute("aria-checked", "true");
  const effort = screen.getByRole("combobox");
  await user.click(effort);
  await user.click(screen.getByText("Medium"));
  expect(register.mock.lastCall?.[0].getModelContext()).toMatchObject({
    config: { modelName: "12", deepThinking: true, reasoningEffort: "medium" },
  });
});

it("defaults the shared selector to low reasoning effort", async () => {
  const user = userEvent.setup();
  render(<ModelSelector models={models} value="12" />);
  await user.click(screen.getByRole("switch"));

  expect(register.mock.lastCall?.[0].getModelContext()).toMatchObject({
    config: { modelName: "12", deepThinking: true, reasoningEffort: "low" },
  });
});

it("lets Workbench control the same selector settings", async () => {
  const user = userEvent.setup();
  const onDeepThinkingChange = vi.fn();
  const onEffortChange = vi.fn();
  render(
    <ModelSelector
      models={models}
      value="12"
      deepThinking
      effort="medium"
      onDeepThinkingChange={onDeepThinkingChange}
      onEffortChange={onEffortChange}
    />
  );
  await user.click(screen.getByRole("switch"));
  expect(onDeepThinkingChange).toHaveBeenCalledWith(false);
  await user.click(screen.getByRole("combobox"));
  await user.click(screen.getByText("High"));
  expect(onEffortChange).toHaveBeenCalledWith("high");
});

it("passes capability metadata without forcing reasoning when deep thinking is off", () => {
  const capability = {
    status: "supported" as const,
    control: "effort" as const,
    levels: ["low" as const, "high" as const],
    source: "catalog" as const,
  };
  render(
    <ModelSelector
      models={[{ ...models[0], reasoningCapability: capability }]}
      value="12"
      deepThinking={false}
    />
  );
  const config = (
    register.mock.lastCall?.[0].getModelContext() as {
      config: Record<string, unknown>;
    }
  ).config;
  expect(config).toMatchObject({
    modelName: "12",
    deepThinking: false,
    reasoningCapability: capability,
  });
  expect(config).not.toHaveProperty("reasoningEffort");
});

it("default shared settings isolate local values by model and conversation without requests", async () => {
  const choices = [
    ...models,
    { id: "13", name: "Second Model", efforts: true },
  ];
  const requests = vi.spyOn(globalThis, "fetch");
  const view = (value: string, scope: string) => (
    <ModelSelector
      models={choices}
      value={value}
      parameterSettingsScopeKey={scope}
    />
  );
  const { rerender } = render(view("12", "thread-a"));
  const openPanel = async () => {
    fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
      key: "Enter",
    });
    return within(await screen.findByRole("region", { name: "高级设置" }));
  };
  let panel = await openPanel();
  const temperature = panel.getByRole("spinbutton", { name: "温度" });
  fireEvent.change(temperature, { target: { value: "0.7" } });
  fireEvent.keyDown(temperature, { key: "Enter" });
  expect(panel.getByRole("slider", { name: "温度 滑块" })).toHaveAttribute(
    "aria-valuenow",
    "0.7"
  );
  rerender(view("13", "thread-a"));
  panel = await openPanel();
  expect(panel.getByRole("spinbutton", { name: "温度" })).toHaveValue(null);
  rerender(view("12", "thread-b"));
  panel = await openPanel();
  expect(panel.getByRole("spinbutton", { name: "温度" })).toHaveValue(null);
  rerender(view("12", "thread-a"));
  panel = await openPanel();
  expect(panel.getByRole("spinbutton", { name: "温度" })).toHaveValue(0.7);
  const config = register.mock.lastCall?.[0].getModelContext() as {
    config: Record<string, unknown>;
  };
  expect(config.config.modelName).toBe("12");
  expect(config.config).toMatchObject({ temperature: 0.7 });
  expect(config.config).not.toHaveProperty("top_p");
  expect(requests).not.toHaveBeenCalled();
});

it("shared parameter editing honors disabled state and controlled callers", async () => {
  const changed = vi.fn();
  const control = {
    scopeKey: "controlled",
    value: { temperature: 0.6, top_p: 0.8 },
    defaultValue: { temperature: 0.5, top_p: 0.9 },
    onChange: changed,
  };
  const { rerender } = render(
    <ModelSelector models={models} value="12" parameterSettings={control} />
  );
  fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
    key: "Enter",
  });
  const input = await screen.findByRole("spinbutton", { name: "温度" });
  expect(input).toHaveValue(0.6);
  fireEvent.change(input, { target: { value: "0.8" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(changed).toHaveBeenLastCalledWith({
    temperature: 0.8,
    top_p: 0.8,
  });
  rerender(
    <ModelSelector
      models={models}
      value="12"
      parameterSettings={{
        ...control,
        value: { temperature: 0.8, top_p: 0.8 },
      }}
    />
  );
  expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(0.8);
  rerender(
    <ModelSelector
      models={models}
      value="12"
      parameterSettings={control}
      parameterSettingsDisabled
    />
  );
  expect(screen.getByRole("button", { name: "高级设置" })).toBeDisabled();
  expect(screen.getByRole("spinbutton", { name: "温度" })).toBeDisabled();
  expect(screen.getByRole("slider", { name: "温度 滑块" })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
});

it("collapses reasoning while off and restores the controls without changing supported options", async () => {
  const view = (enabled: boolean) => (
    <ModelSelector
      models={models}
      value="12"
      deepThinking={enabled}
      showEffort
      effort="high"
    />
  );
  const { rerender } = render(view(false));
  expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByText("思考强度")).not.toBeInTheDocument();
  rerender(view(true));
  expect(screen.getByRole("combobox")).toBeEnabled();
  await userEvent.click(screen.getByRole("combobox"));
  expect(screen.getByRole("option", { name: "High" })).toBeVisible();
});
