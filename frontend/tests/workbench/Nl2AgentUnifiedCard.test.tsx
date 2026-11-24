// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  RequirementCoverageCard,
  type UnifiedBindingView,
} from "@/app/newchat/ui/requirement-coverage-card";
import { restoreUnifiedDraft } from "@/app/newchat/ui/nl2agent-unified-draft";
import type { Nl2aUnifiedResourcesPayload } from "@/app/newchat/adapter/remote-chat-model-adapter";

const mocks = vi.hoisted(() => ({
  append: vi.fn(),
  editing: vi.fn(),
  accepted: vi.fn(),
}));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  const { default: values } =
    await import("../../public/locales/en/common.json");
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, fallback?: string | object) =>
        typeof (values as Record<string, unknown>)[key] === "string"
          ? (values as Record<string, unknown>)[key]
          : typeof fallback === "string"
            ? fallback
            : key,
    }),
  };
});
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      append: mocks.append,
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
  useAuiState: () => false,
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({
    registerCard: vi.fn(),
    submitCard: vi.fn(),
    isCardInteractive: () => true,
  }),
}));

const payload: Nl2aUnifiedResourcesPayload = {
  protocol_version: 2,
  subtype: "requirement_resources",
  purpose: "generate",
  agent_id: 42,
  conversation_id: "conversation",
  run_id: "run",
  card_id: "card",
  state_version: 2,
  resources: [],
  requirements: [
    {
      requirement_id: "r1",
      query: "Search public websites",
      required: true,
      search_queries: { zh: "联网搜索", en: "web search" },
      coverage_status: "covered",
      covered_resources: [
        { candidate_ref: "tool:1", name: "Search", retrieval_score: 0.9 },
      ],
      installable_resources: [],
    },
  ],
};
const binding = (): UnifiedBindingView => ({
  busy: false,
  footer: <button>Bind 1 resource</button>,
  renderResources: () => <span>Existing search resource</span>,
  status: () => "pending",
  onAccepted: mocks.accepted,
  onEditingChange: mocks.editing,
});

beforeEach(() => vi.clearAllMocks());

it("shows a matching icon for each summary state without repeating row status text", () => {
  render(<RequirementCoverageCard payload={payload} binding={binding()} />);
  const summary = screen.getByText(/^Awaiting binding/).closest("span")!;
  expect(summary.querySelector("svg")).not.toBeNull();
  expect(screen.getByRole("img", { name: "Awaiting binding" })).toBeVisible();
  expect(screen.getAllByText(/^Awaiting binding/)).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: "Edit requirement" })
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "Remove" })).toBeVisible();
});

it("collapses resources and creation actions with an accessible, larger details button", () => {
  render(<RequirementCoverageCard payload={payload} binding={binding()} />);
  const toggle = screen.getByRole("button", {
    name: "Toggle details: {{query}}",
  });
  expect(toggle).toHaveClass("size-7");
  expect(toggle.parentElement).toContainElement(
    screen.getByText("联网搜索 · web search")
  );
  expect(toggle.parentElement).not.toContainElement(
    screen.getByText("Search public websites")
  );
  const createSkill = screen.getByRole("button", { name: "Create Skill" });
  expect(createSkill).not.toHaveClass("border");
  expect(createSkill.querySelector("svg")).toBeNull();
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByText("Existing search resource")).not.toBeVisible();
  expect(screen.queryByRole("button", { name: "Create Skill" })).toBeNull();
  fireEvent.click(toggle);
  expect(screen.getByText("Existing search resource")).toBeVisible();
  expect(screen.getByRole("button", { name: "Create MCP" })).toBeVisible();
});

