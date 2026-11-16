// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { RequirementClarificationCard } from "@/app/newchat/ui/requirement-clarification-card";
import { SuggestedResourceInstallationCard } from "@/app/newchat/ui/suggested-resource-installation-card";
import { InstalledResourceBindingCard } from "@/app/newchat/ui/installed-resource-binding-card";

vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ thread: () => ({ append: vi.fn() }) }),
  useAuiState: () => false,
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    availableTools: [],
    isFetching: false,
    isError: false,
  }),
}));

function Editor({
  kind,
  disabled,
  running = false,
}: {
  kind: string;
  disabled: boolean;
  running?: boolean;
}) {
  const [show, setShow] = useState(false);
  const { resetFlow, markRunStarted, markRunFinished, isFormLocked } =
    useNl2AgentFlow();
  return (
    <>
      <button
        onClick={() => {
          resetFlow(42);
          if (running) markRunStarted(42);
          setShow(true);
        }}
      >
        Load conversation
      </button>
      <input aria-label="Agent configuration" disabled={isFormLocked} />
      <button onClick={() => markRunStarted(42)}>Ask another question</button>
      <button onClick={() => markRunFinished(42)}>Finish question</button>
      {show &&
        (kind === "clarification" ? (
          <RequirementClarificationCard
            disabled={disabled}
            payload={{
              subtype: "requirement_clarification",
              agent_id: 42,
              questions: [],
            }}
          />
        ) : kind === "installation" ? (
          <SuggestedResourceInstallationCard
            disabled={disabled}
            payload={{
              subtype: "suggested_resource_installation",
              agent_id: 42,
              resources: [],
            }}
          />
        ) : (
          <InstalledResourceBindingCard
            disabled={disabled}
            payload={{
              subtype: "installed_resource_binding",
              agent_id: 42,
              resources: [],
            }}
          />
        ))}
    </>
  );
}

it.each(["clarification", "installation", "binding"])(
  "disabled historical %s cards do not lock Agent configuration",
  (kind) => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App>
          <Nl2AgentFlowProvider>
            <Editor kind={kind} disabled />
          </Nl2AgentFlowProvider>
        </App>
      </QueryClientProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: "Load conversation" }));
    expect(
      screen.getByRole("textbox", { name: "Agent configuration" })
    ).toBeEnabled();
  }
);

it.each(["clarification", "installation", "binding"])(
  "active %s cards retain their generation edit lock",
  (kind) => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App>
          <Nl2AgentFlowProvider>
            <Editor kind={kind} disabled={false} running />
          </Nl2AgentFlowProvider>
        </App>
      </QueryClientProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: "Load conversation" }));
    expect(
      screen.getByRole("textbox", { name: "Agent configuration" })
    ).toBeDisabled();
  }
);

it.each(["clarification", "installation", "binding"])(
  "restoring the latest %s card leaves editing enabled until another question starts",
  (kind) => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App>
          <Nl2AgentFlowProvider>
            <Editor kind={kind} disabled={false} />
          </Nl2AgentFlowProvider>
        </App>
      </QueryClientProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: "Load conversation" }));
    expect(
      screen.getByRole("textbox", { name: "Agent configuration" })
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Ask another question" })
    );
    expect(
      screen.getByRole("textbox", { name: "Agent configuration" })
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Finish question" }));
    expect(
      screen.getByRole("textbox", { name: "Agent configuration" })
    ).toBeEnabled();
  }
);
