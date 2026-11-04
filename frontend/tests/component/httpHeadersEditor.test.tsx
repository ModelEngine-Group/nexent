// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { HttpHeadersEditor } from "../../components/model/HttpHeadersEditor";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it("retains stored headers without exposing values, supports replacement and removal", () => {
  const changed = vi.fn();
  function Editor() {
    const [value, setValue] = useState<Record<string, string | null>>({
      "x-auth": null,
    });
    return (
      <HttpHeadersEditor
        value={value}
        onChange={(next) => {
          changed(next);
          setValue(next);
        }}
      />
    );
  }
  const { container } = render(<Editor />);
  const field = screen.getByLabelText("modelProfile.headerValue");
  expect(field).toHaveValue("");
  expect(field).toHaveAttribute("placeholder", "modelProfile.storedHeader");
  expect(container.querySelector(".ant-input-password-icon")).toBeNull();
  expect(changed).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: "replacement" } });
  expect(changed).toHaveBeenLastCalledWith({ "x-auth": "replacement" });
  expect(container.querySelector(".ant-input-password-icon")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "common.delete" }));
  expect(changed).toHaveBeenLastCalledWith({});
});

it("blocks blank, invalid and duplicate names until corrected", () => {
  const changed = vi.fn();
  const validity = vi.fn();
  render(
    <HttpHeadersEditor
      value={{ "x-auth": null }}
      onChange={changed}
      onValidityChange={validity}
    />
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.addHeader" })
  );
  expect(validity).toHaveBeenLastCalledWith(false);
  const name = screen.getAllByLabelText("modelProfile.headerName")[1];
  fireEvent.change(name, { target: { value: "X-AUTH" } });
  expect(validity).toHaveBeenLastCalledWith(false);
  fireEvent.change(name, { target: { value: "x bad" } });
  expect(validity).toHaveBeenLastCalledWith(false);
  expect(changed).not.toHaveBeenCalled();
  fireEvent.change(name, { target: { value: "X-Extra" } });
  expect(validity).toHaveBeenLastCalledWith(true);
  expect(changed).toHaveBeenLastCalledWith({ "x-auth": null, "x-extra": "" });
});

it("AC-H1/AC-H3 replaces external values and never submits stale headers", () => {
  const changed = vi.fn();
  const validity = vi.fn();
  const props = { onChange: changed, onValidityChange: validity };
  const page = render(
    <HttpHeadersEditor {...props} value={{ "x-old": null }} />
  );
  page.rerender(
    <HttpHeadersEditor {...props} value={{ "x-new": "new-value" }} />
  );
  expect(screen.getByLabelText("modelProfile.headerName")).toHaveValue("x-new");
  expect(screen.getByLabelText("modelProfile.headerValue")).toHaveValue(
    "new-value"
  );
  expect(changed).not.toHaveBeenCalled();
  expect(validity).toHaveBeenLastCalledWith(true);
  fireEvent.change(screen.getByLabelText("modelProfile.headerValue"), {
    target: { value: "edited" },
  });
  expect(changed).toHaveBeenLastCalledWith({ "x-new": "edited" });
  page.rerender(<HttpHeadersEditor {...props} value={{}} />);
  expect(screen.queryByLabelText("modelProfile.headerName")).toBeNull();
  expect(validity).toHaveBeenLastCalledWith(true);
});

it("AC-H2 keeps invalid local rows when equivalent external maps are recreated or reordered", () => {
  const changed = vi.fn();
  const validity = vi.fn();
  const page = render(
    <HttpHeadersEditor
      value={{ "x-a": null, "x-b": "" }}
      onChange={changed}
      onValidityChange={validity}
    />
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.addHeader" })
  );
  expect(validity).toHaveBeenLastCalledWith(false);
  page.rerender(
    <HttpHeadersEditor
      value={{ "x-b": "", "x-a": null }}
      onChange={changed}
      onValidityChange={vi.fn()}
    />
  );
  expect(screen.getAllByLabelText("modelProfile.headerName")).toHaveLength(3);
  expect(screen.getAllByLabelText("modelProfile.headerName")[2]).toHaveValue(
    ""
  );
  expect(changed).not.toHaveBeenCalled();
});

it("AC-H1 reports replacement validity and clears an invalid draft on an external reset", () => {
  const validity = vi.fn();
  const props = { onChange: vi.fn(), onValidityChange: validity };
  const page = render(
    <HttpHeadersEditor {...props} value={{ "x-stored": null }} />
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.addHeader" })
  );
  page.rerender(
    <HttpHeadersEditor {...props} value={{ "invalid name": "value" }} />
  );
  expect(validity).toHaveBeenLastCalledWith(false);
  page.rerender(<HttpHeadersEditor {...props} value={{}} />);
  expect(screen.queryByLabelText("modelProfile.headerName")).toBeNull();
  expect(validity).toHaveBeenLastCalledWith(true);
});
