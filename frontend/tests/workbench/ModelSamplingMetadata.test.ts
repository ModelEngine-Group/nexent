// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { modelService } from "@/services/modelService";

vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));

it("maps read-only effective sampling separately from persisted nullable model values", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        data: [
          {
            model_id: 11,
            model_name: "fixture",
            display_name: "Fixture",
            model_type: "llm",
            model_factory: "openai",
            connect_status: "available",
            temperature: null,
            top_p: null,
            effective_sampling: { temperature: 1, top_p: 1 },
          },
        ],
      }),
      { status: 200 }
    )
  );
  const models = await modelService.getAllModels();
  expect(models[0]).toMatchObject({
    temperature: null,
    topP: null,
    effectiveSampling: { temperature: 1, top_p: 1 },
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][1]?.method).toBeUndefined();
});