it("shows a dedicated no-match explanation with both existing creation actions", () => {
  render(
    <RequirementCoverageCard
      payload={{
        ...payload,
        requirements: [
          {
            ...payload.requirements[0],
            coverage_status: "uncovered",
            covered_resources: [],
          },
        ],
      }}
      binding={{ ...binding(), status: () => "unmatched" }}
    />
  );
  const explanation = screen.getByText(
    "No candidate has passed verification for this requirement"
  ).parentElement!;
  expect(explanation).toHaveClass("border-dashed");
  expect(explanation.className).toContain("bg-[var(--color-alert-subtler)]/60");
  expect(
    within(explanation).getByText(
      "Create a Skill or connect an MCP service. It will be added to this requirement automatically."
    )
  ).toBeVisible();
  expect(
    within(explanation).getByRole("button", { name: "Create Skill" })
  ).toBeEnabled();
  expect(
    within(explanation).getByRole("button", { name: "Create MCP" })
  ).toBeEnabled();
  expect(screen.queryByText("Existing search resource")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Edit requirement" }));
  expect(
    within(explanation).getByRole("button", { name: "Create Skill" })
  ).toBeDisabled();
  expect(
    within(explanation).getByRole("button", { name: "Create MCP" })
  ).toBeDisabled();
});

it("enters requirement editing while retaining resources, and cancel restores without a run", () => {
  render(<RequirementCoverageCard payload={payload} binding={binding()} />);
  expect(screen.getByRole("button", { name: "Bind 1 resource" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Edit requirement" }));
  expect(mocks.editing).toHaveBeenLastCalledWith(true);
  expect(screen.getByText("Existing search resource")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Bind 1 resource" })).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "Requirement" }), {
    target: { value: "Changed query" },
  });
  fireEvent.blur(screen.getByRole("textbox", { name: "Requirement" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel changes" }));
  expect(screen.getByText("Search public websites")).toBeVisible();
  expect(mocks.editing).toHaveBeenLastCalledWith(false);
  expect(mocks.append).not.toHaveBeenCalled();
});

it("only submits the edited query and keeps derived bilingual phrases read-only", () => {
  render(<RequirementCoverageCard payload={payload} binding={binding()} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit requirement" }));
  expect(
    screen.getByRole("button", { name: "Update requirements and search again" })
  ).toBeDisabled();
  expect(screen.getByText("联网搜索 · web search")).toBeVisible();
  const input = screen.getByRole("textbox", { name: "Requirement" });
  fireEvent.change(input, { target: { value: "Search official websites" } });
  fireEvent.blur(input);
  fireEvent.click(
    screen.getByRole("button", { name: "Update requirements and search again" })
  );
  const action =
    mocks.append.mock.calls[0][0].metadata.custom.nl2agentCardAction;
  expect(action.subtype).toBe("requirement_resources");
  expect(action.action).toBe("confirm_requirements");
  expect(action.result.requirements).toEqual([
    { requirement_id: "r1", query: "Search official websites" },
  ]);
  expect(action.result).not.toHaveProperty("search_queries");
});

it("deleting all requirements offers explicit continuation without an empty search", () => {
  render(<RequirementCoverageCard payload={payload} binding={binding()} />);
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Continue without resources" })
  );
  expect(
    mocks.append.mock.calls[0][0].metadata.custom.nl2agentCardAction.result
      .requirements
  ).toEqual([]);
});

it("retains only unchanged requirement selections when restoring the accepted update chain", () => {
  const next = {
    ...payload,
    requirements: [
      payload.requirements[0],
      { ...payload.requirements[0], requirement_id: "r2", query: "New query" },
    ],
  };
  const result = restoreUnifiedDraft(
    next,
    [
      {
        resource: {
          candidate: {
            candidate_ref: "tool:1",
            resource_type: "tool",
            source: "LOCAL_TOOL",
            name: "Search",
            description: "Search websites",
            requirement_ids: ["r1", "r2"],
            score: 0.9,
          },
          recommendation: "recommended",
          is_bound: false,
          form_kind: "TOOL_CONFIG",
          config: [],
        },
        selected: true,
        configStatus: "valid",
        bindingStatus: "idle",
        draftParams: [],
        fieldErrors: [],
      },
    ],
    {
      queries: { r1: "Search public websites", r2: "Old query" },
      selections: { r1: [], r2: ["tool:99"] },
      items: [],
    }
  );
  expect(result.selections).toEqual({ r1: [], r2: ["tool:1"] });
});
