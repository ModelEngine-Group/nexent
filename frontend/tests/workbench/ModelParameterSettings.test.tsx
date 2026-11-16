// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModelParameterSettings } from "@/components/chat/ModelParameterSettings";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { ModelParameterValue } from "@/types/modelParameterSettings";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (_key: string, fallback: unknown) =>
      typeof fallback === "string" ? fallback : "请输入 0–2 的数字",
  }),
}));

function Harness({ changed }: { changed: (value: unknown) => void }) {
  const [value, setValue] = useState<ModelParameterValue>({});
  return (
    <ModelParameterSettings
      value={value}
      defaultValue={{}}
      inheritedValue={{ temperature: 0.6, top_p: 0.85 }}
      onChange={(next) => {
        changed(next);
        setValue(next);
      }}
    />
  );
}

it("does not open from model-menu autofocus when the thinking switch is disabled", async () => {
  const changed = vi.fn();
  const user = userEvent.setup();
  render(
    <Popover>
      <PopoverTrigger>Open model menu</PopoverTrigger>
      <PopoverContent>
        <button type="button" disabled>
          Deep thinking
        </button>
        <Harness changed={changed} />
      </PopoverContent>
    </Popover>
  );
  await user.click(screen.getByRole("button", { name: "Open model menu" }));
  const advanced = await screen.findByRole("button", { name: "高级设置" });
  await waitFor(() => expect(advanced).toHaveFocus());
  expect(advanced).toHaveAttribute("aria-expanded", "false");
  expect(
    screen.queryByRole("region", { name: "高级设置" })
  ).not.toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
  await user.hover(advanced);
  const panel = await screen.findByRole("region", { name: "高级设置" });
  await waitFor(() => expect(panel).toBeVisible());
  expect(changed).not.toHaveBeenCalled();
});

it.each(["Enter", " ", "ArrowRight"])(
  "opens only on explicit %s activation after focus and closes with Escape",
  async (key) => {
    const changed = vi.fn();
    render(<Harness changed={changed} />);
    const advanced = screen.getByRole("button", { name: "高级设置" });
    fireEvent.focus(advanced);
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    fireEvent.keyDown(advanced, { key });
    const panel = await screen.findByRole("region", { name: "高级设置" });
    await waitFor(() => expect(panel).toBeVisible());
    fireEvent.keyDown(panel, { key: "Escape" });
    await waitFor(() =>
      expect(advanced).toHaveAttribute("aria-expanded", "false")
    );
    await waitFor(() => expect(panel).not.toBeVisible());
    await userEvent.click(advanced);
    await waitFor(() => expect(panel).toBeVisible());
    expect(changed).not.toHaveBeenCalled();
  }
);

it("inherits until edited, preserves zero and decimals, then resets both overrides", async () => {
  const changed = vi.fn();
  const requests = vi.spyOn(globalThis, "fetch");
  render(<Harness changed={changed} />);
  fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
    key: "Enter",
  });
  const panel = within(await screen.findByRole("region", { name: "高级设置" }));
  const temperature = panel.getByRole("spinbutton", { name: "温度" });
  const topP = panel.getByRole("spinbutton", { name: "Top P" });
  expect(temperature).toHaveValue(0.6);
  expect(topP).toHaveValue(0.85);
  expect(temperature).not.toHaveAttribute("placeholder", "继承默认");
  expect(panel.getByRole("slider", { name: "Top P 滑块" })).toHaveAttribute(
    "aria-valuenow",
    "0.85"
  );
  fireEvent.blur(temperature);
  fireEvent.blur(topP);
  expect(changed).not.toHaveBeenCalled();
  for (const value of [0, 0.7, 2]) {
    fireEvent.change(temperature, { target: { value: String(value) } });
    fireEvent.keyDown(temperature, { key: "Enter" });
    expect(changed).toHaveBeenLastCalledWith({ temperature: value });
    expect(panel.getByRole("slider", { name: "温度 滑块" })).toHaveAttribute(
      "aria-valuenow",
      String(value)
    );
  }
  for (const value of [0, 0.95, 1]) {
    fireEvent.change(topP, { target: { value: String(value) } });
    fireEvent.blur(topP);
    expect(changed).toHaveBeenLastCalledWith({ temperature: 2, top_p: value });
  }
  await userEvent.click(panel.getByRole("button", { name: "恢复默认" }));
  expect(changed).toHaveBeenLastCalledWith({});
  expect(panel.getByRole("spinbutton", { name: "温度" })).toHaveValue(0.6);
  expect(panel.getByRole("spinbutton", { name: "Top P" })).toHaveValue(0.85);
  expect(requests).not.toHaveBeenCalled();
});

it.each(["", "-0.1", "2.1"])(
  "invalid temperature %s stays uncommitted and reset clears errors",
  async (invalid) => {
    const changed = vi.fn();
    render(<Harness changed={changed} />);
    fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
      key: "Enter",
    });
    const input = await screen.findByRole("spinbutton", { name: "温度" });
    fireEvent.change(input, { target: { value: invalid } });
    fireEvent.blur(input);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(changed).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "恢复默认" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  }
);

