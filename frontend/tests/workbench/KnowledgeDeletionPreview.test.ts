// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { createElement } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import KnowledgeBaseDeleteNotice from "@/components/knowledge-base/KnowledgeBaseDeleteNotice";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";

vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ Authorization: "Bearer fixture" }),
  fetchWithAuth: (...args: Parameters<typeof fetch>) =>
    globalThis.fetch(...args),
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() },
}));
vi.mock("@/lib/session", () => ({ handleSessionExpired: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
afterEach(() => vi.unstubAllGlobals());

it("renders every returned bound agent by name", () => {
  render(
    createElement(KnowledgeBaseDeleteNotice, {
      preview: {
        agents: [
          { agent_id: 7, display_name: "Other user's private agent" },
          { agent_id: 8, display_name: "Shared agent" },
        ],
      },
    })
  );
  expect(
    screen.getAllByRole("listitem").map((item) => item.textContent)
  ).toEqual(["Other user's private agent", "Shared agent"]);
  expect(
    screen.getByText("knowledgeBase.deleteNotice.conversationsNotice")
  ).toBeInTheDocument();
});

it("keeps the conversation notice when no agents are bound", () => {
  render(createElement(KnowledgeBaseDeleteNotice, { preview: { agents: [] } }));
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
  expect(
    screen.getByText("knowledgeBase.deleteNotice.conversationsNotice")
  ).toBeInTheDocument();
});

it("renders no extra notice when the preview is unavailable", () => {
  const { container } = render(
    createElement(KnowledgeBaseDeleteNotice, { preview: null })
  );
  expect(container).toBeEmptyDOMElement();
});

it.each([
  [knowledgeBaseService, "/api/indices/"],
  [aidpKnowledgeService, "/api/aidp-mgmt/knowledge-bases/"],
] as const)(
  "uses the provider's existing service and route",
  async (service, prefix) => {
    const preview = {
      agents: [{ agent_id: 7, display_name: "Bound agent" }],
    };
    const request = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(preview)));
    vi.stubGlobal("fetch", request);
    await expect(service.previewBoundAgents("123 a")).resolves.toEqual(preview);
    expect(request).toHaveBeenCalledExactlyOnceWith(
      `${prefix}123%20a/bound_agents`,
      {
        method: "GET",
        headers: { Authorization: "Bearer fixture" },
      }
    );
  }
);

it.each([knowledgeBaseService, aidpKnowledgeService])(
  "returns an empty binding result unchanged",
  async (service) => {
    const empty = { agents: [] };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(empty)))
    );
    await expect(service.previewBoundAgents("missing")).resolves.toEqual(empty);
  }
);

it.each([knowledgeBaseService, aidpKnowledgeService])(
  "retains the existing null fallback when preview fails",
  async (service) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 500 }))
    );
    await expect(service.previewBoundAgents("idx")).resolves.toBeNull();
  }
);
