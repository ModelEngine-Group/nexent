// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import HighFidelityPromptEditModal from "@/app/agents/[agentId]/components/HighFidelityPromptEditModal";

function renderModal(onClose = vi.fn()) {
  render(
    <HighFidelityPromptEditModal
      title="创建智能体"
      content=""
      readOnly={false}
      onClose={onClose}
      onSave={vi.fn()}
    />
  );
  return onClose;
}

describe("Prompt editor keyboard dismissal (WCAG 2.1.2 / ARIA APG)", () => {
  it("closes on Escape by default", async () => {
    const onClose = renderModal();
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape", keyCode: 27 });

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
