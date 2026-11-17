// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SourcesPanel } from "@/app/newchat/ui/sources-panel";
import { fetchKnowledgeContent } from "@/services/knowledgeContentService";
import { storageService } from "@/services/storageService";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/knowledgeContentService", () => ({
  fetchKnowledgeContent: vi.fn(),
}));
vi.mock("@/services/storageService", () => ({
  storageService: { downloadFileWithAuth: vi.fn() },
  extractObjectNameFromUrl: () => null,
  getLocalFilePreviewUrl: () => undefined,
  isLocalStorageObjectUrl: () => false,
  fetchImageBlob: vi.fn(),
}));
vi.mock("@/components/common/filePreviewDrawer", () => ({
  FilePreviewDrawer: ({ file, open }: { file: File; open: boolean }) =>
    open ? <div data-testid="preview">{file.name}</div> : null,
}));

const fileRef = { knowledge_id: 7, file_id: "a".repeat(32), file_version: 2 };
const item = {
  sourceType: "document" as const,
  url: "",
  title: "report.pdf",
  filename: "report.pdf",
  citeIndex: 1,
  toolSign: "a",
  fileRef,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchKnowledgeContent).mockResolvedValue(
    new Blob(["report"], { type: "application/pdf" })
  );
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:download"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
});

it("downloads a fixed file reference without guessing attachments from the filename", async () => {
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  render(<SourcesPanel sources={[item]} images={[]} open onClose={() => {}} />);
  fireEvent.click(
    screen.getByRole("button", { name: "chat.sources.download" })
  );
  await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
  expect(fetchKnowledgeContent).toHaveBeenCalledWith(
    fileRef,
    expect.any(AbortSignal)
  );
  expect(storageService.downloadFileWithAuth).not.toHaveBeenCalled();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:download");
  click.mockRestore();
});

it("opens the existing local preview using authorized bytes", async () => {
  render(<SourcesPanel sources={[item]} images={[]} open onClose={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "chat.sources.preview" }));
  expect(await screen.findByTestId("preview")).toHaveTextContent("report.pdf");
  expect(fetchKnowledgeContent).toHaveBeenCalledWith(
    fileRef,
    expect.any(AbortSignal)
  );
});

it("preserves a denied download as an error without using old object lookup", async () => {
  vi.mocked(fetchKnowledgeContent).mockRejectedValue(new Error("forbidden"));
  render(<SourcesPanel sources={[item]} images={[]} open onClose={() => {}} />);
  fireEvent.click(
    screen.getByRole("button", { name: "chat.sources.download" })
  );
  await screen.findByText("chat.sources.downloadError");
  expect(storageService.downloadFileWithAuth).not.toHaveBeenCalled();
});

it("cancels a pending preview and discards its bytes when the file version changes", async () => {
  let finish!: (blob: Blob) => void;
  let signal: AbortSignal | undefined;
  vi.mocked(fetchKnowledgeContent).mockImplementationOnce(
    (_file, currentSignal) => {
      signal = currentSignal;
      return new Promise((resolve) => {
        finish = resolve;
      });
    }
  );
  const { rerender } = render(
    <SourcesPanel sources={[item]} images={[]} open onClose={() => {}} />
  );
  fireEvent.click(screen.getByRole("button", { name: "chat.sources.preview" }));
  rerender(
    <SourcesPanel
      sources={[{ ...item, fileRef: { ...fileRef, file_version: 3 } }]}
      images={[]}
      open
      onClose={() => {}}
    />
  );
  expect(signal?.aborted).toBe(true);
  finish(new Blob(["old bytes"]));
  await waitFor(() => expect(screen.queryByTestId("preview")).toBeNull());
  expect(
    screen.getByRole("button", { name: "chat.sources.preview" })
  ).not.toBeDisabled();
});
