// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResourceDetail from "@/components/resource/ResourceDetail";
import { Drawer, Button } from "antd";
import { AgentDetail } from "@/components/agent/agent-detail";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { MyAgentDetailView } from "@/lib/myAgentDetail";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: { count?: number }) =>
      key === "resourceCenter.agentDetail.copyCount"
        ? `${params?.count} 次`
        : key,
    i18n: { language: "zh" },
  }),
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
  it("uses one empty message for related resources and hides empty tags", () => {
    renderAgentDetail();
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "resourceCenter.agentDetail.basicInfo",
      "resourceCenter.agentDetail.model",
      "resourceCenter.agentDetail.relatedResources",
    ]);
    const relatedResources = headings[2].closest("section")!;
    expect(
      within(relatedResources).getByText(
        "resourceCenter.agentDetail.noRelatedResources"
      )
    ).toBeVisible();
    expect(
      within(relatedResources).queryByRole("heading", { level: 4 })
    ).toBeNull();
    expect(screen.getByRole("dialog").querySelector(".ant-empty")).toBeNull();
    expect(
      screen.getAllByText("resourceCenter.notRecorded").length
    ).toBeGreaterThan(0);
    expect(screen.queryByText("agentRepository.mine.detail.tags")).toBeNull();
  });

  it("groups tags, published version, dates, and zero copies under basic information", () => {
    renderAgentDetail({
      tags: ["medical", "reports"],
      versionLabel: "v2.0",
      repositoryInfo: {
        downloads: 0,
        createdAt: null,
        publishedAt: "2026-10-12T06:20:00Z",
        updatedAt: "2026-10-13T06:20:00Z",
        isMainAgent: true,
      },
    });
    const basicInfo = within(
      screen
        .getByRole("heading", {
          name: "resourceCenter.agentDetail.basicInfo",
        })
        .closest("section")!
    );
    const tags = basicInfo.getByRole("list", {
      name: "agentRepository.mine.detail.tags",
    });
    expect(tags.textContent).toContain("medical");
    expect(tags.textContent).toContain("reports");
    expect(basicInfo.getByText("v2.0")).toBeVisible();
    expect(basicInfo.getByText("0 次")).toBeVisible();
    expect(
      basicInfo
        .getByText("agentConfig.list.column.updatedAt")
        .parentElement?.querySelector("time")
    ).toHaveAttribute("datetime", "2026-10-13T06:20:00Z");
    expect(
      basicInfo
        .getByText("resourceCenter.publishedAt")
        .parentElement?.querySelector("time")
    ).toHaveAttribute("datetime", "2026-10-12T06:20:00Z");
    expect(screen.getByText("agentRepository.card.mainAgent")).toBeVisible();
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
    expect(
      screen.getByRole("heading", { level: 4, name: /detail.skills/ })
    ).toHaveTextContent("5");
    expect(
      screen.queryByText("resourceCenter.agentDetail.noRelatedResources")
    ).toBeNull();
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

  it.each(["agent", "mcp", "skill"])(
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
      expect(screen.getByRole("dialog")).toHaveStyle({ borderRadius: "0" });
      expect(document.querySelector(".ant-drawer")).toHaveClass(
        "resource-detail-drawer",
        "!rounded-none"
      );
      expect(document.querySelector(".ant-drawer-content-wrapper")).toHaveClass(
        "!rounded-none"
      );
      expect(screen.getByRole("dialog")).toHaveClass("!rounded-none");
      expect(document.querySelector(".ant-drawer-body")).toHaveClass(
        "!pt-6",
        "!pb-0"
      );
      fireEvent.click(screen.getByRole("button", { name: "common.close" }));
      expect(close).toHaveBeenCalledOnce();
    }
  );

  it("renders the native drawer title, dismissal and footer actions", () => {
    render(
      <Drawer
        open
        title="Default title"
        closable={{ "aria-label": "Dismiss" }}
        footer={<Button>Close</Button>}
        onClose={vi.fn()}
      >
        <p>Body</p>
      </Drawer>
    );
    expect(screen.getByText("Default title")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
  });
});
