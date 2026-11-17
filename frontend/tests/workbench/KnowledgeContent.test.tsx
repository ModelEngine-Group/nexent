// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchWithErrorHandling, API_ENDPOINTS } from "@/services/api";
import { fetchKnowledgeContent } from "@/services/knowledgeContentService";
import { useKnowledgeContentUrl } from "@/hooks/knowledge/useKnowledgeContentUrl";

vi.mock("@/services/api", () => ({
  API_ENDPOINTS: {
    storage: { knowledgeContent: "/api/file/knowledge/content" },
  },
  fetchWithErrorHandling: vi.fn(),
}));

const file = { knowledge_id: 7, file_id: "a".repeat(32), file_version: 0 };
const request = vi.mocked(fetchWithErrorHandling);
const NativeURL = URL;

beforeEach(() => {
  vi.stubGlobal(
    "URL",
    Object.assign(class extends NativeURL {}, {
      createObjectURL: vi.fn(),
      revokeObjectURL: vi.fn(),
    })
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("posts the exact versioned request once and preserves API errors", async () => {
  const blob = new Blob(["source"]);
  request.mockResolvedValueOnce({ blob: async () => blob } as Response);
  expect(await fetchKnowledgeContent(file)).toBe(blob);
  expect(request).toHaveBeenCalledWith(
    API_ENDPOINTS.storage.knowledgeContent,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify(file),
      signal: expect.any(AbortSignal),
    })
  );
  const error = new Error("forbidden");
  request.mockRejectedValueOnce(error);
  await expect(fetchKnowledgeContent(file)).rejects.toBe(error);
  expect(request).toHaveBeenCalledTimes(2);
});

it("bounds a stalled response body and aborts the underlying request without retry", async () => {
  vi.useFakeTimers();
  let signal: AbortSignal | undefined;
  request.mockImplementationOnce(async (_url, options) => {
    signal = options?.signal as AbortSignal;
    return { blob: () => new Promise(() => {}) } as Response;
  });
  const pending = expect(fetchKnowledgeContent(file)).rejects.toMatchObject({
    name: "TimeoutError",
  });
  await vi.advanceTimersByTimeAsync(12000);
  await pending;
  expect(signal?.aborted).toBe(true);
  expect(request).toHaveBeenCalledTimes(1);
});

it("respects cancellation before sending and during body consumption", async () => {
  const before = new AbortController();
  before.abort();
  await expect(
    fetchKnowledgeContent(file, before.signal)
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(request).not.toHaveBeenCalled();
  const during = new AbortController();
  request.mockResolvedValueOnce({
    blob: () => new Promise(() => {}),
  } as Response);
  const pending = expect(
    fetchKnowledgeContent(file, during.signal)
  ).rejects.toMatchObject({ name: "AbortError" });
  during.abort();
  await pending;
  expect(request).toHaveBeenCalledTimes(1);
});

it("revokes owned Blob URLs on version changes and unmount", async () => {
  const create = vi
    .fn()
    .mockReturnValueOnce("blob:first")
    .mockReturnValueOnce("blob:second");
  const revoke = vi.fn();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke })
  );
  request.mockImplementation(
    async () => ({ blob: async () => new Blob(["bytes"]) }) as Response
  );
  const { result, rerender, unmount } = renderHook(
    ({ version }) => useKnowledgeContentUrl({ ...file, file_version: version }),
    { initialProps: { version: 0 } }
  );
  await waitFor(() => expect(result.current.url).toBe("blob:first"));
  rerender({ version: 1 });
  expect(result.current.url).toBeUndefined();
  await waitFor(() => expect(result.current.url).toBe("blob:second"));
  expect(revoke).toHaveBeenCalledWith("blob:first");
  unmount();
  expect(revoke).toHaveBeenCalledWith("blob:second");
});

it("does not create a Blob URL from a response that arrives after unmount", async () => {
  let resolve!: (blob: Blob) => void;
  const create = vi.spyOn(URL, "createObjectURL");
  request.mockResolvedValueOnce({
    blob: () =>
      new Promise<Blob>((done) => {
        resolve = done;
      }),
  } as Response);
  const { unmount } = renderHook(() => useKnowledgeContentUrl(file));
  await waitFor(() => expect(resolve).toBeTypeOf("function"));
  unmount();
  await act(async () => resolve(new Blob(["late"])));
  expect(create).not.toHaveBeenCalled();
});

it("never reuses a revoked URL when a reference changes away and back before loading", async () => {
  vi.mocked(URL.createObjectURL).mockReturnValue("blob:first");
  request.mockResolvedValueOnce({
    blob: async () => new Blob(["first"]),
  } as Response);
  const { result, rerender } = renderHook(
    ({ version }) => useKnowledgeContentUrl({ ...file, file_version: version }),
    { initialProps: { version: 0 } }
  );
  await waitFor(() => expect(result.current.url).toBe("blob:first"));
  request.mockImplementation(
    async () => ({ blob: () => new Promise(() => {}) }) as Response
  );
  rerender({ version: 1 });
  rerender({ version: 0 });
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:first");
  expect(result.current.url).toBeUndefined();
});
