// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n from "i18next";
import { expect, it } from "vitest";
import { initializeTestI18n } from "./i18n";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import type { ApiConversationDetail } from "@/types/conversation";

const summaries = {
  requirement_clarification: ["已提交需求信息", "Requirements submitted"],
  suggested_resource_installation: [
    "已完成资源安装选择",
    "Resource installation completed",
  ],
  installed_resource_binding: [
    "已完成资源选择",
    "Resource selection completed",
  ],
};
const variants = ["smolagents", "jiuwen"].flatMap((core) =>
  ["zh", "en"].flatMap((locale) =>
    Object.entries(summaries).map(([subtype, texts]) => ({
      core,
      locale,
      subtype,
      expected: texts[locale === "zh" ? 0 : 1],
    }))
  )
);

it.each(variants)(
  "restores $core $locale $subtype summary without mutating the action",
  async ({ core, locale, subtype, expected }) => {
    await initializeTestI18n(locale);
    const action = {
      type: "nl2agent_card_action",
      agent_id: 42,
      subtype,
      action: "submit",
      result: { answers: [] },
    };
    const detail: ApiConversationDetail = {
      conversation_id: 91,
      create_time: 0,
      runtime_metadata: { agent_core: core },
      message: [
        { role: "user", message_id: 11, message: JSON.stringify(action) },
      ],
    };
    const original = JSON.stringify(detail);
    const adapter = new RemoteConversationHistoryAdapter(
      () => "91",
      async () => ({ remoteId: "91", externalId: "91" }),
      async () => detail
    );
    for (let i = 0; i < 2; i++) {
      const restored = (await adapter.load()).messages[0].message;
      expect(restored.content).toEqual([{ type: "text", text: expected }]);
      expect(restored.metadata?.custom?.nl2agentCardAction).toEqual(action);
      expect(JSON.stringify(detail)).toBe(original);
    }
    await i18n.changeLanguage(locale === "zh" ? "en" : "zh");
    const translated = (await adapter.load()).messages[0].message;
    expect(translated.content).toEqual([
      {
        type: "text",
        text: summaries[subtype as keyof typeof summaries][
          locale === "zh" ? 1 : 0
        ],
      },
    ]);
  }
);

it.each(["zh", "en"])(
  "localizes unknown actions and preserves ordinary or invalid user input in %s",
  async (locale) => {
    await initializeTestI18n(locale);
    const unknown = {
      type: "nl2agent_card_action",
      agent_id: 42,
      subtype: "future_action",
      result: {},
    };
    const ordinary = [
      "用户原文 / Original text",
      JSON.stringify({ type: "ordinary", agent_id: 42 }),
      JSON.stringify({ ...unknown, agent_id: 0 }),
      "{not valid JSON",
    ];
    const texts = [JSON.stringify(unknown), ...ordinary];
    const result = await new RemoteConversationHistoryAdapter(
      () => "91",
      async () => ({ remoteId: "91", externalId: "91" }),
      async () => ({
        conversation_id: 91,
        create_time: 0,
        message: texts.map((message, i) => ({
          role: "user",
          message_id: i + 1,
          message,
        })),
      })
    ).load();
    expect(result.messages[0].message.content).toEqual([
      {
        type: "text",
        text: locale === "zh" ? "已继续智能体创建" : "Agent creation continued",
      },
    ]);
    result.messages
      .slice(1)
      .forEach((item, i) =>
        expect(item.message.content).toEqual([
          { type: "text", text: ordinary[i] },
        ])
      );
  }
);
