import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import AidpSliderNumberField from "@/ext_components/aidp/components/AidpSliderNumberField";

function Field() {
  const [value, setValue] = useState<number | null>(10);
  return (
    <>
      <AidpSliderNumberField
        value={value}
        onChange={setValue}
        min={1}
        max={100}
        step={1}
        marks={{ 1: "1", 100: "100" }}
        ariaLabel="TOP K"
      />
      <output data-testid="submitted-value">{value}</output>
    </>
  );
}
it.each([
  ["1.5", "2"],
  ["1.4", "1"],
])(
  "rounds %s and synchronizes the displayed, slider and submitted values",
  (input, expected) => {
    render(<Field />);
    const control = screen.getByRole("spinbutton", { name: "TOP K" });
    fireEvent.change(control, { target: { value: input } });
    fireEvent.blur(control);
    expect(control).toHaveValue(expected);
    expect(screen.getByTestId("submitted-value")).toHaveTextContent(expected);
    expect(screen.getByRole("slider")).toHaveAttribute(
      "aria-valuenow",
      expected
    );
  }
);
