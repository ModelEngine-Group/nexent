// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import RepositoryMcpCard from "@/components/repository/mcp/components/RepositoryMcpCard";
import { SkillRepositoryCard } from "@/components/repository/skill/components/SkillRepositoryCard";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { McpTransportType } from "@/const/mcpTools";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: "password" } }),
}));

const service: CommunityMcpCard = {
  communityId: 7,
  name: "MCP",
  description: "Description",
  status: "active",
  createdAt: "2026-11-17",
  transportType: McpTransportType.SSE,
  serverUrl: "https://example.invalid/sse",
  remotes: [],
  packages: [],
};

function show(
  children: ReactNode,
  resourceType: string,
  layout: "cards" | "list"
) {
  return render(
    <RepositoryPresentationContext.Provider value={{ layout, resourceType }}>
      {children}
    </RepositoryPresentationContext.Provider>
  );
}

test.each(["cards", "list"] as const)(
  "MCP %s retains independent install and permission-gated take-down icons",
  (layout) => {
    const install = vi.fn();
    const takeDown = vi.fn();
    const detail = vi.fn();
    show(
      <RepositoryMcpCard
        service={service}
        installed={false}
        isAdmin
        onInstall={install}
        onOffline={takeDown}
        onSelect={detail}
      />,
      "mcp",
      layout
    );
    fireEvent.click(
      screen.getByRole("button", { name: "mcpTools.repository.install" })
    );
    expect(install).toHaveBeenCalledWith(service);
    fireEvent.click(
      screen.getByRole("button", { name: "mcpTools.repository.offline" })
    );
    expect(takeDown).toHaveBeenCalledWith(service);
    expect(detail).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "mcpTools.mine.moreActions" })
    ).toBeNull();
  }
);

test.each([true, false])(
  "installed MCP hides its installation action for admin=%s",
  (isAdmin) => {
    show(
      <RepositoryMcpCard
        service={service}
        installed
        isAdmin={isAdmin}
        onInstall={vi.fn()}
        onOffline={vi.fn()}
        onSelect={vi.fn()}
      />,
      "mcp",
      "cards"
    );
    expect(
      screen.queryByRole("button", { name: "mcpTools.repository.installed" })
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "mcpTools.repository.install" })
    ).toBeNull();
    expect(
      Boolean(
        screen.queryByRole("button", { name: "mcpTools.repository.offline" })
      )
    ).toBe(isAdmin);
  }
);

test.each(["cards", "list"] as const)(
  "Skill %s retains take-down for its permitted publisher without a primary action",
  (layout) => {
    const takeDown = vi.fn();
    const detail = vi.fn();
    show(
      <SkillRepositoryCard
        listing={{
          skill_repository_id: 7,
          name: "Skill",
          status: "shared",
          can_take_down: true,
        }}
        showAdminMenu={false}
        onTakeDown={takeDown}
        onDetailClick={detail}
      />,
      "skill",
      layout
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "skillRepository.action.status.notShared",
      })
    );
    expect(takeDown).toHaveBeenCalledOnce();
    expect(detail).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", {
        name: "skillRepository.common.moreActions",
      })
    ).toBeNull();
  }
);

test("Skill does not expose take-down when the backend explicitly denies permission", () => {
  show(
    <SkillRepositoryCard
      listing={{
        skill_repository_id: 7,
        name: "Skill",
        status: "shared",
        can_take_down: false,
      }}
      showAdminMenu
      onTakeDown={vi.fn()}
    />,
    "skill",
    "cards"
  );
  expect(
    screen.queryByRole("button", {
      name: "skillRepository.action.status.notShared",
    })
  ).toBeNull();
});

test("MCP author appears once under the name, above the description", () => {
  show(
    <RepositoryMcpCard service={{ ...service, authorDisplayName: "author@example.test" }} installed isAdmin={false}
      onInstall={vi.fn()} onOffline={vi.fn()} onSelect={vi.fn()} />,
    "mcp", "cards",
  );
  const author = screen.getByTitle("author@example.test");
  expect(screen.getAllByText("author@example.test")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: /^MCP/ }).parentElement).toContainElement(author);
});

test("Skill author appears once under the name, above the description", () => {
  show(
    <SkillRepositoryCard listing={{ skill_repository_id: 7, name: "Skill", status: "shared", author: "author@example.test" }} />,
    "skill", "cards",
  );
  const author = screen.getByTitle("author@example.test");
  expect(screen.getAllByText("author@example.test")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "Skill" }).parentElement).toContainElement(author);
});
