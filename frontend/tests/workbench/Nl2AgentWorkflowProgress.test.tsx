// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  isFullGenerationTurn,
  projectNl2AgentWorkflow,
} from "@/app/newchat/assistant-ui/nl2agent-workflow-state";
import {
  Nl2AgentWorkflowHeader,
  Nl2AgentWorkflowProgress,
} from "@/app/newchat/assistant-ui/nl2agent-workflow-progress";
import { recordNl2AgentState } from "@/app/newchat/adapter/nl2agent-state-history";

const thread = vi.hoisted(() => ({
  messages: [] as unknown[],
  isRunning: false,
}));
vi.mock("@assistant-ui/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@assistant-ui/react")>()),
  useAuiState: (selector: (state: { thread: typeof thread }) => unknown) =>
    selector({ thread }),
}));

const state = (stage: string, sequence = 1, run_id = "run") => ({
  event: "resource_retrieval_progress",
  agent_id: 42,
  stage,
  sequence,
  run_id,
});
const message = (events: unknown[] = [], card?: object) => ({
  role: "assistant",
  content: [],
  metadata: {
    custom: {
      nl2agentStates: events,
      ...(card ? { nl2a: { content: { agent_id: 42, ...card } } } : {}),
    },
  },
});
const project = (messages: unknown[], isRunning = false) =>
  projectNl2AgentWorkflow({
    agentId: 42,
    messages,
    isRunning,
    phase: "idle",
  });

const unifiedCard = (statuses: string[]) => ({
  subtype: "requirement_resources",
  resources: [{ candidate: { candidate_ref: "tool:1" } }],
  requirements: statuses.map((coverage_status, index) => ({
    requirement_id: `r${index}`,
    coverage_status,
    covered_resources:
      coverage_status === "covered" ? [{ candidate_ref: "tool:1" }] : [],
    installable_resources:
      coverage_status === "installable"
        ? [{ candidate_ref: "skill_repository:1" }]
        : [],
  })),
});

it.each(["uncovered", "installable", "pending"])(
  "keeps unified cards with a %s requirement in coverage despite other bindable resources",
  (status) => {
    expect(
      project([message([], unifiedCard(["covered", status]))])
    ).toMatchObject({
      current: 1,
      status: "waiting",
      detail: "resolveGaps",
    });
  }
);

it("advances to binding only when every retained requirement has verified installed coverage", () => {
  expect(
    project([message([], unifiedCard(["covered", "covered"]))])
  ).toMatchObject({
    current: 2,
    status: "waiting",
    detail: "selectResources",
  });
  const invalid = unifiedCard(["covered"]);
  invalid.requirements[0].covered_resources = [];
  expect(project([message([], invalid)]).current).toBe(1);
  expect(project([message([], unifiedCard([]))]).current).toBe(1);
});

it("replays complete coverage, rolls back for a new gap and returns to binding after it is resolved", () => {
  const complete = message([], unifiedCard(["covered", "covered"]));
  const gap = message([], unifiedCard(["covered", "uncovered"]));
  expect(project([complete, gap]).current).toBe(1);
  expect(project([complete, gap, complete]).current).toBe(2);
  expect(
    project([message([], { ...unifiedCard(["covered"]), agent_id: 99 })])
      .current
  ).toBe(0);
});

const generationTool = (overrides: Record<string, unknown> = {}) => ({
  ...message(),
  content: [
    {
      type: "tool-call",
      toolName: "nl2a_read_generation_context",
      args: { agent_id: 42, goal: "complete" },
      ...overrides,
    },
  ],
});

it("does not advance a unified coverage gap from a generation tool start", () => {
  expect(
    project(
      [message([], unifiedCard(["covered", "uncovered"])), generationTool()],
      true
    ).current
  ).toBe(1);
  expect(
    project([message([], unifiedCard(["covered"])), generationTool()], true)
      .current
  ).toBe(3);
});

it.each([undefined, { status: "success" }])(
  "shows generation while reading context and composing the prompt (result: %j)",
  (result) => {
    const messages = [
      message([], { subtype: "installed_resource_binding" }),
      generationTool({ result }),
    ];
    const view = project(messages, true);
    expect(view).toMatchObject({
      current: 3,
      status: "running",
      detail: "generating",
      skipped: [],
    });
    render(<Nl2AgentWorkflowProgress value={view} />);
    expect(screen.getByTestId("nl2agent-workflow-progress")).toHaveAttribute(
      "data-step",
      "generation"
    );
  }
);

