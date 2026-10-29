// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import en from "../../public/locales/en/common.json";
import zh from "../../public/locales/zh/common.json";
import AgentRunPolicy from "../../app/[locale]/agents/[agentId]/components/agent-run-policy";

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  readOnly: false,
  translations: {} as Record<string, string>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => mocks.translations[key] ?? key,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({ editedAgent: {}, updateAgentConfig: mocks.update }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => mocks.readOnly,
}));
vi.mock("@/hooks/group/useGroupList", () => ({ useGroupList: vi.fn() }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: vi.fn(),
}));

const options = [
  ["agent.highFidelity.chatMetadata", "agent.allowChatMetadata.tooltip"],
  ["agent.highFidelity.selfValidate", "agent.runPolicy.selfValidateHint"],
  [
    "agent.runPolicy.protocolRepairRetry",
    "agent.runPolicy.protocolRepairRetryHint",
  ],
  ["agent.highFidelity.mainAgent", "agent.deployment.isMainAgentTooltip"],
  ["agent.highFidelity.a2a", "agent.deployment.a2aEnabledTooltip"],
];

describe("Advanced configuration help buttons", () => {
  beforeEach(() => {
    mocks.update.mockReset();
    mocks.readOnly = false;
    mocks.translations = Object.fromEntries(
      Object.entries(en).map(([key, value]) => [key, String(value)])
    );
  });

  it.each([
    ["English", en],
    ["Chinese", zh],
  ])(
    "shows each setting's own hint in %s without changing configuration",
    async (_, translations) => {
      mocks.translations = Object.fromEntries(
        Object.entries(translations).map(([key, value]) => [key, String(value)])
      );
      render(<AgentRunPolicy highFidelity />);
      expect(screen.getAllByRole("button")).toHaveLength(options.length);
      for (const key of [
        "agentConfig.layout.maxRunSteps",
        "agent.highFidelity.runSummary",
      ]) {
        expect(
          screen.queryByRole("button", { name: mocks.translations[key] })
        ).not.toBeInTheDocument();
      }
      for (const [label, hint] of options) {
        const button = screen.getByRole("button", {
          name: mocks.translations[label],
        });
        fireEvent.mouseEnter(button);
        await waitFor(() =>
          expect(screen.getByText(mocks.translations[hint])).toBeVisible()
        );
        fireEvent.click(button);
        fireEvent.mouseLeave(button);
      }
      expect(mocks.update).not.toHaveBeenCalled();
    }
  );

  it("keeps help available in read-only mode and preserves checkbox updates", async () => {
    const view = render(<AgentRunPolicy highFidelity />);
    const label = en["agent.runPolicy.protocolRepairRetry"];
    fireEvent.click(screen.getByRole("checkbox", { name: label }));
    expect(mocks.update).toHaveBeenCalledWith({
      enable_protocol_repair_retry: true,
    });
    mocks.update.mockClear();
    mocks.readOnly = true;
    view.rerender(<AgentRunPolicy highFidelity />);
    expect(screen.getByRole("checkbox", { name: label })).toBeDisabled();
    const help = screen.getByRole("button", { name: label });
    expect(help).toBeEnabled();
    fireEvent.mouseEnter(help);
    await waitFor(() =>
      expect(
        screen.getByText(en["agent.runPolicy.protocolRepairRetryHint"])
      ).toBeVisible()
    );
    fireEvent.click(help);
    expect(mocks.update).not.toHaveBeenCalled();
  });
});

it.each([false, true])(
  "never offers Agent token length overrides (high fidelity: %s)",
  (highFidelity) => {
    render(<AgentRunPolicy highFidelity={highFidelity} />);
    expect(
      screen.queryByText(mocks.translations["agentConfig.layout.outputReserve"])
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(mocks.translations["agent.requestedOutputTokens"])
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
  }
);
