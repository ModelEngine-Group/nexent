// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";
import { ComposerAttachments } from "@/app/newchat/ui/attachment";

const translate = vi.hoisted(() => (key: string) => key);
const composer = vi.hoisted(() => ({ file: undefined as File | undefined }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));
vi.mock("@assistant-ui/react", () => ({
  ComposerPrimitive: {
    Attachments: ({
      children,
    }: {
      children: (value: {
        attachment: { file: File; name: string };
      }) => React.ReactNode;
    }) =>
      composer.file
        ? children({
            attachment: { file: composer.file, name: composer.file.name },
          })
        : null,
  },
  AttachmentPrimitive: { Remove: () => null },
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

const html = "<!doctype html><h1>HTML preview</h1><script>void 0</script>";

test("previews a stored HTML artifact as a single sandboxed document", async () => {
  const fetchPreview = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(html, { headers: { "Content-Type": "text/plain" } })
    );
  try {
    render(
      <FilePreviewDrawer
        open
        onClose={vi.fn()}
        objectName="workspace/report.html"
        fileName="report.html"
        fileType="text/plain"
        presentation="inline"
      />
    );
    const frame = await screen.findByTitle("report.html");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame.getAttribute("srcdoc")).toContain(html);
    expect(screen.queryByText("HTML preview")).toBeNull();
    expect(fetchPreview).toHaveBeenCalledOnce();
    expect(fetchPreview).toHaveBeenCalledWith(
      "/preview",
      expect.not.objectContaining({ headers: { Range: expect.any(String) } })
    );
  } finally {
    fetchPreview.mockRestore();
  }
});

test("opens a local HTML upload from the composer without fetching it", async () => {
  const file = new File([html], "upload.htm", { type: "text/html" });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode(html).buffer,
  });
  composer.file = file;
  const fetchPreview = vi.spyOn(globalThis, "fetch");
  try {
    render(<ComposerAttachments />);
    fireEvent.click(
      screen.getByRole("button", { name: "chat.attachments.preview" })
    );
    await waitFor(() => {
      const frame = document.querySelector('iframe[title="upload.htm"]');
      expect(frame).toHaveAttribute("sandbox", "");
      expect(frame?.getAttribute("srcdoc")).toContain(html);
    });
    expect(fetchPreview).not.toHaveBeenCalled();
  } finally {
    composer.file = undefined;
    fetchPreview.mockRestore();
  }
});
