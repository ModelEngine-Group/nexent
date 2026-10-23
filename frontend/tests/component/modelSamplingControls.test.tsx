// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SliderStepper } from "@/components/common/SliderStepper";
import { ModelAdvancedConfig } from "@/app/models/components/model/ModelAdvancedConfig";
import {
  buildInferenceParamsPayload,
  type ModelAdvancedSettingsValue,
} from "@/app/models/components/model/ModelAdvancedSettings";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));

function modelForm(
  initial: ModelAdvancedSettingsValue = {},
  modelType = "llm"
) {
  const change = vi.fn();
  function Form() {
    const [value, setValue] = useState(initial);
    return (
      <ModelAdvancedConfig
        value={value}
        modelType={modelType}
        onChange={(next) => {
          change(next);
          setValue(next);
        }}
      />
    );
  }
  render(<Form />);
  return change;
}

describe("model sampling controls", () => {
  it("displays inherited defaults without emitting values and preserves explicit zero and clearing", () => {
    const change = modelForm({ max_output_tokens: 512 });
    const temperature = screen.getByRole("spinbutton", { name: "温度" });
    expect(temperature).toHaveValue(1);
    expect(screen.getByRole("spinbutton", { name: "Top P" })).toHaveValue(1);
    expect(change).not.toHaveBeenCalled();
    fireEvent.change(temperature, { target: { value: "0" } });
    const explicit = change.mock.lastCall![0];
    expect(explicit.max_output_tokens).toBe(512);
    expect(buildInferenceParamsPayload(explicit).temperature).toBe(0);
    expect(buildInferenceParamsPayload(explicit)).not.toHaveProperty("top_p");
    fireEvent.change(temperature, { target: { value: "" } });
    expect(change.mock.lastCall![0].temperature).toBeUndefined();
    expect(
      buildInferenceParamsPayload(change.mock.lastCall![0])
    ).not.toHaveProperty("temperature");
  });

  it("applies separate numeric ranges and synchronizes the sliders", () => {
    modelForm();
    fireEvent.change(screen.getByRole("spinbutton", { name: "温度" }), {
      target: { value: "3" },
    });
    expect(screen.getByRole("slider", { name: "温度" })).toHaveAttribute(
      "aria-valuenow",
      "2"
    );
    fireEvent.change(screen.getByRole("spinbutton", { name: "Top P" }), {
      target: { value: "3" },
    });
    expect(screen.getByRole("slider", { name: "Top P" })).toHaveAttribute(
      "aria-valuenow",
      "1"
    );
    fireEvent.change(screen.getByRole("spinbutton", { name: "Top P" }), {
      target: { value: "-1" },
    });
    expect(screen.getByRole("spinbutton", { name: "Top P" })).toHaveValue(0);
  });

  it("supports keyboard limits and decimal stepping", () => {
    modelForm({ temperature: 0.2 });
    const slider = screen.getByRole("slider", { name: "温度" });
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(0.3);
    fireEvent.click(screen.getByRole("button", { name: "温度 −" }));
    expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(0.2);
    fireEvent.keyDown(slider, { key: "End" });
    expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(2);
    fireEvent.click(screen.getByRole("button", { name: "温度 +" }));
    expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(2);
    fireEvent.keyDown(slider, { key: "Home" });
    expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(0);
  });

  it("updates the numeric input when the slider is dragged", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    try {
      modelForm();
      const slider = screen.getByRole("slider", { name: "温度" });
      Object.defineProperty(slider, "setPointerCapture", { value: vi.fn() });
      vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({
        left: 100,
        width: 200,
      } as DOMRect);
      fireEvent.pointerDown(slider, { clientX: 150 });
      expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(0.5);
      fireEvent.pointerMove(slider, { clientX: 200 });
      expect(screen.getByRole("spinbutton", { name: "温度" })).toHaveValue(1);
      fireEvent.pointerUp(slider);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("does not expose sampling controls for rerank models", () => {
    modelForm({}, "rerank");
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("keeps disabled shared controls inert", () => {
    const change = vi.fn();
    render(
      <SliderStepper
        label="Top P"
        value={0.5}
        fallback={1}
        min={0}
        max={1}
        step={0.1}
        disabled
        onChange={change}
      />
    );
    expect(screen.getByRole("spinbutton")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Top P +" }));
    fireEvent.keyDown(screen.getByRole("slider"), { key: "End" });
    expect(change).not.toHaveBeenCalled();
  });
});
