// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import SkillRepositoryPage from "../../app/[locale]/skill-space/page";

const authorization = vi.hoisted(() => ({
  user: { role: "USER", casdoorFeaturePolicy: true },
  permissions: new Set<string>(),
}));

vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: authorization.user,
    hasPermission: (permission: string) =>
      authorization.permissions.has(permission),
  }),
}));

vi.mock("next/navigation", () => {
  const params = new URLSearchParams();
  return { useSearchParams: () => params };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/hooks/useSetupFlow", () => ({ useSetupFlow: () => ({}) }));
vi.mock("@/hooks/skillRepository/useSkillRepositoryListings", () => ({
  useMyEditableSkillCounts: () => ({}),
  useSkillRepositoryListings: () => ({}),
}));

vi.mock("../../app/[locale]/skill-space/skill-space", () => ({
  SkillSpace: () => <div>Repository content</div>,
}));
vi.mock("../../app/[locale]/skill-space/my-skill", () => ({
  MySkill: ({
    canCreate,
    canPublish,
  }: {
    canCreate: boolean;
    canPublish: boolean;
  }) => (
    <div>
      {canCreate && <button>Create Skill</button>}
      {canPublish && <button>Submit Skill</button>}
    </div>
  ),
}));
vi.mock("../../app/[locale]/skill-space/review-center", () => ({
  ReviewCenter: () => <div>Review content</div>,
}));

afterEach(() => authorization.permissions.clear());

it("updates the visible repository and review tabs after grants change in the same session", () => {
  const { rerender } = render(<SkillRepositoryPage />);
  expect(screen.queryByRole("tab")).toBeNull();

  authorization.permissions.add("skill.repository:read");
  rerender(<SkillRepositoryPage />);
  expect(screen.getByText("Repository content")).toBeVisible();
  expect(screen.getAllByRole("tab")).toHaveLength(1);

  authorization.permissions.delete("skill.repository:read");
  authorization.permissions.add("skill.repository:review");
  rerender(<SkillRepositoryPage />);
  expect(screen.queryByText("Repository content")).toBeNull();
  expect(screen.getByText("Review content")).toBeVisible();
});

it("enables submission independently of creating Skill and browsing the repository", () => {
  authorization.permissions.add("skill.repository:publish");
  render(<SkillRepositoryPage />);
  expect(screen.getByRole("button", { name: "Submit Skill" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Create Skill" })).toBeNull();
  expect(screen.queryByText("Repository content")).toBeNull();
});
