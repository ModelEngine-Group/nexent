// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModelParameterSettings } from "@/components/chat/ModelParameterSettings";
import type { ModelParameterValue } from "@/types/modelParameterSettings";

vi.mock("react-i18next", () => ({
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
      onChange={(next) => {
        changed(next);
        setValue(next);
      }}
    />
  );
}

it("inherits until edited, preserves zero and decimals, then resets both overrides", async () => {
  const changed = vi.fn();
  const requests = vi.spyOn(globalThis, "fetch");
  render(<Harness changed={changed} />);
  fireEvent.focus(screen.getByRole("button", { name: "高级设置" }));
  const panel = within(await screen.findByRole("region", { name: "高级设置" }));
  const temperature = panel.getByRole("spinbutton", { name: "温度" });
  const topP = panel.getByRole("spinbutton", { name: "Top P" });
  expect(temperature).toHaveValue(null);
  expect(temperature).toHaveAttribute("placeholder", "继承默认");
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
  expect(panel.getByRole("spinbutton", { name: "温度" })).toHaveValue(null);
  expect(panel.getByRole("spinbutton", { name: "Top P" })).toHaveValue(null);
  expect(requests).not.toHaveBeenCalled();
});

it.each(["", "-0.1", "2.1"])(
  "invalid temperature %s stays uncommitted and reset clears errors",
  async (invalid) => {
    const changed = vi.fn();
    render(<Harness changed={changed} />);
    fireEvent.focus(screen.getByRole("button", { name: "高级设置" }));
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
  fireEvent.focus(screen.getByRole("button", { name: "高级设置" }));
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
  expect(changed).toHaveBeenLastCalledWith({ temperature: 0.1 });
  const topP = screen.getByRole("spinbutton", { name: "Top P" });
  fireEvent.change(topP, { target: { value: "1.1" } });
  fireEvent.blur(topP);
  expect(topP).toHaveAttribute("aria-invalid", "true");
  expect(changed).toHaveBeenCalledTimes(1);
});
