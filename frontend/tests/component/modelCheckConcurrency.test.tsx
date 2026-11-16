// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  createModelOutlet,
  validateModelOutlet,
} from "../../services/modelProfileService";
import { modelService } from "../../services/modelService";

vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));
vi.mock("@/lib/session", () => ({ handleSessionExpired: vi.fn() }));
const fetcher = vi.fn();
beforeEach(() => {
  fetcher.mockReset();
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => vi.unstubAllGlobals());
const response = (
  json: () => Promise<unknown> = async () => ({
    data: { ok: true, connectivity: true },
  })
) => ({ status: 200, ok: true, json });

it("Q-01 profile, row, draft and managed-tenant checks share the same three HTTP slots", async () => {
  const finish: Array<() => void> = [];
  fetcher.mockImplementation(
    () => new Promise((resolve) => finish.push(() => resolve(response())))
  );
  const checks = [
    validateModelOutlet({ outlet_id: 1 }),
    validateModelOutlet({ outlet_id: 2 }),
    modelService.verifyModelConfigConnectivity({
      modelName: "draft",
      modelType: "embedding",
    }),
    modelService.verifyCustomModel("row", "llm"),
    modelService.checkManageTenantModelConnectivityDetail(
      "tenant",
      "managed-detail",
      "llm"
    ),
    modelService.checkManageTenantModelConnectivity("tenant", "managed", "llm"),
  ];
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(fetcher.mock.calls.map(([url]) => String(url))).not.toContain(
    expect.stringContaining("display_name=row")
  );
  finish[0]();
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4));
  expect(String(fetcher.mock.calls[3][0])).toContain("healthcheck");
  for (let index = 1; index < checks.length; index++) {
    await vi.waitFor(() => expect(finish[index]).toBeTypeOf("function"));
    finish[index]();
  }
  await Promise.all(checks);
  expect(fetcher).toHaveBeenCalledTimes(6);
});

it("Q-02 retains slots until response JSON is consumed and skips cancelled queued HTTP calls", async () => {
  const finish: Array<() => void> = [];
  fetcher.mockImplementation(() =>
    Promise.resolve(
      response(
        () =>
          new Promise((resolve) =>
            finish.push(() =>
              resolve({ data: { ok: true, connectivity: true } })
            )
          )
      )
    )
  );
  const active = [1, 2, 3].map((outlet_id) =>
    validateModelOutlet({ outlet_id })
  );
  await vi.waitFor(() => expect(finish).toHaveLength(3));
  const controller = new AbortController();
  const queued = validateModelOutlet({ outlet_id: 4 }, controller.signal);
  const rejected = expect(queued).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  await rejected;
  const next = modelService.verifyCustomModel("next", "llm");
  expect(fetcher).toHaveBeenCalledTimes(3);
  finish[0]();
  await vi.waitFor(() => expect(finish).toHaveLength(4));
  expect(fetcher).toHaveBeenCalledTimes(4);
  finish.slice(1).forEach((done) => done());
  await Promise.all([...active, next]);
});

it("Q-03 configuration saves bypass the check queue", async () => {
  const finish: Array<() => void> = [];
  fetcher.mockImplementation((url) =>
    String(url).endsWith("/model/outlets")
      ? Promise.resolve(response(async () => ({ data: { model_id: 99 } })))
      : new Promise((resolve) => finish.push(() => resolve(response())))
  );
  const checks = [1, 2, 3].map((outlet_id) =>
    validateModelOutlet({ outlet_id })
  );
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  const saved = await createModelOutlet({
    request_model_id: "saved",
    provider_info: { base_url: "https://models.invalid/v1" },
    catalog_revision: "revision",
  });
  expect(saved.model_id).toBe(99);
  expect(fetcher).toHaveBeenCalledTimes(4);
  finish.forEach((done) => done());
  await Promise.all(checks);
});