it("recognizes prompt saving before the first saved-field receipt", () => {
  expect(
    project(
      [
        message([], { subtype: "installed_resource_binding" }),
        generationTool({
          toolName: "nl2a_save_agent_draft_fields",
          argsText: JSON.stringify({
            agent_id: 42,
            fields: { prompt: "Draft" },
          }),
        }),
      ],
      true
    )
  ).toMatchObject({ current: 3, status: "running", detail: "generating" });
});

it("does not advance binding from unrelated, invalid, failed or inactive tools", () => {
  const binding = message([], { subtype: "installed_resource_binding" });
  for (const overrides of [
    { args: { agent_id: 99, goal: "complete" } },
    { argsText: '{"goal":' },
    {
      toolName: "nl2a_save_agent_draft_fields",
      args: { fields: { name: "Name" } },
    },
    { isError: true },
  ]) {
    expect(project([binding, generationTool(overrides)], true).current).toBe(2);
  }
  expect(
    project([binding, generationTool({ isError: true })], true).status
  ).toBe("error");
  expect(project([binding, generationTool()]).current).toBe(2);
  expect(project([generationTool(), binding], true).current).toBe(2);
});

it.each([
  [message([state("preparing_embeddings")]), "coverage", "paused"],
  [
    message([], { subtype: "requirement_clarification" }),
    "requirements",
    "waiting",
  ],
  [message([], unifiedCard(["uncovered"])), "coverage", "waiting"],
  [
    message([], { subtype: "installed_resource_binding" }),
    "binding",
    "waiting",
  ],
])(
  "restores the header from saved workflow facts without an in-memory creation session: %j",
  (saved, step, status) => {
    thread.messages = [saved];
    const { rerender } = render(
      <Nl2AgentWorkflowHeader agentId={42} restoring />
    );
    expect(screen.queryByTestId("nl2agent-workflow-progress")).toBeNull();
    rerender(<Nl2AgentWorkflowHeader agentId={42} restoring={false} />);
    expect(screen.getByTestId("nl2agent-workflow-progress")).toHaveAttribute(
      "data-step",
      step as string
    );
    expect(screen.getByTestId("nl2agent-workflow-progress")).toHaveAttribute(
      "data-state",
      status as string
    );
    expect(screen.queryByTestId("nl2agent-workflow-spinner")).toBeNull();
    rerender(<Nl2AgentWorkflowHeader agentId={99} restoring={false} />);
    expect(screen.queryByTestId("nl2agent-workflow-progress")).toBeNull();
    thread.messages = [];
    rerender(<Nl2AgentWorkflowHeader agentId={42} restoring={false} />);
    expect(screen.queryByTestId("nl2agent-workflow-progress")).toBeNull();
  }
);

it("does not infer creation from local prompt saves, prose or invalid retrieval history", () => {
  expect(
    isFullGenerationTurn(
      [
        message([
          {
            event: "agent_draft_fields_saved",
            agent_id: 42,
            updated_fields: ["prompt"],
          },
        ]),
      ],
      42
    )
  ).toBe(false);
  expect(
    isFullGenerationTurn(
      [message([{ ...state("searching_text"), sequence: -1 }])],
      42
    )
  ).toBe(false);
  expect(
    isFullGenerationTurn(
      [
        {
          role: "assistant",
          content: [{ type: "text", text: "Create an agent" }],
        },
      ],
      42
    )
  ).toBe(false);
  expect(
    isFullGenerationTurn(
      [
        message([state("searching_text")]),
        message([{ event: "agent_generation_completed", agent_id: 42 }]),
        { role: "user", content: [] },
      ],
      42
    )
  ).toBe(false);
});

it("waits for prompt approval without reporting completion and preserves cancellation", () => {
  expect(
    project([message([], { subtype: "prompt_generation", status: "pending" })])
  ).toMatchObject({ current: 3, status: "waiting", detail: "confirmPrompt" });
  expect(
    project([
      message([], { subtype: "prompt_generation", status: "cancelled" }),
    ])
  ).toMatchObject({ current: 3, status: "paused", detail: "promptCancelled" });
  expect(
    isFullGenerationTurn(
      [
        {
          role: "assistant",
          content: [
            {
              type: "tool-call",
              toolName: "nl2a_read_generation_context",
              args: { goal: "complete" },
            },
          ],
        },
      ],
      42
    )
  ).toBe(true);
});

