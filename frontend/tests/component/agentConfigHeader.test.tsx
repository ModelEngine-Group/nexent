// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
function setup(
  readOnly: boolean,
  agentId: number | null = 42,
  displayedAgent: AgentDraft = agent,
  publicationVisible = false
) {
  const callbacks = {
    onConfigure: vi.fn(),
    onDebug: vi.fn(),
    onPublish: vi.fn(),
    onPublication: vi.fn(),
    onManualUnlock: vi.fn(),
  };
  const { container } = render(
    <Form component="div" disabled={readOnly}>
      <Input aria-label="Protected field" />
      <AgentConfigHeader
        agent={displayedAgent}
        agentId={agentId}
        readOnly={readOnly}
        debugVisible={!publicationVisible}
        publicationVisible={publicationVisible}
        canManualUnlock={false}
        {...callbacks}
      />
    </Form>
  );
  return { ...callbacks, container };
}

describe("AgentConfigHeader workflow navigation", () => {
  it("opens the publication tab without publishing in read-only mode", () => {
    const callbacks = setup(true);
    const publication = screen.getByRole("button", {
      name: "agent.highFidelity.publishMode",
    });
    expect(publication).toBeEnabled();
    fireEvent.click(publication);
    expect(callbacks.onPublication).toHaveBeenCalledTimes(1);
    expect(callbacks.onPublish).not.toHaveBeenCalled();
  });
  it("selects only the publication tab when its empty page is shown", () => {
    setup(false, 42, agent, true);
    for (const [name, pressed] of [
      ["agent.highFidelity.publishMode", "true"],
      ["agent.highFidelity.configureMode", "false"],
      ["agent.highFidelity.debugMode", "false"],
    ]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute(
        "aria-pressed",
        pressed
      );
    }
  });
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
      name: "agent.config.button.publish",
    });
    expect(publish).toBeDisabled();
    fireEvent.click(publish);
    expect(callbacks.onPublish).not.toHaveBeenCalled();
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
      screen.getByRole("button", { name: "agent.config.button.publish" })
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
      "agent.config.button.publish",
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

describe("AgentConfigHeader legacy avatar fallback", () => {
  it.each([
    [41, "bot"],
    [42, "wand"],
    [43, "lightbulb"],
    [44, "zap"],
    [45, "sparkles"],
  ])("renders the legacy icon for agent %s", (agentId, icon) => {
    const { container } = setup(false, agentId as number);
    expect(
      container.querySelector(`.ant-avatar svg.lucide-${icon}`)
    ).toBeInTheDocument();
    expect(container.querySelector(".ant-avatar img")).toBeNull();
  });
  it("prefers the saved image and falls back to the ID icon if loading fails", () => {
    const { container } = setup(false, 42, {
      ...agent,
      icon_url: "/api/agent/42/icon?v=saved",
    });
    const image = container.querySelector(".ant-avatar img")!;
    expect(image).toHaveAttribute("src", "/unused-icon");
    fireEvent.error(image);
    expect(
      container.querySelector(".ant-avatar svg.lucide-wand")
    ).toBeInTheDocument();
    expect(container.querySelector(".ant-avatar img")).toBeNull();
  });
});
