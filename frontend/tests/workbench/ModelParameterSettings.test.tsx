// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ModelParameterSettings } from "@/components/chat/ModelParameterSettings";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_key: string, fallback: string) => fallback }),
}));

function Harness({ changed }: { changed: (value: unknown) => void }) {
  const [value, setValue] = useState({ temperatureLevel: 50, topPLevel: 90 });
  return (
    <ModelParameterSettings
      value={value}
      defaultValue={{ temperatureLevel: 50, topPLevel: 90 }}
      onChange={(next) => {
        changed(next);
        setValue(next);
      }}
    />
  );
}

it("numeric edits synchronize levels and restore defaults without requests", async () => {
  const changed = vi.fn();
  const requests = vi.spyOn(globalThis, "fetch");
  render(<Harness changed={changed} />);
  await userEvent.hover(screen.getByRole("button", { name: "高级设置" }));
  const panel = within(await screen.findByRole("region", { name: "高级设置" }));
  const temperature = panel.getByRole("spinbutton", { name: "温度" });
  await userEvent.clear(temperature);
  await userEvent.type(temperature, "100{Enter}");
  expect(changed).toHaveBeenLastCalledWith({
    temperatureLevel: 100,
    topPLevel: 90,
  });
  expect(panel.getByRole("slider", { name: "温度 滑块" })).toHaveAttribute(
    "aria-valuenow",
    "100"
  );
  const topP = panel.getByRole("spinbutton", { name: "Top P" });
  await userEvent.clear(topP);
  await userEvent.type(topP, "1");
  fireEvent.blur(topP);
  expect(changed).toHaveBeenLastCalledWith({
    temperatureLevel: 100,
    topPLevel: 1,
  });
  await userEvent.click(panel.getByRole("button", { name: "恢复默认" }));
  expect(panel.getByRole("spinbutton", { name: "温度" })).toHaveValue(50);
  expect(panel.getByRole("spinbutton", { name: "Top P" })).toHaveValue(90);
  expect(requests).not.toHaveBeenCalled();
});

it("restoring defaults also clears an invalid uncommitted numeric draft", async () => {
  render(<Harness changed={vi.fn()} />);
  fireEvent.focus(screen.getByRole("button", { name: "高级设置" }));
  const input = await screen.findByRole("spinbutton", { name: "温度" });
  fireEvent.change(input, { target: { value: "101" } });
  fireEvent.blur(input);
  await userEvent.click(screen.getByRole("button", { name: "恢复默认" }));
  expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(50);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it.each(["", "0", "101", "1.5"])(
  "invalid input %s never emits a parameter change",
  async (invalid) => {
    const changed = vi.fn();
    render(<Harness changed={changed} />);
    fireEvent.focus(screen.getByRole("button", { name: "高级设置" }));
    const input = await screen.findByRole("spinbutton", { name: "温度" });
    fireEvent.change(input, { target: { value: invalid } });
    fireEvent.blur(input);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("1–100");
    expect(changed).not.toHaveBeenCalled();
  }
);

it("keyboard slider editing emits the same controlled value", async () => {
  const changed = vi.fn();
  render(<Harness changed={changed} />);
  fireEvent.focus(screen.getByRole("button", { name: "高级设置" }));
  const slider = await screen.findByRole("slider", { name: "温度 滑块" });
  fireEvent.keyDown(slider, {
    key: "ArrowRight",
    code: "ArrowRight",
    keyCode: 39,
  });
  fireEvent.keyUp(slider, {
    key: "ArrowRight",
    code: "ArrowRight",
    keyCode: 39,
  });
  expect(changed).toHaveBeenLastCalledWith({
    temperatureLevel: 51,
    topPLevel: 90,
  });
  expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(51);
});
