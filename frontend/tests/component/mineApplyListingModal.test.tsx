// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Relative import: the component-suite vitest config maps "@" to the frontend
// root but has no "@/app" -> "app/[locale]" rule, so the literal relative path
// is the only form that resolves in both places.
import { MineApplyListingModal } from "../../app/[locale]/agent-space/components/MineApplyListingModal";
import agentRepositoryService from "@/services/agentRepositoryService";
import { tagManagementApi } from "@/services/tagManagementService";
import zh from "@/public/locales/zh/common.json";
import type { MyEditableAgentItem } from "@/types/agentRepository";
import type {
  TagAssignment,
  TagDefinition,
  TagValue,
} from "@/types/tagManagement";

// Resolve keys against the real zh bundle with {{var}} interpolation so a
// key/variable mismatch fails here instead of leaking a raw placeholder into
// the UI. A key that is absent from the bundle falls back to the key itself,
// which mirrors i18next and makes "component still reads a deleted key"
// observable as raw key text on screen.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      key: string,
      options?: { defaultValue?: string } & Record<string, unknown>
    ) => {
      const template =
        (zh as unknown as Record<string, string>)[key] ??
        options?.defaultValue ??
        key;
      return String(template).replace(
        /\{\{(\w+)\}\}/g,
        (placeholder: string, name: string) =>
          options && options[name] !== undefined
            ? String(options[name])
            : placeholder
      );
    },
  }),
}));

// The modal loads listings and tags through react-query hooks. Stub the two
// services the hooks wrap so the real hooks, the real assignment -> listing
// tag mapping and the real submit gate all execute in this test.
vi.mock("@/services/agentRepositoryService", () => ({
  default: {
    fetchAgentRepositoryListings: vi.fn(),
  },
}));

vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(),
    listDefinitions: vi.fn(),
    getAssignments: vi.fn(),
  },
}));

const CATEGORY_DEFINITION_ID = 30;

const CATEGORY_VALUES = [
  {
    value_id: 1,
    display_value: "营销",
    normalized_value: "marketing",
    sort_order: 0,
    status: "active",
  },
  {
    value_id: 2,
    display_value: "代码审查",
    normalized_value: "code_review",
    sort_order: 1,
    status: "active",
  },
  {
    value_id: 3,
    display_value: "质量",
    normalized_value: "quality",
    sort_order: 2,
    status: "active",
  },
  {
    value_id: 4,
    display_value: "数据",
    normalized_value: "data",
    sort_order: 3,
    status: "active",
  },
  {
    value_id: 5,
    display_value: "BI",
    normalized_value: "bi",
    sort_order: 4,
    status: "active",
  },
  {
    value_id: 6,
    display_value: "自动化",
    normalized_value: "automation",
    sort_order: 5,
    status: "active",
  },
] as TagValue[];

const AGENT_CATEGORY = {
  definition_id: CATEGORY_DEFINITION_ID,
  bucket_id: 1,
  definition_key: "agent_category",
  definition_name: "Agent category",
  selection_mode: "multi_select",
  sort_order: 0,
  status: "active",
  active_value_count: CATEGORY_VALUES.length,
  value_capacity: 100,
  values: CATEGORY_VALUES,
} as TagDefinition;

const AGENT: MyEditableAgentItem = {
  agent_id: 7,
  name: "Support copilot",
  current_version_no: 3,
  version_label: "v3",
  permission: "EDIT",
  repository_info: [],
};

/** Assignment payload for the given agent-category value ids. */
function assignmentsFor(valueIds: number[]): TagAssignment {
  return {
    resource_type: "agent",
    resource_id: String(AGENT.agent_id),
    assignment_count: valueIds.length,
    assignment_capacity: 100,
    assignments: valueIds.map((valueId) => {
      const value = CATEGORY_VALUES.find((item) => item.value_id === valueId);
      return {
        definition_id: CATEGORY_DEFINITION_ID,
        definition_key: AGENT_CATEGORY.definition_key,
        definition_name: AGENT_CATEGORY.definition_name,
        selection_mode: "multi_select",
        value_id: valueId,
        display_value: value?.display_value ?? "",
        value_status: "active",
      };
    }),
  };
}

function renderModal() {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <App>{children}</App>
    </QueryClientProvider>
  );
  render(
    <MineApplyListingModal
      open
      agent={AGENT}
      onClose={onClose}
      onSubmit={onSubmit}
    />,
    { wrapper }
  );
  return { onSubmit, onClose };
}

async function submitApplication(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "提交申请" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(
    agentRepositoryService.fetchAgentRepositoryListings
  ).mockResolvedValue({ items: [] });
  vi.mocked(tagManagementApi.listLibraries).mockResolvedValue([
    {
      bucket_id: 1,
      bucket_key: "default_resource",
      bucket_name: "Resources",
      status: "active",
      resource_types: ["agent", "skill", "knowledge_base", "tool"],
      definition_count: 1,
      definition_capacity: 100,
    },
  ]);
  vi.mocked(tagManagementApi.listDefinitions).mockResolvedValue([
    AGENT_CATEGORY,
  ]);
  vi.mocked(tagManagementApi.getAssignments).mockResolvedValue(
    assignmentsFor([])
  );
});

describe("MineApplyListingModal listing tags are optional", () => {
  it("submits an application when the agent has no tag at all", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderModal();

    // The tag field advertises itself as optional instead of blocking submit.
    expect(
      await screen.findByText("最多选择 5 个标签（选填）")
    ).toBeInTheDocument();

    await submitApplication(user);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      icon_url: null,
      tags: [],
      content: "",
    });

    // Regression: the deleted "tags are required" key must not reappear as
    // raw key text, which is what the i18n mock renders for an absent key.
    expect(
      screen.queryByText("agentRepository.mine.applyModal.validation.tags")
    ).not.toBeInTheDocument();
  });

  it("still sends the localized tags that the user selected", async () => {
    vi.mocked(tagManagementApi.getAssignments).mockResolvedValue(
      assignmentsFor([1, 4])
    );
    const user = userEvent.setup();
    const { onSubmit } = renderModal();

    expect(await screen.findByText("营销 · 数据")).toBeInTheDocument();

    await submitApplication(user);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      icon_url: null,
      tags: ["营销", "数据"],
      content: "",
    });
  });

  it("still rejects a submission above the tag limit", async () => {
    vi.mocked(tagManagementApi.getAssignments).mockResolvedValue(
      assignmentsFor(CATEGORY_VALUES.map((value) => value.value_id))
    );
    const user = userEvent.setup();
    const { onSubmit } = renderModal();

    await screen.findByText("营销 · 代码审查 · 质量 · 数据 · BI · 自动化");

    await submitApplication(user);

    expect(
      await screen.findByText("最多只能选择 5 个标签")
    ).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
