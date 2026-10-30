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
