// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchWithErrorHandling } from "@/services/api";
import { trajectoryService } from "@/services/trajectoryService";
import { record } from "./trajectoryFixtures";

vi.mock("@/services/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/api")>()),
  fetchWithErrorHandling: vi.fn(),
}));
const request = vi.mocked(fetchWithErrorHandling);
beforeEach(() => {
  request.mockReset();
  request.mockResolvedValue(
    new Response(JSON.stringify({ code: 0, data: { items: [] } }))
  );
});

describe("trajectory HTTP adapter", () => {
  it("preserves decimal IDs and forwards cancellation, filters and signed membership", async () => {
    const signal = new AbortController().signal;
    await trajectoryService.records(
      {
        conversation_id: record.conversation_id,
        id_query: "中文 + ?",
        page: 2,
        query_id: "signed+/=",
      },
      signal
    );
    const [url, options] = request.mock.calls[0];
    const parsed = new URL(String(url), "http://localhost");
    expect(parsed.searchParams.get("conversation_id")).toBe(
      "9223372036854775806"
    );
    expect(parsed.searchParams.get("id_query")).toBe("中文 + ?");
    expect(parsed.searchParams.get("query_id")).toBe("signed+/=");
    expect(options).toMatchObject({ signal, cache: "no-store" });
  });
  it("binds the execution directory to the conversation query and cancellation", async () => {
    const signal = new AbortController().signal;
    await trajectoryService.conversation(
      record,
      { query_id: "query", cursor: "next-round", limit: 1 },
      signal
    );
    const [url, options] = request.mock.calls[0];
    const parsed = new URL(String(url), "http://localhost");
    expect(parsed.pathname).toContain(record.conversation_id);
    expect(parsed.pathname).not.toContain("snapshot");
    expect(Object.fromEntries(parsed.searchParams)).toMatchObject({
      tenant_id: "tenant",
      target_user_id: "owner",
      query_id: "query",
      cursor: "next-round",
      limit: "1",
    });
    expect(options).toMatchObject({ signal, cache: "no-store" });
  });
  it("binds snapshots to row tenant, owner and execution and keeps cursor separate", async () => {
    await trajectoryService.snapshot(record, {
      cursor: "cursor",
      snapshot_id: "snapshot",
      node_id: "parent",
    });
    const parsed = new URL(
      String(request.mock.calls[0][0]),
      "http://localhost"
    );
    expect(parsed.pathname).toContain(record.conversation_id);
    expect(Object.fromEntries(parsed.searchParams)).toMatchObject({
      tenant_id: "tenant",
      target_user_id: "owner",
      trajectory_id: "execution",
      cursor: "cursor",
      snapshot_id: "snapshot",
      limit: "500",
    });
  });
  it("bounds content reads and URL-encodes the authorized reference", async () => {
    await trajectoryService.content(
      record.conversation_id,
      "signed/+?",
      1048575
    );
    const url = String(request.mock.calls[0][0]);
    expect(url).toContain("signed%2F%2B%3F");
    expect(url).toContain("limit=1048576");
    expect(url).toContain("offset=1048575");
  });
  it("only posts days and cursor, never list tenant or path", async () => {
    await trajectoryService.cleanup(30, "cursor");
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({
      before_days: 30,
      cursor: "cursor",
    });
    expect(request.mock.calls[0][1]?.method).toBe("POST");
  });
  it("preserves business errors for the common error panel", async () => {
    const error = Object.assign(new Error(), { code: "snapshot_reset" });
    request.mockRejectedValue(error);
    await expect(trajectoryService.records({})).rejects.toBe(error);
  });
});
