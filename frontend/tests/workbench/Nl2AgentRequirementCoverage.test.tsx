// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { RequirementCoverageCard as UnifiedCoverage } from "@/app/newchat/ui/requirement-coverage-card";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import type {
  Nl2aUnifiedResourcesPayload,
  Nl2aInstallableResource,
} from "@/app/newchat/adapter/remote-chat-model-adapter";

const { append, fetchWithAuth, installOfficialSkills, threadState } =
  vi.hoisted(() => ({
    append: vi.fn(),
    fetchWithAuth: vi.fn(),
    installOfficialSkills: vi.fn(),
    threadState: { running: false },
  }));
beforeEach(() => {
  threadState.running = false;
  fetchWithAuth.mockReset();
});
vi.mock("@/lib/auth", () => ({ fetchWithAuth }));
vi.mock("@/services/skillService", () => ({
  installOfficialSkills,
  fetchOfficialSkillsWithStatus: async () => [
    { name: "weather", status: "installed", skill_id: 17 },
  ],
}));
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("antd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("antd")>();
  return {
    ...actual,
    App: { useApp: () => ({ message: { success: vi.fn() } }) },
  };
});
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      append,
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
  useAuiState: () => threadState.running,
}));

const payload: Nl2aUnifiedResourcesPayload = {
  subtype: "requirement_resources",
  protocol_version: 2,
  purpose: "generate",
  resources: [],
  agent_id: 42,
  conversation_id: "1",
  run_id: "run",
  card_id: "card",
  state_version: 3,
  requirements: [
    {
      requirement_id: "weather",
      query: "Find weather",
      required: true,
      coverage_status: "uncovered",
      covered_resources: [],
      installable_resources: [],
    },
  ],
};

const repositoryPayload: Nl2aUnifiedResourcesPayload = {
  ...payload,
  requirements: [
    {
      ...payload.requirements[0],
      coverage_status: "installable",
      installable_resources: [
        {
          candidate_ref: "tenant_mcp_repository:3",
          name: "12306",
          resource_type: "mcp_server",
          installation_status: "disabled",
        },
      ],
    },
  ],
};

function RequirementCoverageCard({
  payload,
  disabled,
  busy = false,
}: {
  payload: Nl2aUnifiedResourcesPayload;
  disabled?: boolean;
  busy?: boolean;
}) {
  return (
    <UnifiedCoverage
      payload={payload}
      disabled={disabled}
      binding={{
        busy,
        footer: <footer>Binding actions</footer>,
        renderResources: () => null,
        status: (id) =>
          payload.requirements.find((row) => row.requirement_id === id)
            ?.coverage_status === "uncovered"
            ? "unmatched"
            : "choose",
        onAccepted: () => undefined,
        onEditingChange: () => undefined,
      }}
    />
  );
}

it.each([{ disabled: true }, { busy: true }])(
  "does not refresh installation status for an inactive historical card: %j",
  async (props) => {
    fetchWithAuth.mockResolvedValue(
      Response.json({
        remote_mcp_server_list: [{ market_id: 3, enabled: true }],
      })
    );
    render(
      <Nl2AgentFlowProvider>
        <RequirementCoverageCard payload={repositoryPayload} {...props} />
      </Nl2AgentFlowProvider>
    );
    await act(async () => {});
    expect(fetchWithAuth).not.toHaveBeenCalled();
    expect(screen.getByText("Installed, disabled")).toBeDefined();
  }
);

it("refreshes installation status only after a card becomes interactive", async () => {
  fetchWithAuth.mockResolvedValue(
    Response.json({ remote_mcp_server_list: [] })
  );
  threadState.running = true;
  const card = (
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={repositoryPayload} />
    </Nl2AgentFlowProvider>
  );
  const { rerender } = render(card);
  expect(fetchWithAuth).not.toHaveBeenCalled();
  threadState.running = false;
  rerender(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={repositoryPayload} />
    </Nl2AgentFlowProvider>
  );
  await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
  expect(fetchWithAuth.mock.calls[0][0]).toContain(
    "installation_status_only=true"
  );
});

