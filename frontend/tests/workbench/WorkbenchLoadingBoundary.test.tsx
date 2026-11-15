// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WorkbenchLoadingBoundary } from "@/features/workbench/components/WorkbenchLoadingBoundary";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: () => "加载中" }),
}));
const ready = {
  conversationReady: true,
  modelsLoading: false,
  bootstrapLoading: false,
  resourcesResolving: false,
};
it("still waits for active conversation history", () => {
  render(
    <WorkbenchLoadingBoundary {...ready} conversationReady={false}>
      <textarea aria-label="draft" />
    </WorkbenchLoadingBoundary>
  );
  expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
it.each(["modelsLoading", "bootstrapLoading", "resourcesResolving"] as const)(
  "preserves composer identity and edited draft during %s",
  (flag) => {
    const content = <textarea aria-label="draft" defaultValue="draft" />;
    const { rerender } = render(
      <WorkbenchLoadingBoundary {...ready}>{content}</WorkbenchLoadingBoundary>
    );
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "unsent draft" } });
    rerender(
      <WorkbenchLoadingBoundary {...ready} {...{ [flag]: true }}>
        {content}
      </WorkbenchLoadingBoundary>
    );
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("unsent draft");
    rerender(
      <WorkbenchLoadingBoundary {...ready}>{content}</WorkbenchLoadingBoundary>
    );
    expect(screen.getByRole("textbox")).toBe(input);
  }
);
