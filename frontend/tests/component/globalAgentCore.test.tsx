// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ContextManagerSetting from "@/app/agents/[agentId]/components/context-manager-setting";

const state = vi.hoisted(() => ({
  core: "jiuwen",
  readOnly: false,
  update: vi.fn(),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ agentCore: state.core }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => state.readOnly,
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (value: unknown) => unknown) =>
    selector({
      editedAgent: { agent_core: "smolagents", enable_context_manager: true },
      updateAgentConfig: state.update,
    }),
}));
beforeEach(() => {
  state.core = "jiuwen";
  state.readOnly = false;
  state.update.mockClear();
});
it.each(["jiuwen", "smolagents"])(
  "offers no per-Agent Core control under %s",
  (core) => {
    state.core = core;
    render(<ContextManagerSetting />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText("agent.core.label")).not.toBeInTheDocument();
    expect(screen.queryByText("agent.core.globalHint")).not.toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeEnabled();
    expect(state.update).not.toHaveBeenCalled();
  }
);
it("keeps CM editable independently of global Core", () => {
  render(<ContextManagerSetting />);
  fireEvent.click(screen.getByRole("switch"));
  expect(state.update).toHaveBeenCalledExactlyOnceWith({
    enable_context_manager: false,
  });
});
it("locks CM for read-only users", () => {
  state.readOnly = true;
  render(<ContextManagerSetting />);
  expect(screen.getByRole("switch")).toBeDisabled();
  fireEvent.click(screen.getByRole("switch"));
  expect(state.update).not.toHaveBeenCalled();
});