it.each([{ disabled: true }, { busy: true }])(
  "cancels an installation refresh and ignores its late response when the card becomes inactive: %j",
  async (props) => {
    let complete!: (response: Response) => void;
    fetchWithAuth.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          complete = resolve;
        })
    );
    const { rerender } = render(
      <Nl2AgentFlowProvider>
        <RequirementCoverageCard payload={repositoryPayload} />
      </Nl2AgentFlowProvider>
    );
    await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
    const signal = fetchWithAuth.mock.calls[0][1]?.signal as
      AbortSignal | undefined;
    rerender(
      <Nl2AgentFlowProvider>
        <RequirementCoverageCard payload={repositoryPayload} {...props} />
      </Nl2AgentFlowProvider>
    );
    await act(async () => {
      complete(
        Response.json({
          remote_mcp_server_list: [{ market_id: 3, enabled: true }],
        })
      );
    });
    expect(signal?.aborted).toBe(true);
    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Installed, disabled")).toBeDefined();
  }
);

it("does not query installation status in recommendation mode", async () => {
  fetchWithAuth.mockResolvedValue(
    Response.json({ remote_mcp_server_list: [] })
  );
  render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard
        payload={{ ...repositoryPayload, purpose: "recommend" }}
      />
    </Nl2AgentFlowProvider>
  );
  await act(async () => {});
  expect(fetchWithAuth).not.toHaveBeenCalled();
});

it("shows the recorded snapshot again after an interactive card becomes read-only", async () => {
  fetchWithAuth.mockResolvedValue(
    Response.json({ remote_mcp_server_list: [{ market_id: 3, enabled: true }] })
  );
  const { rerender } = render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={repositoryPayload} />
    </Nl2AgentFlowProvider>
  );
  expect(await screen.findByText("Installed", { exact: true })).toBeDefined();
  rerender(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={repositoryPayload} disabled />
    </Nl2AgentFlowProvider>
  );
  expect(screen.getByText("Installed, disabled")).toBeDefined();
  expect(fetchWithAuth).toHaveBeenCalledTimes(1);
});

it("stops refreshing when a registered card has already been submitted", async () => {
  function SubmittedCard() {
    const { submitCard } = useNl2AgentFlow();
    return (
      <>
        <button onClick={() => submitCard("card")}>Submit current card</button>
        <RequirementCoverageCard payload={repositoryPayload} />
      </>
    );
  }
  fetchWithAuth.mockImplementation(() => new Promise<Response>(() => {}));
  render(
    <Nl2AgentFlowProvider>
      <SubmittedCard />
    </Nl2AgentFlowProvider>
  );
  await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(1));
  const signal = fetchWithAuth.mock.calls[0][1]?.signal as
    AbortSignal | undefined;
  fireEvent.click(screen.getByRole("button", { name: "Submit current card" }));
  expect(signal?.aborted).toBe(true);
  expect(fetchWithAuth).toHaveBeenCalledTimes(1);
});

function Fixture() {
  const { markRunStarted, markRunFinished } = useNl2AgentFlow();
  return (
    <>
      <button onClick={() => markRunStarted(42)}>
        Run configuration change
      </button>
      <button onClick={() => markRunFinished(42)}>
        Finish configuration change
      </button>
      <RequirementCoverageCard payload={payload} />
    </>
  );
}

it("retains the changed requirement and submits the current card only on confirmation", () => {
  append.mockClear();
  render(
    <Nl2AgentFlowProvider>
      <Fixture />
    </Nl2AgentFlowProvider>
  );
  expect(
    screen.getByText("nl2agent.unified.unmatchedTitle")
  ).toBeDefined();
  expect(screen.getByRole("button", { name: "Create Skill" })).toBeDefined();
  expect(screen.getByRole("button", { name: "nl2agent.unified.createMcp" })).toBeDefined();
  expect(screen.queryByRole("textbox", { name: "Requirement" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Edit requirement" }));
  const editor = screen.getByRole("textbox", { name: "Requirement" });
  fireEvent.change(screen.getByRole("textbox", { name: "Requirement" }), {
    target: { value: "Find current weather" },
  });
  fireEvent.blur(editor);
  expect(screen.getByText("Find current weather")).toBeDefined();
  fireEvent.click(screen.getByText("Run configuration change"));
  fireEvent.click(screen.getByText("Finish configuration change"));
  expect(screen.getByRole("button", { name: "Create Skill" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "nl2agent.unified.createMcp" })).toBeDisabled();
  expect(append).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "nl2agent.unified.update" })
  );
  expect(append).toHaveBeenCalledOnce();
  expect(append.mock.calls[0][0].metadata.custom.nl2agentCardAction).toEqual({
    type: "nl2agent_card_action",
    subtype: "requirement_resources",
    agent_id: 42,
    action: "confirm_requirements",
    result: {
      card_id: "card",
      state_version: 3,
      requirements: [
        {
          requirement_id: "weather",
          query: "Find current weather",
        },
      ],
    },
  });
});

