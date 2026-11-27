// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18next from "i18next";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
import { conversationService } from "@/services/conversationService";
import { ApiError } from "@/services/api";
import { ordinarySendError } from "@/app/newchat/utils/ordinary-send";
import { getConversationResourceLimitMessage } from "@/const/errorMessageI18n";

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }));
afterEach(() => vi.unstubAllGlobals());
vi.mock("@/lib/avatar", () => ({ generateAvatarUrl: vi.fn() }));
vi.mock("@/lib/session", () => ({
  hasAuthCookies: () => false,
  checkSessionValid: () => true,
  handleSessionExpired: vi.fn(),
}));

beforeEach(async () => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
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
    expect(
      ordinarySendError(error, "zh", (value) =>
        getConversationResourceLimitMessage(value, i18next.t)
      )
    ).toBe(error.message);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/agent/run"),
      expect.objectContaining({ method: "POST" })
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

it.each([undefined, "", "   ", 42])(
  "shows a model error without inventing an invalid Agent name (%s)",
  async (agentName) => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          message: {
            code: "model_not_available",
            details: { agent_name: agentName },
          },
        }),
        {
          status: 404,
        }
      )
    );
    await expect(
      conversationService.runAgent({ query: "hello", history: [] })
    ).rejects.toMatchObject({
      code: "model_not_available",
      message: "大语言模型不可用，请修改",
    });
  }
);

it("preserves unrelated error messages from the request interceptor", async () => {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ message: "No access" }), { status: 403 })
  );
  await expect(
    conversationService.runAgent({ query: "hello", history: [] })
  ).rejects.toMatchObject({
    code: 403,
    message: "No access",
  });
});

it("retains the successful streaming response", async () => {
  fetchMock.mockResolvedValue(
    new Response("data: hello\n\n", {
      headers: { "Content-Type": "text/event-stream" },
    })
  );
  const reader = await conversationService.runAgent({
    query: "hello",
    history: [],
  });
  expect("type" in reader).toBe(false);
  if (!("type" in reader)) {
    expect(new TextDecoder().decode((await reader.read()).value)).toBe(
      "data: hello\n\n"
    );
    await reader.cancel();
  }
});
