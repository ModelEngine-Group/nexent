// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/common/Button";
import { PreviewDrawerShell } from "@/components/preview/PreviewDrawerShell";

describe("StandardDrawer", () => {
  it("renders the documented content and closes through the footer actions", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onConfirm = vi.fn();

    render(
      <PreviewDrawerShell
        open
        title="test"
        closeLabel="Close"
        onClose={onClose}
        footer={
          <>
            <Button variant="outline" onClick={onClose}>
              {"Close"}
            </Button>
            <Button onClick={onConfirm}>{"Confirm"}</Button>
          </>
        }
      >
        12434
      </PreviewDrawerShell>
    );

    expect(screen.getByText("test")).toBeInTheDocument();
    expect(screen.getByText("12434")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveStyle({
      width: "560px",
    });
    const closeButtons = screen.getAllByRole("button", { name: "Close" });
    expect(closeButtons).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();

    await user.click(closeButtons[0]);
    await user.click(closeButtons[1]);
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onClose).toHaveBeenCalledTimes(2);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("allows the drawer width to be adjusted", () => {
    render(
      <PreviewDrawerShell
        open
        title="test"
        closeLabel="Close"
        onClose={vi.fn()}
        width={640}
        footer={
          <>
            <Button variant="outline" onClick={vi.fn()}>
              {"Close"}
            </Button>
          </>
        }
      >
        12434
      </PreviewDrawerShell>
    );

    expect(screen.getByRole("dialog")).toHaveStyle({
      width: "640px",
    });
  });

  it("sets button text letter spacing to zero", () => {
    render(
      <Button variant="outline" size="sm">
        Close
      </Button>
    );

    expect(screen.getByRole("button", { name: "Close" })).toHaveClass(
      "tracking-normal"
    );
  });

  it("does not insert spaces into localized CJK button labels", () => {
    render(
      <Button variant="outline" size="sm">
        关闭
      </Button>
    );

    const button = screen.getByRole("button", { name: "关闭" });
    expect(button.textContent).toBe("关闭");
  });
});
