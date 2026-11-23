import { App } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StandardCard } from "@/components/common/StandardCard";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardModal } from "@/components/common/StandardModal";
import { StandardPaginator } from "@/components/common/StandardPaginator";
import { StandardQuestionIcon } from "@/components/common/StandardQuestionIcon";

describe("standard components", () => {
  it("renders the documented card defaults and configurable dimensions", () => {
    const { rerender } = render(
      <StandardCard data-testid="default-card">Card content</StandardCard>
    );

    const defaultCard = screen.getByTestId("default-card");
    expect(defaultCard).toHaveClass("rounded-[8px]", "bg-[#fff]", "!border-0");

    rerender(
      <StandardCard
        data-testid="configured-card"
        bordered
        borderRadius="12px"
        width={320}
        height={96}
      >
        Card content
      </StandardCard>
    );

    expect(screen.getByTestId("configured-card")).toHaveStyle({
      width: "320px",
      height: "96px",
      borderRadius: "12px",
    });
  });

  it("renders the Ant Design question icon", () => {
    render(<StandardQuestionIcon aria-label="Question icon" />);

    expect(screen.getByLabelText("Question icon")).toBeInTheDocument();
  });

  it("uses Ant Design pagination with optional configuration", () => {
    render(<StandardPaginator total={50} data-testid="paginator" />);

    expect(screen.getByTestId("paginator")).toHaveClass(
      "text-[14px]",
      "![letter-spacing:0px]",
      "text-[#191919]"
    );
    expect(screen.getByRole("list")).toBeInTheDocument();
  });

  it("preserves Ant Design input behavior with documented styles", () => {
    render(<StandardInput placeholder="Enter content" />);

    expect(screen.getByPlaceholderText("Enter content")).toHaveClass(
      "!h-7",
      "!rounded-[4px]",
      "!border-[#c9c9c9]"
    );
  });

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
});
