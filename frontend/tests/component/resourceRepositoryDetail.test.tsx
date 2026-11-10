// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResourceDetail from "@/components/resource/ResourceDetail";
import { StandardDrawer } from "@/components/common/StandardDrawer";
import { AgentDetail } from "@/components/agent/agent-detail";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { MyAgentDetailView } from "@/lib/myAgentDetail";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/hooks/auth/useUserDisplayName", () => ({
  useUserDisplayName: () => (_username: string, fallback: string) => fallback,
}));

function renderAgentDetail(overrides: Partial<MyAgentDetailView> = {}) {
  return render(
    <RepositoryPresentationContext.Provider
      value={{ layout: "cards", resourceType: "agent" }}
    >
      <AgentDetail
        open
        onClose={vi.fn()}
        published
        showRepositoryInfo
        detail={{
          title: "Repository agent",
          description: "",
          author: null,
          modelName: null,
          versionLabel: null,
          tools: [],
          skills: [],
          knowledgeBases: [],
          subAgents: [],
          tags: [],
          ...overrides,
        }}
      />
    </RepositoryPresentationContext.Provider>
  );
}

describe("agent repository detail", () => {
  it("keeps each empty section heading and renders the standard empty state", () => {
    renderAgentDetail();
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "agentRepository.mine.detail.tags",
      "common.description",
      "agentRepository.mine.detail.author",
      "resourceCenter.publishedAt",
      "agentRepository.mine.detail.model",
      "agentRepository.mine.detail.knowledgeBases",
      "agentRepository.mine.detail.skills",
      "agentRepository.mine.detail.tools",
      "resourceCenter.subAgents",
    ]);
    for (const heading of headings) {
      if (heading.textContent === "resourceCenter.publishedAt") continue;
      expect(
        heading.closest("section")?.querySelector(".ant-empty")
      ).toBeTruthy();
    }
    expect(screen.getByText("resourceCenter.notRecorded")).toBeTruthy();
  });

  it("renders four separate models initially and lets users show and hide the rest", () => {
    renderAgentDetail({
      repositoryInfo: {
        downloads: 0,
        createdAt: null,
        modelNames: ["First", "Second", "Third", "Fourth", "Fifth"],
      },
    });
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.expandMore" })
    );
    expect(screen.getByText("Fifth")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", {
        name: "mcpConfig.toolsList.button.collapse",
      })
    );
    expect(screen.queryByText("Fifth")).toBeNull();
  });

  it("expands related resource sections independently", () => {
    renderAgentDetail({
      skills: ["Skill 1", "Skill 2", "Skill 3", "Skill 4", "Skill 5"],
      tools: ["Tool 1", "Tool 2", "Tool 3", "Tool 4", "Tool 5"],
    });
    const [expandSkills, expandTools] = screen.getAllByRole("button", {
      name: "resourceCenter.expandMore",
    });
    fireEvent.click(expandSkills);
    expect(screen.getByText("Skill 5")).toBeTruthy();
    expect(screen.queryByText("Tool 5")).toBeNull();
    fireEvent.click(expandTools);
    expect(screen.getByText("Tool 5")).toBeTruthy();
    expect(screen.getByText("Skill 5")).toBeTruthy();
  });
});

describe("repository detail container compatibility", () => {
  it("keeps the legacy centered modal outside the new repository", () => {
    render(
      <ResourceDetail open onClose={vi.fn()}>
        <p>Legacy detail</p>
      </ResourceDetail>
    );
    expect(
      screen.getByText("Legacy detail").closest(".ant-modal")
    ).not.toBeNull();
    expect(document.querySelector(".ant-drawer")).toBeNull();
  });

  it.each(["agent", "mcp"])(
    "opens %s detail as a right drawer and retains the close callback",
    (resourceType) => {
      const close = vi.fn();
      render(
        <RepositoryPresentationContext.Provider
          value={{ layout: "cards", resourceType }}
        >
          <ResourceDetail open onClose={close}>
            <p>Repository detail</p>
          </ResourceDetail>
        </RepositoryPresentationContext.Provider>
      );
      expect(document.querySelector(".ant-drawer-right")).not.toBeNull();
      expect(document.querySelector(".ant-modal")).toBeNull();
      expect(screen.getByText("Repository detail")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "common.close" }));
      expect(close).toHaveBeenCalledOnce();
    }
  );

  it("preserves the standard drawer header and footer defaults", () => {
    render(
      <StandardDrawer
        open
        title="Default title"
        closeLabel="Dismiss"
        closeText="Close"
        onClose={vi.fn()}
      >
        <p>Body</p>
      </StandardDrawer>
    );
    expect(screen.getByText("Default title")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
  });
});
