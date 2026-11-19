// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RepositoryView } from "@/app/resource-space/components/skill/components/RepositoryView";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { SkillRepositoryListingItem } from "@/types/skillRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/app/resource-space/components/RepositoryDisplayControls", () => ({
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
vi.mock("@/app/resource-space/components/skill/components/SkillRepositoryCard", () => ({
  SkillRepositoryCard: ({ action }: { action: ReactNode }) => <>{action}</>,
}));
vi.mock(
  "@/app/resource-space/components/skill/components/SkillRepositoryControls",
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
  installationState: SkillRepositoryListingItem["installation_state"] = "not_installed",
  copies: NonNullable<SkillRepositoryListingItem["installed_copies"]> = [],
  enhanced = true
) {
  const install = vi.fn();
  const detail = vi.fn();
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
        listings={[
          {
            ...listing,
            installation_state: installationState,
            installed_copies: copies,
          },
        ]}
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
        enhanced={enhanced}
        onDetailClick={detail}
        showAdminMenu={false}
        onTakeDown={vi.fn()}
        installingRepositoryId={installingRepositoryId}
        takingDownRepositoryId={null}
      />
    </RepositoryPresentationContext.Provider>
  );
  return { install, detail };
}

const copy = { skill_id: 11, name: "My Skill", can_uninstall: true };

describe("skill repository install and installed actions", () => {
  it("preserves the legacy repository copy action", () => {
    const { install } = renderActions(null, "installed", [copy], false);
    const button = screen.getByRole("button", {
      name: "skillRepository.repository.copy",
    });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(install).toHaveBeenCalledOnce();
  });

  it("installs an unavailable skill with one button and no dropdown", () => {
    const { install } = renderActions();
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.install" })
    );
    expect(install).toHaveBeenCalledOnce();
    expect(install.mock.calls[0][0].skill_repository_id).toBe(7);
    expect(
      screen.queryByRole("button", { name: "resourceCenter.actions" })
    ).toBeNull();
  });

  it.each([
    { copies: [] },
    { copies: [copy] },
    { copies: [{ ...copy, can_uninstall: false }] },
    { copies: [copy, { ...copy, skill_id: 12, name: "Second copy" }] },
  ])(
    "hides installed actions without a removal action for copies: %j",
    ({ copies }) => {
      const { install } = renderActions(null, "installed", copies);
      expect(
        screen.queryByRole("button", { name: "resourceCenter.installed" })
      ).toBeNull();
      expect(
        screen.queryByRole("button", { name: "resourceCenter.install" })
      ).toBeNull();
      expect(install).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("button", { name: "resourceCenter.uninstall" })
      ).toBeNull();
      expect(screen.queryByRole("dialog")).toBeNull();
    }
  );

  it("does not guess installation state for unlinked historical skills", () => {
    const { install } = renderActions(null, "unknown");
    const button = screen.getByRole("button", {
      name: "resourceCenter.install",
    });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(install).not.toHaveBeenCalled();
  });

  it("blocks repeated clicks while installation is pending", () => {
    const { install } = renderActions(7);
    fireEvent.click(
      screen.getByRole("button", { name: /resourceCenter\.install$/ })
    );
    expect(install).not.toHaveBeenCalled();
  });
});
