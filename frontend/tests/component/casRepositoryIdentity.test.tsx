// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewAgentList } from "../../app/[locale]/agent-space/components/ReviewAgentList";
import type { AgentRepositoryListingItem } from "@/types/agentRepository";
import { AgentDetail } from "@/components/agent/agent-detail";
import { SkillDetail } from "@/components/skill/skill-detail";
import { SkillRepositoryCard } from "../../app/[locale]/skill-space/components/SkillRepositoryCard";
import RepositoryMcpCard from "../../app/[locale]/mcp-space/components/RepositoryMcpCard";
import {
  mapMyAgentDetail,
  mapRepositoryAgentDetail,
} from "@/lib/myAgentDetail";
import type { AgentVersionDetail } from "@/services/agentVersionService";
import type { AgentRepositoryListingDetail } from "@/types/agentRepository";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";
import type { CommunityMcpCard } from "@/types/mcpTools";
const session = vi.hoisted(() => ({ provider: "cas" }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: session.provider } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const version = {
  name: "Agent",
  author: "author@test",
  author_cas_username: "平台作者",
} as AgentVersionDetail;
const skill = {
  name: "Skill",
  skill_repository_id: 1,
  status: "shared",
  author: "author@test",
  author_cas_username: "平台作者",
  submitted_by: "submitter@test",
  submitted_by_cas_username: "提交人",
} as SkillRepositoryListingDetail;
const mcp = {
  name: "MCP",
  authorDisplayName: "author@test",
  authorCasUsername: "平台作者",
  tags: [],
  transportType: "sse" as CommunityMcpCard["transportType"],
  description: "MCP description",
  status: "active",
  createdAt: "2026-10-15",
  remotes: [],
  packages: [],
  serverUrl: "https://example.test/mcp",
} satisfies CommunityMcpCard;
describe("platform author presentation", () => {
  it.each(["cas", "local"])(
    "renders linked Agent and Skill authors for a %s viewer",
    (provider) => {
      session.provider = provider;
      render(
        <>
          <AgentDetail
            open
            onClose={vi.fn()}
            published
            detail={mapMyAgentDetail(version, { tags: [] })}
          />
          <SkillDetail
            open
            detail={skill}
            isLoading={false}
            isError={false}
            isFetching={false}
            onClose={vi.fn()}
            onRetry={vi.fn()}
          />
        </>
      );
      expect(
        screen.getAllByText(provider === "cas" ? "平台作者" : "author@test")
      ).toHaveLength(2);
    }
  );
  it("renders card authors and submitter fallback without changing the source objects", () => {
    session.provider = "cas";
    render(
      <>
        <SkillRepositoryCard listing={{ ...skill, author: null }} />
        <RepositoryMcpCard
          service={mcp}
          isAdmin={false}
          installed={false}
          onInstall={vi.fn()}
          onSelect={vi.fn()}
          onOffline={vi.fn()}
        />
      </>
    );
    expect(screen.getByText("提交人")).toBeInTheDocument();
    expect(screen.getByText("平台作者")).toBeInTheDocument();
    expect(mcp.authorDisplayName).toBe("author@test");
    expect(skill.submitted_by).toBe("submitter@test");
  });
  it("keeps custom and externally supplied authors when no metadata can verify their source", () => {
    session.provider = "cas";
    render(
      <SkillRepositoryCard
        listing={{
          ...skill,
          author: "Imported Author",
          author_cas_username: undefined,
        }}
      />
    );
    expect(screen.getByText("Imported Author")).toBeInTheDocument();
    expect(screen.queryByText("提交人")).not.toBeInTheDocument();
  });
  it.each(["cas", "local"])(
    "formats the submitter after the existing self comparison for %s",
    (provider) => {
      session.provider = provider;
      render(
        <ReviewAgentList
          listings={[
            {
              agent_repository_id: 1,
              name: "Agent",
              status: "pending_review",
              submitted_by: "me@test",
              submitted_by_cas_username: "提交人",
            } as AgentRepositoryListingItem,
          ]}
          currentUserEmail="me@test"
          updatingRepositoryId={null}
          onDetailClick={vi.fn()}
          onApprove={vi.fn()}
          onReject={vi.fn()}
        />
      );
      expect(
        screen.getByText(provider === "cas" ? "提交人" : "repository.review.me")
      ).toBeInTheDocument();
    }
  );
  it("does not apply listing author metadata to a different version author", () => {
    const detail = mapRepositoryAgentDetail(
      { ...version, author: "Imported Author", author_cas_username: undefined },
      {
        author: "author@test",
        author_cas_username: "平台作者",
      } as AgentRepositoryListingDetail
    );
    expect(detail.author).toBe("Imported Author");
    expect(detail.authorCasUsername).toBeUndefined();
  });
});
