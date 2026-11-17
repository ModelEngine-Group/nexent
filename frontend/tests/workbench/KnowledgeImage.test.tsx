// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthenticatedImage } from "@/app/newchat/ui/authenticated-image";
import { fetchKnowledgeContent } from "@/services/knowledgeContentService";
import { fetchImageBlob } from "@/services/storageService";

vi.mock("@/services/knowledgeContentService", () => ({
  fetchKnowledgeContent: vi.fn(),
}));
vi.mock("@/services/storageService", () => ({
  fetchImageBlob: vi.fn(),
  isLocalStorageObjectUrl: () => false,
}));

const reference = {
  knowledge_id: 7,
  file_id: "a".repeat(32),
  file_version: 0,
  image_ref: {
    space: "files",
    key: "kb/image.png",
    version: "v1",
    sha256: "b".repeat(64),
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:authorized"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
});

it("renders authorized reference bytes without requesting the supplied old URL", async () => {
  vi.mocked(fetchKnowledgeContent).mockResolvedValue(
    new Blob(["image"], { type: "image/png" })
  );
  const { unmount } = render(
    <AuthenticatedImage
      knowledgeReference={reference}
      src="https://old.invalid/image.png"
      alt="knowledge"
      preview
    />
  );
  await waitFor(() =>
    expect(screen.getByAltText("knowledge").getAttribute("src")).toBe(
      "blob:authorized"
    )
  );
  expect(fetchKnowledgeContent).toHaveBeenCalledWith(
    reference,
    expect.any(AbortSignal)
  );
  expect(fetchImageBlob).not.toHaveBeenCalled();
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:authorized");
});

it("shows a placeholder after denied access and never falls back to the old URL", async () => {
  vi.mocked(fetchKnowledgeContent).mockRejectedValue(new Error("forbidden"));
  render(
    <AuthenticatedImage
      knowledgeReference={reference}
      src="https://old.invalid/image.png"
      alt="knowledge"
      fallback={<span>unavailable</span>}
    />
  );
  await screen.findByText("unavailable");
  expect(screen.queryByRole("img")).toBeNull();
  expect(fetchImageBlob).not.toHaveBeenCalled();
});
