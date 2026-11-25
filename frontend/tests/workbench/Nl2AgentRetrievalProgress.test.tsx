// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { parseNl2AgentState } from "@/app/newchat/adapter/remote-chat-model-adapter";
import {
  Nl2AgentRetrievalProgress,
  type RetrievalProgress,
} from "@/app/newchat/assistant-ui/nl2agent-retrieval-progress";

const event: RetrievalProgress = {
  event: "resource_retrieval_progress",
  agent_id: 1,
  run_id: "run",
  sequence: 1,
  stage: "preparing_embeddings",
};

it("accepts trusted progress shape and rejects malformed counts or private payload", () => {
  expect(parseNl2AgentState(JSON.stringify(event))).toEqual(event);
  for (const patch of [
    { sequence: 0 },
    { completed: 2, total: 1 },
    { total: 4 },
    { run_id: "" },
    { stage: "unknown" },
    { config: "secret" },
  ]) {
    expect(
      parseNl2AgentState(JSON.stringify({ ...event, ...patch }))
    ).toBeNull();
  }
});

it("shows real stage percentage and no fabricated percentage without total", () => {
  const { rerender } = render(<Nl2AgentRetrievalProgress value={event} />);
  expect(screen.getByRole("status")).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
  rerender(
    <Nl2AgentRetrievalProgress value={{ ...event, completed: 1, total: 4 }} />
  );
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
    "25"
  );
  rerender(
    <Nl2AgentRetrievalProgress
      value={{ ...event, stage: "fallback_to_text" }}
    />
  );
  expect(screen.queryByRole("progressbar")).toBeNull();
  expect(screen.getByRole("status").textContent).toContain(
    "nl2agent.retrieval.fallback_to_text"
  );
  rerender(<Nl2AgentRetrievalProgress value={{ ...event, stage: "searching_text" }} fallback />);
  expect(screen.getByRole("status").textContent).toContain("nl2agent.retrieval.fallback_to_text");
});
