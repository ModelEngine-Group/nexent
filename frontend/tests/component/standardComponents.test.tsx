// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Button, ConfigProvider } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StandardModal } from "@/components/common/StandardModal";
import { NEXENT_THEME } from "@/const/brand";

describe("shared modal and theme", () => {
  it("supports modal actions and keeps the modal open when an action returns false", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const onCancel = vi.fn(() => false);
    const onClose = vi.fn();

    render(
      <App>
        <StandardModal
          open
          title="Modal title"
          closeLabel="Close"
          cancelText="Cancel"
          confirmText="Confirm"
          onOpenChange={onOpenChange}
          onCancel={onCancel}
          onClose={onClose}
        >
          Modal content
        </StandardModal>
      </App>
    );

    expect(screen.getByText("Modal title")).toBeInTheDocument();
    expect(screen.getByText("Modal content")).toBeInTheDocument();
    expect(document.querySelector(".ant-modal")).toHaveStyle({
      width: "480px",
    });
    expect(document.querySelector(".ant-modal-container")).toHaveClass(
      "!border-[#c9c9c9]",
      "!shadow-[0_0_15px_0_rgba(26,26,26,0.1)]"
    );
    expect(document.querySelector(".ant-modal-body")).toHaveClass("!py-4");

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
  it("does not insert spaces into localized CJK button labels", () => {
    render(
      <ConfigProvider theme={NEXENT_THEME} button={{ autoInsertSpace: false }}>
        <Button>关闭</Button>
      </ConfigProvider>
    );
    expect(screen.getByRole("button", { name: "关闭" }).textContent).toBe(
      "关闭"
    );
  });
});