it("keeps a historical coverage card read-only", () => {
  append.mockClear();
  render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={payload} disabled />
    </Nl2AgentFlowProvider>
  );
  expect(screen.getByText("Find weather")).toBeDefined();
  expect(screen.queryByRole("textbox", { name: "Requirement" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Edit requirement" })).toBeNull();
  expect(
    screen.queryByRole("button", { name: "nl2agent.unified.update" })
  ).toBeNull();
  expect(append).not.toHaveBeenCalled();
});

it("adds an inline requirement on Enter without prematurely confirming the card", () => {
  append.mockClear();
  render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={payload} />
    </Nl2AgentFlowProvider>
  );
  fireEvent.click(screen.getAllByRole("button", { name: "Add requirement" })[0]);
  const input = screen.getByRole("textbox", { name: "Add requirement" });
  const confirm = screen.getByRole("button", {
    name: "nl2agent.unified.update",
  });
  fireEvent.change(input, { target: { value: " Send a text message " } });
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.getByText("Send a text message")).toBeDefined();
  expect(append).not.toHaveBeenCalled();
  fireEvent.click(confirm);
  expect(
    append.mock.calls[0][0].metadata.custom.nl2agentCardAction.result
      .requirements[1]
  ).toMatchObject({
    client_key: expect.any(String),
    query: "Send a text message",
  });
});

it("shows numeric relevance scores and removes the requirement from the submission", () => {
  append.mockClear();
  const scored = {
    ...payload,
    requirements: [
      {
        ...payload.requirements[0],
        coverage_status: "installable" as const,
        installable_resources: [
          { candidate_ref: "tool:17", name: "Weather", retrieval_score: 0.85 },
          { candidate_ref: "tool:18", name: "Forecast", retrieval_score: 0.6 },
          { candidate_ref: "tool:19", name: "Climate", retrieval_score: 0.599 },
          { candidate_ref: "tool:20", name: "Missing score" },
          {
            candidate_ref: "tool:21",
            name: "Invalid score",
            retrieval_score: NaN,
          },
          {
            candidate_ref: "tool:22",
            name: "Infinite score",
            retrieval_score: Infinity,
          },
          { candidate_ref: "tool:23", name: "Zero score", retrieval_score: 0 },
        ],
      },
    ],
  };
  render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={scored} />
    </Nl2AgentFlowProvider>
  );
  expect(screen.getByText("Related resources")).toBeDefined();
  expect(screen.getByText("85").parentElement).toHaveTextContent(
    "Relevance score: 85 points"
  );
  expect(screen.getByText("85")).toHaveClass("text-[var(--color-success)]");
  expect(screen.getAllByText("60")).toHaveLength(2);
  for (const score of screen.getAllByText("60")) {
    expect(score.parentElement).toHaveTextContent("Relevance score: 60 points");
  }
  expect(screen.getByText("0").parentElement).toHaveTextContent(
    "Relevance score: 0 points"
  );
  expect(screen.getAllByText(/^Relevance score:/)).toHaveLength(4);
  expect(screen.queryByRole("img", { name: /relevance/i })).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(
    screen.getByRole("button", { name: "nl2agent.unified.noResources" })
  );
  expect(
    append.mock.calls[0][0].metadata.custom.nl2agentCardAction.result
      .requirements
  ).toEqual([]);
});

it("refreshes installed MCP status on a coverage card created before installation", async () => {
  fetchWithAuth.mockReset().mockResolvedValueOnce(
    Response.json({
      remote_mcp_server_list: [{ market_id: 3, enabled: false }],
    })
  );
  const { container } = render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard
        payload={{
          ...payload,
          requirements: [
            {
              ...payload.requirements[0],
              coverage_status: "installable",
              installable_resources: [
                {
                  candidate_ref: "tenant_mcp_repository:3",
                  name: "12306",
                  resource_type: "mcp_server",
                },
              ],
            },
          ],
        }}
      />
    </Nl2AgentFlowProvider>
  );
  expect(await screen.findByText("Installed, disabled")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Install 12306" })).toBeNull();
  expect(container.querySelector("footer")).toHaveTextContent("Binding actions");
});

