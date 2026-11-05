// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import { updateModelOutlet } from "@/services/modelProfileService";

const transport = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { model: { outlet: (id: number) => `/model/outlets/${id}` } },
  fetchWithErrorHandling: transport,
}));
beforeEach(() => {
  transport.mockReset();
  transport.mockResolvedValue({
    json: async () => ({ data: { model_id: 12 } }),
  });
});

it("AC-FIX-03 retries a saved draft without sending immutable provider identity in connection PATCH", async () => {
  const connection = {
    provider_id: "__custom__",
    base_url: "https://models.example/v1",
    ssl_verify: false,
    timeout_seconds: 7,
    concurrency_limit: 2,
  };
  await updateModelOutlet(12, {
    expected_revision: 3,
    connection,
    api_key: null,
    http_headers: { "x-gateway": null },
    extra_api_parameters: [{ path: "/vendor/thinking", value: false }],
  });
  const [url, options] = transport.mock.calls[0];
  expect(url).toBe("/model/outlets/12");
  expect(options.method).toBe("PATCH");
  expect(JSON.parse(options.body)).toEqual({
    expected_revision: 3,
    connection: {
      base_url: connection.base_url,
      ssl_verify: false,
      timeout_seconds: 7,
      concurrency_limit: 2,
    },
    api_key: null,
    http_headers: { "x-gateway": null },
    extra_api_parameters: [{ path: "/vendor/thinking", value: false }],
  });
  expect(connection.provider_id).toBe("__custom__");
});

it("preserves parameter-only PATCH without inventing connection changes", async () => {
  await updateModelOutlet(12, {
    expected_revision: 4,
    parameter_values: { temperature: 0, top_p: 1 },
  });
  expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual({
    expected_revision: 4,
    parameter_values: { temperature: 0, top_p: 1 },
  });
});
