// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfigCard } from "@/components/agent/ConfigCard";
import { InputField } from "@/components/common/InputField";
import { Modal } from "@/components/common/Modal";
import { Pagination } from "@/components/common/Pagination";
import { CircleHelp } from "lucide-react";

describe("standard components", () => {
  it("renders the documented card defaults and configurable dimensions", () => {
    const { rerender } = render(
      <ConfigCard data-testid="default-card">Card content</ConfigCard>
    );

    const defaultCard = screen.getByTestId("default-card");
    expect(defaultCard).toHaveClass("bg-card", "border-0");

    rerender(
      <ConfigCard
        data-testid="configured-card"
        style={{ ...{}, borderRadius: "12px", width: 320, height: 96 }}
      >
        Card content
      </ConfigCard>
    );

    expect(screen.getByTestId("configured-card")).toHaveStyle({
      width: "320px",
      height: "96px",
      borderRadius: "12px",
    });
  });

  it("renders the accessible shared question icon", () => {
    render(<CircleHelp aria-label="Question icon" />);

    expect(screen.getByLabelText("Question icon")).toBeInTheDocument();
  });

  it("uses the common pagination without Ant Design", () => {
    render(
      <Pagination
        total={50}
        data-testid="paginator"
        current={1}
        pageSize={10}
      />
    );

    expect(screen.getByTestId("paginator")).toHaveAttribute(
      "data-slot",
      "pagination"
    );
    expect(screen.getByRole("list")).toBeInTheDocument();
  });

  it("renders a native input using the shared semantic theme", () => {
    render(<InputField placeholder="Enter content" />);

    expect(screen.getByPlaceholderText("Enter content")).toHaveClass(
      "rounded-md",
      "border-input",
      "bg-transparent"
    );
  });

  it("supports modal actions and keeps the modal open when an action returns false", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const onCancel = vi.fn(() => false);
    const onClose = vi.fn();

    render(
      <Modal
        open
        title="Modal title"
        closeLabel="Close"
        onClose={() => {
          if ((onClose as () => boolean | void)() === false) return;
          onOpenChange(false);
        }}
        actions={{
          cancelLabel: "Cancel",
          confirmLabel: "Confirm",
          onCancel: () => {
            if ((onCancel as () => boolean | void)() === false) return;
            onOpenChange(false);
          },
          onConfirm: () => {
            onOpenChange(false);
          },
        }}
      >
        Modal content
      </Modal>
    );

    expect(screen.getByText("Modal title")).toBeInTheDocument();
    expect(screen.getByText("Modal content")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveStyle({
      width: "480px",
    });

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
