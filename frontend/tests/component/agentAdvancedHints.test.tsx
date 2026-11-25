// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import en from "../../public/locales/en/common.json";
import zh from "../../public/locales/zh/common.json";
import AgentRunPolicy from "../../app/[locale]/agents/[agentId]/components/agent-run-policy";

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  readOnly: false,
  savedMemory: true,
  loadMemoryConfig: vi.fn().mockResolvedValue({ memoryEnabled: true }),
  tenantMemory: { enabled: true } as { enabled: boolean } | undefined,
  tenantMemoryError: false,
  translations: {} as Record<string, string>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => mocks.translations[key] ?? key,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      editedAgent: { enable_memory: mocks.savedMemory },
      updateAgentConfig: mocks.update,
    }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => mocks.readOnly,
}));
vi.mock("@/hooks/memory/useTenantMemorySettings", () => ({
  useTenantMemorySettings: () => ({
    data: mocks.tenantMemory,
    isError: mocks.tenantMemoryError,
  }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({ useGroupList: vi.fn() }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "tenant-a", id: "user-a" },
  }),
}));

vi.mock("@/services/memoryService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/memoryService")>()),
  loadMemoryConfig: mocks.loadMemoryConfig,
}));

function renderPolicy(highFidelity: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }
  return render(<AgentRunPolicy highFidelity={highFidelity} />, {
    wrapper: Wrapper,
  });
}

const options = [
  ["agent.highFidelity.chatMetadata", "agent.allowChatMetadata.tooltip"],
  ["agent.highFidelity.selfValidate", "agent.runPolicy.selfValidateHint"],
  [
    "agent.runPolicy.protocolRepairRetry",
    "agent.runPolicy.protocolRepairRetryHint",
  ],
  [
    "memory.manager.agentAutomaticMemory",
    "memory.manager.agentAutomaticMemoryHint",
  ],
  ["agent.highFidelity.mainAgent", "agent.deployment.isMainAgentTooltip"],
  ["agent.highFidelity.a2a", "agent.deployment.a2aEnabledTooltip"],
];

describe("Advanced configuration help buttons", () => {
  beforeEach(() => {
    mocks.update.mockReset();
    mocks.loadMemoryConfig
      .mockReset()
      .mockResolvedValue({ memoryEnabled: true });
    mocks.readOnly = false;
    mocks.savedMemory = true;
    mocks.tenantMemory = { enabled: true };
    mocks.tenantMemoryError = false;
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
      renderPolicy(true);
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

  it.each([
    [false, false],
    [false, true],
    [true, false],
    [true, true],
  ])(
    "keeps the saved memory value when the tenant closes it (high fidelity: %s, saved: %s)",
    (highFidelity, saved) => {
      mocks.savedMemory = saved;
      mocks.tenantMemory = { enabled: false };
      const label = en["memory.manager.agentAutomaticMemory"];
      const role = highFidelity ? "checkbox" : "switch";
      const view = renderPolicy(highFidelity);
      const control = screen.getByRole(role, { name: label });
      expect(control).toBeDisabled();
      expect(mocks.loadMemoryConfig).not.toHaveBeenCalled();
      expect(control).toHaveAccessibleDescription(
        en["memory.manager.tenantMemoryDisabledHint"]
      );
      expect(control.matches(":checked, [aria-checked=true]")).toBe(saved);
      fireEvent.click(control);
      expect(mocks.update).not.toHaveBeenCalled();

      mocks.tenantMemory = { enabled: true };
      view.rerender(<AgentRunPolicy highFidelity={highFidelity} />);
      const restored = screen.getByRole(role, { name: label });
      expect(restored).toBeEnabled();
      expect(restored.matches(":checked, [aria-checked=true]")).toBe(saved);
      fireEvent.click(restored);
      expect(mocks.update).toHaveBeenCalledWith({ enable_memory: !saved });
    }
  );

  it.each([
    [false, false],
    [true, true],
  ])(
    "shows the personal hint without changing the shared setting (high fidelity: %s, saved: %s)",
    async (highFidelity, saved) => {
      mocks.savedMemory = saved;
      mocks.loadMemoryConfig.mockResolvedValue({ memoryEnabled: false });
      renderPolicy(highFidelity);
      const control = screen.getByRole(highFidelity ? "checkbox" : "switch", {
        name: en["memory.manager.agentAutomaticMemory"],
      });
      const hint = en["memory.manager.personalMemoryDisabledHint"];
      expect(await screen.findByText(hint)).toBeVisible();
      expect(control).toHaveAccessibleDescription(hint);
      expect(control).toBeEnabled();
      expect(control.matches(":checked, [aria-checked=true]")).toBe(saved);
      expect(mocks.loadMemoryConfig).toHaveBeenCalledWith({
        throwOnError: true,
      });
      fireEvent.click(control);
      expect(mocks.update).toHaveBeenCalledWith({ enable_memory: !saved });

      mocks.loadMemoryConfig.mockResolvedValue({ memoryEnabled: true });
      act(() => {
        window.dispatchEvent(
          new CustomEvent("memorySwitchChanged", { detail: true })
        );
      });
      await waitFor(() =>
        expect(screen.queryByText(hint)).not.toBeInTheDocument()
      );
    }
  );

  it("keeps editing available when the personal preference cannot be read", async () => {
    mocks.loadMemoryConfig.mockRejectedValue(new Error("unavailable"));
    renderPolicy(true);
    await waitFor(() => expect(mocks.loadMemoryConfig).toHaveBeenCalled());
    const control = screen.getByRole("checkbox", {
      name: en["memory.manager.agentAutomaticMemory"],
    });
    expect(control).not.toHaveAccessibleDescription();
    expect(control).toBeEnabled();
  });

  it("keeps the memory setting disabled when the tenant status is unknown", () => {
    mocks.tenantMemory = undefined;
    const view = renderPolicy(true);
    const control = screen.getByRole("checkbox", {
      name: en["memory.manager.agentAutomaticMemory"],
    });
    expect(control).toBeDisabled();
    expect(control).not.toHaveAccessibleDescription();
    mocks.tenantMemoryError = true;
    view.rerender(<AgentRunPolicy highFidelity />);
    expect(control).toBeDisabled();
    expect(control).toHaveAccessibleDescription(
      en["memory.manager.tenantMemoryLoadError"]
    );
  });

  it("keeps help available in read-only mode and preserves checkbox updates", async () => {
    const view = renderPolicy(true);
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
    renderPolicy(highFidelity);
    expect(
      screen.queryByText(mocks.translations["agentConfig.layout.outputReserve"])
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(mocks.translations["agent.requestedOutputTokens"])
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
  }
);
