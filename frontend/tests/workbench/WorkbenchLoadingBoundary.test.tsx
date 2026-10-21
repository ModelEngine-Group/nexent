// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
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

it.each([
  { conversationReady: false },
  { modelsLoading: true },
  { bootstrapLoading: true },
  { resourcesResolving: true },
])("does not mount composer or warnings while %j", (pending) => {
  const mount = vi.fn();
  function Composer() {
    mount();
    return <p>所选模型不可用，请重新选择模型</p>;
  }
  render(
    <WorkbenchLoadingBoundary {...ready} {...pending}>
      <Composer />
    </WorkbenchLoadingBoundary>
  );
  expect(screen.getByRole("status", { name: "加载中" })).toHaveAttribute(
    "aria-busy",
    "true"
  );
  expect(mount).not.toHaveBeenCalled();
  expect(screen.queryByText(/所选模型不可用/)).not.toBeInTheDocument();
});

it.each(["models-first", "bootstrap-first"])(
  "waits for both requests with %s completion, then restores after resource loading",
  (order) => {
    const content = <textarea aria-label="输入消息" defaultValue="draft" />;
    const { rerender } = render(
      <WorkbenchLoadingBoundary {...ready} modelsLoading bootstrapLoading>
        {content}
      </WorkbenchLoadingBoundary>
    );
    rerender(
      <WorkbenchLoadingBoundary
        {...ready}
        modelsLoading={order !== "models-first"}
        bootstrapLoading={order !== "bootstrap-first"}
      >
        {content}
      </WorkbenchLoadingBoundary>
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    rerender(
      <WorkbenchLoadingBoundary {...ready}>{content}</WorkbenchLoadingBoundary>
    );
    expect(screen.getByRole("textbox")).toHaveValue("draft");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    rerender(
      <WorkbenchLoadingBoundary {...ready} resourcesResolving>
        {content}
      </WorkbenchLoadingBoundary>
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    rerender(
      <WorkbenchLoadingBoundary {...ready}>{content}</WorkbenchLoadingBoundary>
    );
    expect(screen.getByRole("textbox")).toHaveValue("draft");
  }
);

it.each(["暂无可用模型", "会话资源恢复失败，请重新打开会话"])(
  "shows settled feedback instead of loading forever: %s",
  (feedback) => {
    render(
      <WorkbenchLoadingBoundary {...ready}>
        <p role="alert">{feedback}</p>
      </WorkbenchLoadingBoundary>
    );
    expect(screen.getByRole("alert")).toHaveTextContent(feedback);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  }
);
