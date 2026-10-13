import { Form, Input } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentConfigHeader } from "../../app/[locale]/agents/[agentId]/components/agent-config-header";
import type { AgentDraft } from "../../stores/agentStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      lastSavedAt: null,
      queue: [],
      editedAgent: null,
      savedAgent: null,
    }),
}));
vi.mock("../../services/api", () => ({
  API_ENDPOINTS: { agent: { icon: () => "/unused-icon" } },
}));

const agent: AgentDraft = {
  name: "fixture_agent",
  display_name: "Fixture Agent",
  description: "Fixture description",
  model: "Fixture Model",
  tools: [],
  skills: [],
  max_step: 10,
  provide_run_summary: false,
};
function setup(readOnly: boolean, agentId: number | null = 42) {
  const callbacks = {
    onConfigure: vi.fn(),
    onDebug: vi.fn(),
    onPublish: vi.fn(),
    onEditIdentity: vi.fn(),
    onManualUnlock: vi.fn(),
  };
  render(
    <Form component="div" disabled={readOnly}>
      <Input aria-label="Protected field" />
      <AgentConfigHeader
        agent={agent}
        agentId={agentId}
        readOnly={readOnly}
        debugVisible
        canManualUnlock={false}
        {...callbacks}
      />
    </Form>
  );
  return callbacks;
}

describe("AgentConfigHeader workflow navigation", () => {
  it("returns to configure inside a disabled Form while retaining read-only protections", () => {
    const callbacks = setup(true);
    const configure = screen.getByRole("button", {
      name: "agent.highFidelity.configureMode",
    });
    expect(configure).toBeEnabled();
    fireEvent.click(configure);
    expect(callbacks.onConfigure).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("textbox", { name: "Protected field" })
    ).toBeDisabled();
    const publish = screen.getByRole("button", {
      name: "agent.highFidelity.publishMode",
    });
    expect(publish).toBeDisabled();
    fireEvent.click(publish);
    expect(callbacks.onPublish).not.toHaveBeenCalled();
    expect(callbacks.onEditIdentity).not.toHaveBeenCalled();
  });
  it("preserves editable configure, debug and publish callbacks", () => {
    const callbacks = setup(false);
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.configureMode" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.debugMode" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.publishMode" })
    );
    expect(callbacks.onConfigure).toHaveBeenCalledTimes(1);
    expect(callbacks.onDebug).toHaveBeenCalledTimes(1);
    expect(callbacks.onPublish).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("textbox", { name: "Protected field" })
    ).toBeEnabled();
  });
  it("keeps debug and publication disabled when no Agent is selected", () => {
    const callbacks = setup(false, null);
    for (const name of [
      "agent.highFidelity.debugMode",
      "agent.highFidelity.publishMode",
    ]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      fireEvent.click(button);
    }
    expect(callbacks.onDebug).not.toHaveBeenCalled();
    expect(callbacks.onPublish).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "agent.highFidelity.configureMode" })
    ).toBeEnabled();
  });
});
