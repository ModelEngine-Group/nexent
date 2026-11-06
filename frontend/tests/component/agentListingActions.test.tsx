// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import AgentConfigActions from "@/app/agents/components/agent-config-actions";
import type { Agent } from "@/types/agentConfig";
import type {
  AgentRepositoryListingCreatePayload,
  MyEditableAgentItem,
} from "@/types/agentRepository";

const mocks = vi.hoisted(() => ({ push: vi.fn(), createListing: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ locale: "zh" }),
  usePathname: () => "/zh/agents",
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      agentId: null,
      editedAgent: null,
      isReadOnly: false,
      reset: vi.fn(),
    }),
}));
vi.mock("@/hooks/agent/useAgentInfo", () => ({
  useAgentInfo: () => ({ agentInfo: null }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));
vi.mock("@/components/agent/AgentCallRelationshipModal", () => ({
  default: () => null,
}));
vi.mock("@/app/agents/components/a2a/A2AServerSettingsPanel", () => ({
  default: () => null,
}));
vi.mock("@/services/agentRepositoryService", () => ({
  default: {
    createAgentRepositoryListing: mocks.createListing,
  },
}));
vi.mock("@/components/agent/AgentApplyListingModal", () => ({
  AgentApplyListingModal: ({
    agent,
    onClose,
    onSubmit,
    isSubmitting,
  }: {
    agent: MyEditableAgentItem;
    onClose: () => void;
    onSubmit: (payload: AgentRepositoryListingCreatePayload) => Promise<void>;
    isSubmitting: boolean;
  }) => (
    <div role="dialog" aria-label="listing">
      <span>{agent.name}</span>
      <button onClick={onClose}>cancel-listing</button>
      <button
        disabled={isSubmitting}
        onClick={() =>
          void onSubmit({
            content: "Please review",
            tags: ["support"],
            icon_url: null,
          })
        }
      >
        submit-listing
      </button>
    </div>
  ),
}));

const agent = {
  id: "42",
  name: "assistant",
  display_name: "Assistant",
  description: "Helps users",
  permission: "EDIT",
  current_version_no: 3,
  repository_info: [],
  model: "model",
  max_step: 5,
  provide_run_summary: false,
  tools: [],
} as Agent;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.createListing.mockResolvedValue({});
});

async function openMenu(
  overrides: Partial<Agent> = {},
  variant: "menu" | "table" = "menu"
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const current = { ...agent, ...overrides };
  render(
    <QueryClientProvider client={client}>
      <App>
        <AgentConfigActions
          agent={current}
          agentId={42}
          agentName={current.display_name}
          readOnly={current.permission === "READ_ONLY"}
          variant={variant}
        />
      </App>
    </QueryClientProvider>
  );
  fireEvent.click(
    screen.getByRole("button", { name: "agentRepository.mine.menu.more" })
  );
  await screen.findByRole("menu");
  return { invalidate };
}

test("shows listing and evaluation first without configuration or publication shortcuts", async () => {
  await openMenu();
  expect(
    screen.queryByRole("menuitem", { name: "agentConfig.list.configure" })
  ).toBeNull();
  expect(
    screen
      .getAllByRole("menuitem")
      .slice(0, 2)
      .map((item) => item.textContent)
  ).toEqual(["agentConfig.list.listing", "agentRepository.mine.evaluate"]);
  expect(
    screen.queryByRole("menuitem", { name: "agentConfig.list.publish" })
  ).toBeNull();
  expect(mocks.createListing).not.toHaveBeenCalled();
});

test.each([
  { current_version_no: 0 },
  { permission: "READ_ONLY" },
  {
    repository_info: [
      { agent_repository_id: 8, version_no: 3, status: "pending_review" },
    ],
  },
  {
    repository_info: [
      { agent_repository_id: 8, version_no: 3, status: "shared" },
    ],
  },
  {
    repository_info: [
      { agent_repository_id: 8, version_no: 3, status: "rejected" },
    ],
  },
] as Partial<Agent>[])(
  "prevents listing for ineligible metadata %j",
  async (overrides) => {
    await openMenu(overrides);
    const listing = screen.getByRole("menuitem", {
      name: "agentConfig.list.listing",
    });
    expect(listing).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(listing);
    expect(screen.queryByRole("dialog", { name: "listing" })).toBeNull();
    expect(mocks.createListing).not.toHaveBeenCalled();
  }
);

test("allows listing a new version and refreshes repository and configuration caches after submission", async () => {
  const { invalidate } = await openMenu({
    repository_info: [
      { agent_repository_id: 8, version_no: 2, status: "shared" },
    ],
  });
  fireEvent.click(
    screen.getByRole("menuitem", { name: "agentConfig.list.listing" })
  );
  expect(
    await screen.findByRole("dialog", { name: "listing" })
  ).toHaveTextContent("Assistant");
  expect(mocks.createListing).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("submit-listing"));
  await waitFor(() =>
    expect(mocks.createListing).toHaveBeenCalledExactlyOnceWith(42, 3, {
      content: "Please review",
      tags: ["support"],
      icon_url: null,
    })
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "listing" })).toBeNull()
  );
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agents"] });
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: ["agentRepositoryListings"],
  });
});

test("keeps the application open on failure and supports retry", async () => {
  mocks.createListing.mockRejectedValueOnce(new Error("Network unavailable"));
  await openMenu();
  fireEvent.click(
    screen.getByRole("menuitem", { name: "agentConfig.list.listing" })
  );
  fireEvent.click(await screen.findByText("submit-listing"));
  await screen.findByText("repository.mine.applyError");
  expect(screen.getByRole("dialog", { name: "listing" })).toBeInTheDocument();
  fireEvent.click(screen.getByText("submit-listing"));
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "listing" })).toBeNull()
  );
  expect(mocks.createListing).toHaveBeenCalledTimes(2);
});

test("cancels without applying", async () => {
  await openMenu();
  fireEvent.click(
    screen.getByRole("menuitem", { name: "agentConfig.list.listing" })
  );
  fireEvent.click(await screen.findByText("cancel-listing"));
  expect(screen.queryByRole("dialog", { name: "listing" })).toBeNull();
  expect(mocks.createListing).not.toHaveBeenCalled();
});

test.each(["menu", "table"] as const)(
  "evaluates a published readonly Agent from %s with its ID selected",
  async (variant) => {
    await openMenu({ permission: "READ_ONLY" }, variant);
    fireEvent.click(
      screen.getByRole("menuitem", { name: "agentRepository.mine.evaluate" })
    );
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith(
      `/zh/evaluation?agent_ids=${encodeURIComponent("[42]")}`
    );
    expect(mocks.createListing).not.toHaveBeenCalled();
  }
);

test("does not navigate to evaluation for an unpublished Agent", async () => {
  await openMenu({ current_version_no: 0 });
  const evaluate = screen.getByRole("menuitem", {
    name: "agentRepository.mine.evaluate",
  });
  expect(evaluate).toHaveAttribute("aria-disabled", "true");
  fireEvent.click(evaluate);
  expect(mocks.push).not.toHaveBeenCalled();
});
