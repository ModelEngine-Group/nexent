// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DocumentChunk from "@/app/knowledges/components/document/DocumentChunk";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type { Document } from "@/types/knowledgeBase";

vi.mock("react-i18next", () => {
  const t = (key: string, options?: { count?: number }) =>
    options?.count === undefined ? key : `${key}:${options.count}`;
  return { useTranslation: () => ({ t }) };
});
vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn() },
}));
vi.mock("@/services/knowledgeBaseService", () => ({
  default: { previewChunksPaginated: vi.fn(), hybridSearch: vi.fn() },
}));

const documents = [
  { id: "alpha-file", name: "Alpha.pdf", chunk_num: 1 },
  { id: "beta-file", name: "Beta.pdf", chunk_num: 1 },
] as Document[];
const alpha = {
  id: "chunk-a",
  content: "Alpha content",
  path_or_url: "alpha-file",
};
const beta = {
  id: "chunk-b",
  content: "Beta content",
  path_or_url: "beta-file",
};
const listChunks = vi.mocked(knowledgeBaseService.previewChunksPaginated);

function chunkPage(chunks: Array<typeof alpha>) {
  return { chunks, total: chunks.length, page: 1, pageSize: 10 };
}

function renderChunks(initialDocumentId?: string, permission = "EDIT") {
  return render(
    <App>
      <DocumentChunk
        knowledgeBaseId="test-kb"
        knowledgeBaseName="Test knowledge base"
        documents={documents}
        initialDocumentId={initialDocumentId}
        knowledgeBaseChunkCount={2}
        permission={permission}
      />
    </App>
  );
}

describe("knowledge base chunks", () => {
  beforeEach(() => {
    listChunks.mockReset();
    vi.mocked(knowledgeBaseService.hybridSearch).mockReset();
    listChunks.mockImplementation(async (_id, _page, _size, documentId) =>
      chunkPage(
        documentId
          ? [alpha, beta].filter((chunk) => chunk.path_or_url === documentId)
          : [alpha, beta]
      )
    );
  });

  it("loads all documents by default and keeps a stale response off a selected document", async () => {
    let resolveAll!: (page: ReturnType<typeof chunkPage>) => void;
    listChunks.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveAll = resolve;
        })
    );
    renderChunks();
    expect(listChunks).toHaveBeenCalledWith("test-kb", 1, 10, undefined);
    fireEvent.click(screen.getByRole("button", { name: "Beta.pdf" }));
    expect(await screen.findByText("Beta content")).toBeVisible();
    await act(async () => resolveAll(chunkPage([alpha, beta])));
    expect(screen.queryByText("Alpha content")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /document.chunk.allDocuments/ })
    );
    expect(await screen.findByText("Alpha content")).toBeVisible();
    expect(screen.getByText("Beta content")).toBeVisible();
    expect(screen.getByText("document.chunk.total:2")).toBeVisible();
  });

  it("opens a requested document and searches within the selected view", async () => {
    vi.mocked(knowledgeBaseService.hybridSearch).mockResolvedValue({
      results: [
        { ...alpha, content: "Alpha result", score: 0.95 },
        { ...beta, content: "Beta result", score: 0.8 },
      ],
    });
    renderChunks("beta-file", "READ_ONLY");
    expect(await screen.findByText("Beta content")).toBeVisible();
    expect(listChunks).toHaveBeenCalledWith("test-kb", 1, 10, "beta-file");
    expect(
      screen.queryByRole("button", { name: "document.chunk.tooltip.edit" })
    ).not.toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("textbox", { name: "document.chunk.search.content" }),
      {
        target: { value: " query " },
      }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "document.chunk.search.submit" })
    );
    expect(await screen.findByText("Beta result")).toBeVisible();
    expect(screen.queryByText("Alpha result")).not.toBeInTheDocument();
    expect(knowledgeBaseService.hybridSearch).toHaveBeenCalledWith(
      "test-kb",
      "query",
      { topK: 10 }
    );
    fireEvent.click(
      screen.getByRole("button", { name: /document.chunk.allDocuments/ })
    );
    expect(screen.getByText("Alpha result")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "document.chunk.search.clear" })
    );
    expect(await screen.findByText("Alpha content")).toBeVisible();
    expect(screen.queryByText("Alpha result")).not.toBeInTheDocument();
  });

  it("keeps document navigation available after a load failure and supports retry", async () => {
    listChunks.mockRejectedValueOnce(new Error("Network error"));
    renderChunks();
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Beta.pdf" })).toBeEnabled();
    fireEvent.click(
      screen.getByRole("button", { name: "repository.common.retry" })
    );
    await waitFor(() =>
      expect(screen.getByText("Alpha content")).toBeVisible()
    );
  });
});
