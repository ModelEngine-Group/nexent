// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RequestParametersEditor } from "../../components/model/RequestParametersEditor";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
function Harness({
  initial,
  changed,
}: {
  initial: Array<{ path: string; value: unknown }>;
  changed: (value: string) => void;
}) {
  const [value, setValue] = useState(JSON.stringify(initial));
  return (
    <RequestParametersEditor
      value={value}
      onChange={(next) => {
        setValue(next);
        changed(next);
      }}
    />
  );
}

it("preserves typed false, zero, null, objects and arrays without a JSON text field", () => {
  const changed = vi.fn();
  const initial = [
    { path: "/flag", value: false },
    { path: "/count", value: 0 },
    { path: "/empty", value: null },
    {
      path: "/options",
      value: { nested: { size: 3 }, tags: ["one", false, null] },
    },
  ];
  render(<Harness initial={initial} changed={changed} />);
  expect(
    screen.queryByRole("textbox", { name: "modelProfile.extraParameters" })
  ).not.toBeInTheDocument();
  fireEvent.change(
    screen.getAllByRole("textbox", { name: "modelProfile.parameterName 1" })[0],
    { target: { value: "renamed" } }
  );
  expect(JSON.parse(changed.mock.calls.at(-1)![0])).toEqual([
    { path: "/renamed", value: false },
    ...initial.slice(1),
  ]);
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "modelProfile.parameterValue 1" }),
    { target: { value: "0" } }
  );
  expect(JSON.parse(changed.mock.calls.at(-1)![0])[3].value.nested.size).toBe(
    0
  );
});

it("retains incomplete and duplicate rows for correction and deletes only the selected row", () => {
  const changed = vi.fn();
  render(
    <Harness initial={[{ path: "/flag", value: false }]} changed={changed} />
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.addParameter" })
  );
  expect(changed).not.toHaveBeenCalled();
  fireEvent.change(
    screen.getByRole("textbox", { name: "modelProfile.parameterName 2" }),
    { target: { value: "flag" } }
  );
  expect(screen.getByText("modelProfile.parameterRowsInvalid")).toBeVisible();
  fireEvent.change(
    screen.getByRole("textbox", { name: "modelProfile.parameterName 2" }),
    { target: { value: "second" } }
  );
  expect(JSON.parse(changed.mock.calls.at(-1)![0])).toEqual([
    { path: "/flag", value: false },
    { path: "/second", value: "" },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "common.delete 1" }));
  expect(JSON.parse(changed.mock.calls.at(-1)![0])).toEqual([
    { path: "/second", value: "" },
  ]);
});

it("keeps existing nested paths and escapes literal names instead of changing API keys", () => {
  const changed = vi.fn();
  render(
    <Harness
      initial={[
        { path: "/options/flag", value: false },
        { path: "/literal~1name", value: "yes" },
      ]}
      changed={changed}
    />
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "modelProfile.parameterValue 2" }),
    { target: { value: "updated" } }
  );
  expect(JSON.parse(changed.mock.calls.at(-1)![0])).toEqual([
    { path: "/options/flag", value: false },
    { path: "/literal~1name", value: "updated" },
  ]);
});
