// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18next from "i18next";
import { beforeEach, expect, it, vi } from "vitest";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
import { conversationService } from "@/services/conversationService";
import { ApiError } from "@/services/api";

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }));
vi.mock("@/lib/auth", () => ({
  fetchWithAuth: fetchMock,
  getAuthHeaders: () => ({}),
}));

beforeEach(async () => {
  fetchMock.mockReset();
  await i18next.init({
    lng: "zh",
    keySeparator: false,
    defaultNS: "translation",
    resources: { zh: { translation: zh }, en: { translation: en } },
  });
});

it.each(["message", "detail"])(
  "names the failing Agent from the %s envelope",
  async (envelope) => {
    const details = { agent_id: 48, agent_name: "厨师助手", version_no: 1 };
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          [envelope]: { code: "model_not_available", details },
        }),
        { status: 404 }
      )
    );
    const error = await conversationService
      .runAgent({ query: "hello", history: [], agent_id: 50 })
      .catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "model_not_available", details });
    expect(error.message).toBe(
      "厨师助手智能体无可用模型，请检查该智能体绑定版本的模型配置。"
    );
  }
);

it("localizes the named error in English", async () => {
  await i18next.changeLanguage("en");
  fetchMock.mockResolvedValue(
    new Response(
      JSON.stringify({
        message: {
          code: "model_not_available",
          details: { agent_name: "Chef" },
        },
      }),
      { status: 404 }
    )
  );
  await expect(
    conversationService.runAgent({ query: "hello", history: [] })
  ).rejects.toThrow(
    'Agent "Chef" has no available model. Check the model configuration of its bound version.'
  );
});

it("preserves the generic code without inventing an Agent name", async () => {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ message: { code: "model_not_available" } }), {
      status: 404,
    })
  );
  await expect(
    conversationService.runAgent({ query: "hello", history: [] })
  ).rejects.toMatchObject({
    code: "model_not_available",
    message: "HTTP 404: ",
  });
});
