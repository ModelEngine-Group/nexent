// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RepositoryView } from "@/components/repository/skill/components/RepositoryView";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { SkillRepositoryListingItem } from "@/types/skillRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/repository/RepositoryDisplayControls", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/TagFilterPopover", () => ({ default: () => null }));
vi.mock("@/components/resource/ResourceCardGrid", () => ({
  default: ({
    items,
    renderItem,
  }: {
    items: SkillRepositoryListingItem[];
    renderItem: (item: SkillRepositoryListingItem) => ReactNode;
  }) => <>{items.map(renderItem)}</>,
}));
vi.mock("@/components/repository/skill/components/SkillRepositoryCard", () => ({
  SkillRepositoryCard: ({ action }: { action: ReactNode }) => <>{action}</>,
}));
vi.mock(
  "@/components/repository/skill/components/SkillRepositoryControls",
  () => ({
    AsyncContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  })
);

const listing: SkillRepositoryListingItem = {
  skill_repository_id: 7,
  name: "Skill",
  status: "shared",
  installation_state: "not_installed",
  installed_copies: [],
};

function renderActions(
  installingRepositoryId: number | null = null,
  installationState: SkillRepositoryListingItem["installation_state"] = "not_installed"
) {
  const install = vi.fn();
  render(
    <RepositoryPresentationContext.Provider
      value={{ layout: "cards", resourceType: "skill" }}
    >
      <RepositoryView
        searchQuery=""
        onSearchChange={vi.fn()}
        tagDefinitions={[]}
        tagPredicates={[]}
        onTagPredicatesChange={vi.fn()}
        listings={[{ ...listing, installation_state: installationState }]}
        isLoading={false}
        isError={false}
        isFetching={false}
        page={1}
        total={1}
        onPageChange={vi.fn()}
        pageSize={12}
        onPageSizeChange={vi.fn()}
        onRetry={vi.fn()}
        onInstall={install}
        onUninstall={vi.fn()}
        onDetailClick={vi.fn()}
        showAdminMenu={false}
        onTakeDown={vi.fn()}
        installingRepositoryId={installingRepositoryId}
        takingDownRepositoryId={null}
      />
    </RepositoryPresentationContext.Provider>
  );
  return install;
}

describe("skill repository split install action", () => {
  it.each(["installed", "unknown"] as const)(
    "keeps %s resources behind the copy menu instead of installing implicitly",
    async (state) => {
      const install = renderActions(null, state);
      fireEvent.click(
        screen.getByRole("button", {
          name:
            state === "installed"
              ? "resourceCenter.installed"
              : "resourceCenter.install",
        })
      );
      expect(await screen.findByRole("menu")).toBeTruthy();
      expect(install).not.toHaveBeenCalled();
    }
  );
  it("installs directly without also opening the copy menu", () => {
    const install = renderActions();
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.install" })
    );
    expect(install).toHaveBeenCalledExactlyOnceWith(listing);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("opens the copy menu from the arrow without installing", async () => {
    const install = renderActions();
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.actions" })
    );
    expect(await screen.findByRole("menu")).toBeTruthy();
    expect(install).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("resourceCenter.installAnother"));
    expect(install).toHaveBeenCalledExactlyOnceWith(listing);
  });

  it("disables the menu while that resource is installing", () => {
    renderActions(7);
    expect(
      screen
        .getByRole("button", { name: "resourceCenter.actions" })
        .hasAttribute("disabled")
    ).toBe(true);
  });
});