it("installs in the coverage row and retries only association after a failed link", async () => {
  fetchWithAuth.mockReset();
  installOfficialSkills.mockReset().mockResolvedValue(undefined);
  const weather: Nl2aInstallableResource = {
    candidate: {
      candidate_ref: "nexent_official_skill:weather",
      name: "Weather",
      description: "",
      resource_type: "skill",
      source: "NEXENT_OFFICIAL_SKILL",
      requirement_ids: ["weather"],
      score: 1,
    },
    recommendation: "recommended",
    form_kind: "SKILL_CONFIG",
    config: [],
    default_option_id: "official",
    installation_options: [
      {
        option_id: "official",
        label: "Install",
        form_kind: "SKILL_CONFIG",
        config: [],
      },
    ],
  };
  fetchWithAuth.mockResolvedValueOnce(Response.json({ resources: [weather] }));
  fetchWithAuth.mockResolvedValueOnce(
    Response.json({
      status: "claimed",
      target_name: "weather",
      attempt_id: "attempt",
    })
  );
  fetchWithAuth.mockResolvedValueOnce(Response.json({}, { status: 409 }));
  fetchWithAuth.mockResolvedValueOnce(Response.json({ status: "linked" }));
  const installable: Nl2aUnifiedResourcesPayload = {
    ...payload,
    requirements: [
      {
        ...payload.requirements[0],
        coverage_status: "installable",
        installable_resources: [
          {
            candidate_ref: "nexent_official_skill:weather",
            name: "Weather",
          },
        ],
      },
    ],
  };
  render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard payload={installable} />
    </Nl2AgentFlowProvider>
  );
  expect(screen.queryByText("Install to verify")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Install Weather" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
  await waitFor(() => expect(fetchWithAuth).toHaveBeenCalledTimes(4));
  expect(installOfficialSkills).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId("nl2agent-installation-card")).toBeNull();
  expect(fetchWithAuth.mock.calls[3]).toEqual(fetchWithAuth.mock.calls[2]);
  expect(JSON.parse(fetchWithAuth.mock.calls[3][1].body)).toMatchObject({
    card_id: "card",
    state_version: 3,
    requirement_id: "weather",
    resource_id: 17,
  });
  expect(
    await screen.findByRole("button", { name: "nl2agent.unified.verify" })
  ).toBeEnabled();
});

it("asks for a missing MCP URL inside the coverage row before installing", async () => {
  const candidate = {
    candidate_ref: "tenant_mcp_repository:8",
    name: "Ticket service",
    description: "",
    resource_type: "mcp_server",
    source: "TENANT_MCP_REPOSITORY",
    requirement_ids: ["weather"],
    score: 1,
  } as const;
  fetchWithAuth
    .mockReset()
    .mockResolvedValueOnce(Response.json({ remote_mcp_server_list: [] }))
    .mockResolvedValueOnce(
      Response.json({
        resources: [
          {
            candidate,
            recommendation: "recommended",
            form_kind: "MCP_REMOTE",
            config: {},
            default_option_id: "remote",
            installation_options: [
              {
                option_id: "remote",
                label: "Remote",
                form_kind: "MCP_REMOTE",
                config: {},
              },
            ],
          },
        ],
      })
    )
    .mockResolvedValueOnce(
      Response.json({
        status: "installed",
        resource_type: "mcp_server",
        resource_id: 24,
      })
    )
    .mockResolvedValueOnce(Response.json({ status: "linked" }));
  render(
    <Nl2AgentFlowProvider>
      <RequirementCoverageCard
        payload={{
          ...payload,
          requirements: [
            {
              ...payload.requirements[0],
              coverage_status: "installable",
              installable_resources: [{ ...candidate }],
            },
          ],
        }}
      />
    </Nl2AgentFlowProvider>
  );
  const install = screen.getByRole("button", {
    name: "Install Ticket service",
  });
  await waitFor(() =>
    expect((install as HTMLButtonElement).disabled).toBe(false)
  );
  fireEvent.click(install);
  const url = await screen.findByRole("textbox", { name: "URL" });
  expect(fetchWithAuth).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByTestId("nl2agent-installation-card")).toBeNull();
  fireEvent.change(url, { target: { value: "https://example.test/mcp" } });
  fireEvent.click(screen.getByRole("button", { name: "Install" }));
  expect(
    await screen.findByRole("button", { name: "nl2agent.unified.verify" })
  ).toBeEnabled();
  expect(fetchWithAuth).toHaveBeenCalledTimes(4);
});
