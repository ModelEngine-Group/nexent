// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import {
  ArtifactDocumentPanel,
  artifactDocumentSource,
} from "@/app/newchat/components/artifact-document-panel";
import type {
  ArtifactAttachmentLike,
  ConversationArtifact,
} from "@/app/newchat/utils/conversation-artifacts";

const state = vi.hoisted(() => ({ props: vi.fn(), download: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/common/filePreviewDrawer", () => ({
  FilePreviewDrawer: (props: unknown) => {
    state.props(props);
    return <div data-testid="document-viewer" />;
  },
}));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: {
    storage: {
      file: (object: string, mode: string, name: string) =>
        `/file/${object}?mode=${mode}&name=${name}`,
    },
  },
}));
vi.mock("@/services/storageService", () => ({
  storageService: {
    getPreviewUrl: (object: string, name: string) =>
      `/preview/${object}?name=${name}`,
  },
}));
vi.mock("@/app/newchat/ui/attachment", () => ({
  triggerUrlDownload: state.download,
}));

const attachment = (name: string, extra = {}) =>
  ({
    id: "file",
    name,
    object_name: "workspace/report",
    preview_url: "https://old/raw.docx",
    ...extra,
  }) as ArtifactAttachmentLike;

test.each(["docx", "xlsx", "pptx"])(
  "%s uses original bytes and the stream renderer instead of PDF",
  (extension) => {
    const result = artifactDocumentSource(attachment(`report.${extension}`));
    expect(result.rawStream).toBe(true);
    expect(result.previewUrl).toContain("mode=stream");
    expect(result.previewUrl).not.toContain("https://old");
    expect(result.downloadUrl).toBe(result.previewUrl);
  }
);

test.each(["doc", "xls", "ppt", "pdf", "txt", "md"])(
  "%s keeps the existing remote preview path",
  (extension) => {
    const result = artifactDocumentSource(attachment(`report.${extension}`));
    expect(result.rawStream).toBe(false);
    expect(result.previewUrl).toContain("/preview/workspace/report");
    expect(result.downloadUrl).toContain("mode=stream");
  }
);

test("falls back to a real source URL if object identity is unavailable", () => {
  const result = artifactDocumentSource(
    attachment("report.docx", {
      object_name: "",
      download_url: "https://files/original.docx",
    })
  );
  expect(result.previewUrl).toBe("https://files/original.docx");
  expect(result.rawStream).toBe(true);
});

test("renders an inline document with close, download and return-to-artifacts controls", () => {
  const onClose = vi.fn();
  const onShowArtifacts = vi.fn();
  const artifact = {
    key: "a:file",
    messageId: "a",
    attachment: attachment("report.docx"),
  } as ConversationArtifact;
  render(
    <ArtifactDocumentPanel
      artifact={artifact}
      onClose={onClose}
      onShowArtifacts={onShowArtifacts}
    />
  );
  expect(
    screen.getByRole("complementary", { name: "report.docx" })
  ).toBeVisible();
  expect(state.props).toHaveBeenLastCalledWith(
    expect.objectContaining({
      open: true,
      presentation: "inline",
      rawStream: true,
      fileName: "report.docx",
    })
  );
  fireEvent.click(
    screen.getByRole("button", { name: "chat.artifacts.download" })
  );
  expect(state.download).toHaveBeenCalledWith(
    expect.stringContaining("mode=stream"),
    "report.docx"
  );
  fireEvent.click(screen.getByRole("button", { name: "chat.artifacts.title" }));
  expect(onShowArtifacts).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "chat.artifacts.close" }));
  expect(onClose).toHaveBeenCalledOnce();
});