it("keyboard sliders commit decimal steps and Top P rejects values above one", async () => {
  const changed = vi.fn();
  render(<Harness changed={changed} />);
  fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
    key: "Enter",
  });
  const slider = await screen.findByRole("slider", { name: "温度 滑块" });
  fireEvent.keyDown(slider, {
    key: "ArrowRight",
    code: "ArrowRight",
    keyCode: 39,
  });
  expect(changed).not.toHaveBeenCalled();
  fireEvent.keyUp(slider, {
    key: "ArrowRight",
    code: "ArrowRight",
    keyCode: 39,
  });
  expect(changed).toHaveBeenLastCalledWith({ temperature: 0.7 });
  const topP = screen.getByRole("spinbutton", { name: "Top P" });
  fireEvent.change(topP, { target: { value: "1.1" } });
  fireEvent.blur(topP);
  expect(topP).toHaveAttribute("aria-invalid", "true");
  expect(changed).toHaveBeenCalledTimes(1);
});

it("shows configured zero and exact decimal defaults without turning focus or reset into an override", async () => {
  const changed = vi.fn();
  const props = {
    value: {},
    defaultValue: {},
    inheritedValue: { temperature: 0, top_p: 0.87 },
    onChange: changed,
  };
  const { rerender } = render(<ModelParameterSettings {...props} />);
  fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
    key: "Enter",
  });
  const t = await screen.findByRole("spinbutton", { name: "温度" });
  const p = screen.getByRole("spinbutton", { name: "Top P" });
  expect(t).toHaveValue(0);
  expect(p).toHaveValue(0.87);
  expect(screen.getByRole("slider", { name: "Top P 滑块" })).toHaveAttribute(
    "aria-valuenow",
    "0.87"
  );
  fireEvent.blur(t);
  fireEvent.blur(p);
  expect(changed).not.toHaveBeenCalled();
  rerender(
    <ModelParameterSettings
      {...props}
      inheritedValue={{ temperature: 0.45, top_p: 0.83 }}
    />
  );
  expect(t).toHaveValue(0.45);
  expect(p).toHaveValue(0.83);
  expect(screen.getByRole("slider", { name: "温度 滑块" })).toHaveAttribute(
    "aria-valuenow",
    "0.45"
  );
  fireEvent.blur(t);
  expect(changed).not.toHaveBeenCalled();
  rerender(
    <ModelParameterSettings
      {...props}
      value={{ temperature: 0.9 }}
      inheritedValue={{ temperature: 0.45, top_p: 0.83 }}
    />
  );
  expect(t).toHaveValue(0.9);
  expect(p).toHaveValue(0.83);
});

it("does not invent an unknown default or a zero slider handle, but permits a runtime override", async () => {
  const changed = vi.fn();
  render(
    <ModelParameterSettings value={{}} defaultValue={{}} onChange={changed} />
  );
  fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
    key: "Enter",
  });
  const t = await screen.findByRole("spinbutton", { name: "温度" });
  expect(t).toHaveValue(null);
  expect(t).not.toHaveAttribute("placeholder", "继承默认");
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.getByText("请先在模型配置中设置默认值，或输入本次使用的数值。", {
        exact: true,
      })
    ).toBeVisible()
  );
  fireEvent.blur(t);
  expect(changed).not.toHaveBeenCalled();
  fireEvent.change(t, { target: { value: "0.4" } });
  fireEvent.blur(t);
  expect(changed).toHaveBeenLastCalledWith({ temperature: 0.4 });
});

it("restoring discards an uncommitted numeric draft without submitting or saving the intermediate value", async () => {
  const changed = vi.fn();
  const submitted = vi.fn();
  render(
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submitted();
      }}
    >
      <input aria-label="Composer draft" defaultValue="Keep this draft" />
      <Harness changed={changed} />
    </form>
  );
  fireEvent.keyDown(screen.getByRole("button", { name: "高级设置" }), {
    key: "Enter",
  });
  const temperature = await screen.findByRole("spinbutton", { name: "温度" });
  await userEvent.click(temperature);
  fireEvent.change(temperature, { target: { value: "0.4" } });
  const reset = screen.getByRole("button", { name: "恢复默认" });
  expect(reset).toHaveAttribute("type", "button");
  await userEvent.click(reset);
  expect(changed.mock.calls).toEqual([[{}]]);
  expect(submitted).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "Composer draft" })).toHaveValue(
    "Keep this draft"
  );
  expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(0.6);
});

it("UI-SESSION-15 keeps the submenu open when focus and click target the same trigger", async () => {
  render(<Harness changed={vi.fn()} />);
  const trigger = screen.getByRole("button", { name: "高级设置" });
  await userEvent.click(trigger);
  await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "true"));
  expect(
    await screen.findByRole("spinbutton", { name: "温度" })
  ).toBeInTheDocument();
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(trigger).toHaveAttribute("aria-expanded", "false");
});
