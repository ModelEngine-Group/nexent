// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn(), warn: vi.fn(), log: vi.fn() },
}));
vi.mock("@/services/storageService", () => ({
  storageService: { getPreviewUrl: () => "/preview", downloadFile: vi.fn() },
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: () => null,
  extractMarkdownHeadings: () => [],
}));
vi.mock("@/components/common/rawStreamPreviewViewer", () => ({
  RawStreamPreviewViewer: ({ url }: { url: string }) => (
    <div data-testid="stream-viewer">{url}</div>
  ),
}));

const props = {
  open: true,
  onClose: vi.fn(),
  objectName: "workspace/report.docx",
  fileName: "report.docx",
  previewUrl: "/original.docx",
  rawStream: true,
};

test("inline mode mounts preview content without a modal or drawer", async () => {
  const { container } = render(
    <FilePreviewDrawer {...props} presentation="inline" />
  );
  expect(
    container.querySelector('[data-slot="inline-file-preview"]')
  ).not.toBeNull();
  expect(await screen.findByTestId("stream-viewer")).toHaveTextContent(
    "/original.docx"
  );
  expect(document.querySelector(".ant-drawer")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("closed inline mode does not leave a document visible", () => {
  const { container } = render(
    <FilePreviewDrawer {...props} open={false} presentation="inline" />
  );
  expect(container).toBeEmptyDOMElement();
});

test("default drawer presentation stays available", async () => {
  render(<FilePreviewDrawer {...props} />);
  await waitFor(() =>
    expect(document.querySelector(".ant-drawer")).not.toBeNull()
  );
  expect(await screen.findByTestId("stream-viewer")).toHaveTextContent(
    "/original.docx"
  );
});

test("fullscreen presentation retains its existing back action", async () => {
  const close = vi.fn();
  render(
    <FilePreviewDrawer {...props} onClose={close} presentation="fullscreen" />
  );
  expect(
    await screen.findByRole("button", { name: "common.back" })
  ).toBeVisible();
  expect(await screen.findByTestId("stream-viewer")).toHaveTextContent(
    "/original.docx"
  );
});
