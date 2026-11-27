// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { fetchWithErrorHandling } from "@/services/api";
import { tagManagementApi } from "@/services/tagManagementService";

vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));
vi.mock("@/services/api", () => ({
  API_BASE_URL: "/api",
  API_ENDPOINTS: {},
  fetchWithErrorHandling: vi.fn(),
}));

it("keeps the full document ID in the query for both tag reads and writes", async () => {
  const fetch = vi.mocked(fetchWithErrorHandling);
  fetch.mockImplementation(async () => new Response("{}"));
  const documentId = "imports/中文 100%.txt";
  const options = { provider: "local", knowledgeBaseId: "kb-1" };

  await tagManagementApi.getAssignments(
    "knowledge_document",
    documentId,
    options
  );
  await tagManagementApi.replaceAssignments(
    "knowledge_document",
    documentId,
    { value_ids: [9] },
    options
  );
  await tagManagementApi.getAssignments(
    "knowledge_document",
    documentId,
    options
  );

  expect(fetch).toHaveBeenCalledTimes(3);
  for (const [request] of fetch.mock.calls) {
    const url = new URL(String(request), "http://test");
    expect(url.pathname).toBe("/api/tag-libraries/documents/assignments");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      document_id: documentId,
      provider: "local",
      knowledge_base_id: "kb-1",
    });
  }
  expect(fetch.mock.calls[1][1]).toMatchObject({
    method: "PUT",
    body: JSON.stringify({ value_ids: [9] }),
  });
});
