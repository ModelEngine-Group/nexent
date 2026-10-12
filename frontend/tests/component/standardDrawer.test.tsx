import { App } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StandardButton } from "@/components/common/StandardButton";
import { StandardDrawer } from "@/components/common/StandardDrawer";

describe("StandardDrawer", () => {
  it("renders the documented content and closes through the footer actions", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onConfirm = vi.fn();

    render(
      <App>
        <StandardDrawer
          open
          title="test"
          closeLabel="Close"
          closeText="Close"
          confirmText="Confirm"
          onClose={onClose}
          onConfirm={onConfirm}
        >
          12434
        </StandardDrawer>
      </App>
    );

    expect(screen.getByText("test")).toBeInTheDocument();
    expect(screen.getByText("12434")).toBeInTheDocument();
    expect(document.querySelector(".ant-drawer-content-wrapper")).toHaveStyle({
      width: "560px",
    });
    expect(screen.getByRole("dialog")).toHaveClass(
      "!shadow-[-2px_0_12px_0_rgba(0,0,0,0.08)]"
    );
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
      <App>
        <StandardDrawer
          open
          title="test"
          closeLabel="Close"
          closeText="Close"
          onClose={vi.fn()}
          width={640}
        >
          12434
        </StandardDrawer>
      </App>
    );

    expect(document.querySelector(".ant-drawer-content-wrapper")).toHaveStyle({
      width: "640px",
    });
  });

  it("sets button text letter spacing to zero", () => {
    render(<StandardButton>Close</StandardButton>);

    expect(screen.getByRole("button", { name: "Close" })).toHaveClass(
      "![letter-spacing:0px]",
      "[&>span]:![letter-spacing:0px]"
    );
  });

  it("does not insert spaces into localized CJK button labels", () => {
    render(<StandardButton>关闭</StandardButton>);

    const button = screen.getByRole("button", { name: "关闭" });
    expect(button.textContent).toBe("关闭");
  });
});
