// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import {
  fetchWorkbenchBootstrap,
  previewWorkbenchAgent,
} from "@/features/workbench/api";
import { conversationService } from "@/services/conversationService";
import { ApiError } from "@/services/api";
vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({
    Authorization: "Bearer fixture",
    "Content-Type": "application/json",
  }),
  fetchWithAuth: (...args: Parameters<typeof fetch>) =>
    globalThis.fetch(...args),
}));

it("ordinary retry forwards the saved target and acknowledges user index zero", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response("", {
        status: 200,
        headers: { "X-User-Message-Id": "501", "X-User-Message-Index": "0" },
      })
    );
  vi.stubGlobal("fetch", fetch);
  const acknowledged = vi.fn();
  await conversationService.runAgent(
    {
      query: "Same",
      history: [],
      conversation_id: 42,
      retry_user_message_id: 501,
      retry_message_index: 0,
    },
    undefined,
    undefined,
    undefined,
    undefined,
    undefined,
    acknowledged
  );
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({
    retry_user_message_id: 501,
    retry_message_index: 0,
  });
  expect(acknowledged).toHaveBeenCalledWith(501, 0);
  vi.unstubAllGlobals();
});

it.each([
  [null, null],
  ["0", "0"],
  ["501", "-1"],
  ["bad", "2"],
])("invalid user boundary is never acknowledged: %s %s", async (id, index) => {
  const headers: Record<string, string> = {};
  if (id !== null) headers["X-User-Message-Id"] = id;
  if (index !== null) headers["X-User-Message-Index"] = index;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("", { status: 200, headers }))
  );
  const acknowledged = vi.fn();
  await conversationService.runAgent(
    { query: "Same", history: [] },
    undefined,
    undefined,
    undefined,
    undefined,
    undefined,
    acknowledged
  );
  expect(acknowledged).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

it("Workbench bootstrap and published preview carry the authenticated identity", async () => {
  const fetch = vi
    .fn()
    .mockImplementation(
      async () => new Response(JSON.stringify({ data: {} }), { status: 200 })
    );
  vi.stubGlobal("fetch", fetch);
  await fetchWorkbenchBootstrap();
  await previewWorkbenchAgent(8, 3);
  for (const [, options] of fetch.mock.calls)
    expect(options.headers.Authorization).toBe("Bearer fixture");
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    agent_id: 8,
    version_no: 3,
  });
  vi.unstubAllGlobals();
});
it("UT-FE-WB-034 preserves the config conflict code and safe version for controller reload", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "WORKBENCH_CONFIG_VERSION_CONFLICT",
            current_version: 4,
          },
        }),
        { status: 409 }
      )
    )
  );
  await expect(
    conversationService.runAgent({
      query: "draft",
      history: [],
      conversation_id: 7,
      entrypoint: "workbench",
      expected_workbench_config_version: 3,
    })
  ).rejects.toMatchObject({
    name: "ApiError",
    code: "WORKBENCH_CONFIG_VERSION_CONFLICT",
    details: { current_version: 4 },
  });
  vi.unstubAllGlobals();
});
it("UT-FE-WB-013 creation permission failure cannot become a successful stream", async () => {
  const accepted = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "FORBIDDEN" } }), {
        status: 403,
      })
    )
  );
  try {
    await conversationService
      .runAgent({ query: "create", history: [], runtime_mode: "nl2skill" })
      .then(accepted);
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("FORBIDDEN");
  }
  expect(accepted).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});
