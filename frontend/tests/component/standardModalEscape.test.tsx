// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { StandardModal } from "@/components/common/StandardModal";

function renderModal(onOpenChange = vi.fn()) {
  render(
    <StandardModal
      open
      title="创建智能体"
      closeLabel="关闭"
      cancelText="取消"
      confirmText="确定"
      onOpenChange={onOpenChange}
      onClose={() => undefined}
    >
      <input aria-label="名称" />
    </StandardModal>
  );
  return onOpenChange;
}

describe("StandardModal keyboard dismissal (WCAG 2.1.2 / ARIA APG)", () => {
  it("closes on Escape by default", async () => {
    const onOpenChange = renderModal();
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape", keyCode: 27 });

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("keeps Escape inert only when closeOnEscape is explicitly disabled", async () => {
    const onOpenChange = vi.fn();
    render(
      <StandardModal
        open
        title="长表单"
        closeLabel="关闭"
        cancelText="取消"
        confirmText="确定"
        closeOnEscape={false}
        onOpenChange={onOpenChange}
        onClose={() => undefined}
      >
        <input aria-label="名称" />
      </StandardModal>
    );
    const dialog = await screen.findByRole("dialog");

    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape", keyCode: 27 });

    // Give React a tick to flush any handler that might have fired.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
