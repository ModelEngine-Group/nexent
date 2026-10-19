// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MyAgentCard } from "../../app/[locale]/agent-space/components/MyAgentCard";
import { fetchPagedAgentList } from "@/services/agentConfigService";
import type { MyEditableAgentItem } from "@/types/agentRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        "agentRepository.card.mainAgent": "主智能体",
        "agentRepository.card.untitled": "未命名",
        "agentRepository.card.noDescription": "暂无描述",
        "agentRepository.mine.lifecycle.draft": "草稿",
        "agentRepository.mine.lifecycle.published": "已发布",
      };
      return translations[key] ?? key;
    },
  }),
}));

vi.mock("@/app/[locale]/agent-space/components/MyAgentIcon", () => ({
  MyAgentIcon: () => <div data-testid="agent-icon" />,
}));

vi.mock("@/components/resource/ResourceCard", () => ({
  default: ({ title, badge }: { title?: unknown; badge?: unknown }) => (
    <div>
      <div data-testid="card-title">{title as never}</div>
      <div data-testid="card-badge">{badge as never}</div>
    </div>
  ),
}));

const baseAgent: MyEditableAgentItem = {
  agent_id: 1,
  name: "Sample Agent",
  description: "desc",
  current_version_no: 1,
  permission: "EDIT",
  repository_info: [],
};

function renderCard(agent: MyEditableAgentItem) {
  return render(
    <MyAgentCard
      agent={agent}
      onEdit={vi.fn()}
      onView={vi.fn()}
      onApplyListing={vi.fn()}
      onViewReview={vi.fn()}
      onDelete={vi.fn()}
      onEvaluate={vi.fn()}
      onUsageGuide={vi.fn()}
    />
  );
}

describe("MyAgentCard main-agent badge", () => {
  it("marks an explicit main agent", () => {
    renderCard({ ...baseAgent, is_main_agent: true });
    expect(screen.getByText("主智能体")).toBeInTheDocument();
  });

  it("treats an agent with no flag as a main agent", () => {
    renderCard(baseAgent);
    expect(screen.getByText("主智能体")).toBeInTheDocument();
  });

  it("omits the badge for a non-main agent", () => {
    renderCard({ ...baseAgent, is_main_agent: false });
    expect(screen.queryByText("主智能体")).not.toBeInTheDocument();
  });
});

describe("fetchPagedAgentList latest-publish sort", () => {
  it("serializes the sort_by_update_time filter", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], pagination: {}, creator_counts: {} }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchPagedAgentList({
      tenantId: "tenant_1",
      sortByUpdateTime: true,
      page: 1,
      pageSize: 20,
    });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("sort_by_update_time=true");
    vi.unstubAllGlobals();
  });

  it("omits the filter when sorting is not requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], pagination: {}, creator_counts: {} }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchPagedAgentList({ tenantId: "tenant_1", page: 1, pageSize: 20 });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("sort_by_update_time");
    vi.unstubAllGlobals();
  });
});