it("only explicit full creation intent enables steps for an existing draft", () => {
  const tool = (purpose: string) => ({
    role: "assistant",
    content: [
      {
        type: "tool-call",
        toolName: "nl2a_discover_requirements",
        args: { purpose },
      },
    ],
  });
  expect(isFullGenerationTurn([], 42)).toBe(false);
  expect(isFullGenerationTurn([tool("recommend")], 42)).toBe(false);
  expect(isFullGenerationTurn([tool("bind")], 42)).toBe(false);
  for (const purpose of ["recommend", "bind"]) {
    expect(
      isFullGenerationTurn(
        [
          tool(purpose),
          message([state("searching_text")], unifiedCard(["uncovered"])),
        ],
        42
      )
    ).toBe(false);
  }
  expect(
    isFullGenerationTurn([tool("generate"), { role: "user", content: [] }], 42)
  ).toBe(true);
  expect(
    isFullGenerationTurn(
      [
        tool("generate"),
        message([{ event: "agent_generation_completed", agent_id: 42 }]),
        { role: "user", content: [{ type: "text", text: "只修改提示词" }] },
      ],
      42
    )
  ).toBe(false);
});

it("shows normal fuzzy matching without inventing semantic failure", () => {
  const view = project([
    message(
      [state("searching_text"), state("verifying_capabilities", 2)],
      unifiedCard(["uncovered"])
    ),
  ]);
  expect(view.current).toBe(1);
  expect(view.mode).toBe("fuzzy");
  expect(view.status).toBe("waiting");
  expect(view.fallback).toBe(false);
  render(<Nl2AgentWorkflowProgress value={view} />);
  expect(screen.getByTestId("nl2agent-workflow-progress")).toHaveAttribute(
    "data-step",
    "coverage"
  );
  expect(screen.queryByTestId("nl2agent-workflow-spinner")).toBeNull();
  expect(screen.getByRole("status")).not.toHaveTextContent("fallback");
});

it("keeps hybrid stages and real fallback, ignores stale sequences", () => {
  const view = project(
    [
      message([
        state("searching_hybrid"),
        state("preparing_embeddings", 2),
        state("computing_similarity", 3),
        state("verifying_capabilities", 4),
        state("searching_text", 2),
      ]),
    ],
    true
  );
  expect(view.mode).toBe("hybrid");
  expect(view.pipeline).toEqual(["done", "done", "running"]);
  const failed = project(
    [
      message([
        state("searching_hybrid"),
        state("fallback_to_text", 2),
        state("verifying_capabilities", 3),
      ]),
    ],
    true
  );
  expect(failed.fallback).toBe(true);
  expect(failed.mode).toBe("fuzzy");
});

it("restores binding and return to requirements without treating user intent as success", () => {
  expect(
    project([message([], { subtype: "installed_resource_binding" })]).current
  ).toBe(2);
  expect(
    project([
      message([], { subtype: "installed_resource_binding" }),
      message([], { subtype: "requirement_clarification" }),
    ]).current
  ).toBe(0);
  const textOnly = {
    role: "assistant",
    content: [{ type: "text", text: "All steps completed" }],
  };
  expect(project([textOnly]).current).toBe(0);
  expect(
    project([message([{ event: "agent_generation_completed", agent_id: 99 }])])
      .status
  ).not.toBe("completed");
});

it("saved fields do not finish generation; trusted completion does", () => {
  const saved = message([
    {
      event: "agent_draft_fields_saved",
      agent_id: 42,
      updated_fields: ["prompt"],
    },
  ]);
  const view = project([saved]);
  expect(view.current).toBe(3);
  expect(view.status).not.toBe("completed");
  expect(view.skipped).toEqual([1, 2]);
  const failed = message([
    {
      event: "prompt_generation_failed",
      agent_id: 42,
      failed_fields: ["prompt"],
    },
  ]);
  expect(project([saved, failed]).status).toBe("error");
  expect(
    project([
      saved,
      message([{ event: "agent_generation_completed", agent_id: 42 }]),
    ]).status
  ).toBe("completed");
});

it("does not carry retrieval mode into a fresh run or a fresh conversation", () => {
  const view = project(
    [message([state("searching_hybrid"), state("searching_text", 1, "next")])],
    true
  );
  expect(view.mode).toBe("fuzzy");
  expect(view.fallback).toBe(false);
  expect(project([]).current).toBe(0);
  expect(project([]).mode).toBeUndefined();
  const stopped = project([message([state("preparing_embeddings")])]);
  expect(stopped.status).toBe("paused");
});

it("retains a bounded trusted history with latest counts and no stale writes", () => {
  const first = state("preparing_embeddings", 3) as Parameters<
    typeof recordNl2AgentState
  >[1] & { event: "resource_retrieval_progress" };
  const events = recordNl2AgentState([], first);
  expect(recordNl2AgentState(events, { ...first, sequence: 2 })).toEqual(
    events
  );
  const latest = recordNl2AgentState(events, {
    ...first,
    sequence: 4,
    completed: 2,
    total: 4,
  });
  expect(latest).toHaveLength(1);
  expect(latest[0]).toMatchObject({ completed: 2, total: 4 });
});
