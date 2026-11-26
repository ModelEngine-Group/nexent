// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, it, vi } from "vitest";
import { ConversationEvolutionSwitch } from "@/components/chat/ConversationEvolutionSwitch";
import { conversationService } from "@/services/conversationService";
import { useWithdrawConversationAnalysis } from "@/hooks/chat/useWithdrawConversationAnalysis";

vi.mock("@/services/conversationService", () => ({
  conversationService: { evolutionSetting: vi.fn() },
}));
vi.mock("@/components/providers/AuthorizationProvider", async () => {
  const { createContext } = await import("react");
  const auth = { user: { id: "owner", tenantId: "t" } };
  return { AuthorizationContext: createContext(auth), useAuthorizationContext: () => auth };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const modal = vi.hoisted(() => ({ confirm: vi.fn() }));
vi.mock("@/hooks/useConfirmModal", () => ({ useConfirmModal: () => modal }));

beforeEach(() => {
  vi.mocked(conversationService.evolutionSetting).mockReset();
  modal.confirm.mockClear();
});

it("reads the saved setting and applies changes to the selected conversation", async () => {
  let saved = false;
  vi.mocked(conversationService.evolutionSetting).mockImplementation(async (_, enabled) => {
    saved = typeof enabled === "boolean" ? enabled : saved;
    return saved;
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ConversationEvolutionSwitch id={42} />
    </QueryClientProvider>
  );
  const toggle = screen.getByRole("switch");
  await waitFor(() => expect(toggle).toBeEnabled());
  expect(toggle).toHaveAttribute("aria-checked", "false");
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  expect(conversationService.evolutionSetting).toHaveBeenCalledWith(42, true);
  expect(screen.queryByText("chat.evolution.withdraw")).not.toBeInTheDocument();
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
  expect(conversationService.evolutionSetting).toHaveBeenCalledWith(42, false);
  expect(conversationService.evolutionSetting).not.toHaveBeenCalledWith(42, "revoke");
});

function HistoryAction() {
  const withdraw = useWithdrawConversationAnalysis();
  return <button onClick={() => withdraw?.(42)}>History menu action</button>;
}

it("withdraws only after confirmation and refreshes the selected chat's switch", async () => {
  const saved = new Map([[42, true], [43, true]]);
  vi.mocked(conversationService.evolutionSetting).mockImplementation(async (id, action) => {
    if (action === "revoke") saved.set(id, false);
    return saved.get(id) ?? false;
  });
  render(<QueryClientProvider client={new QueryClient()}><App>
    <ConversationEvolutionSwitch id={42} />
    <ConversationEvolutionSwitch id={43} />
    <HistoryAction />
  </App></QueryClientProvider>);
  const [active, other] = screen.getAllByRole("switch");
  await waitFor(() => expect(active).toHaveAttribute("aria-checked", "true"));
  await waitFor(() => expect(other).toHaveAttribute("aria-checked", "true"));
  fireEvent.click(screen.getByRole("button", { name: "History menu action" }));
  expect(conversationService.evolutionSetting).not.toHaveBeenCalledWith(42, "revoke");
  expect(modal.confirm).toHaveBeenCalledWith(expect.objectContaining({ title: "chat.evolution.withdraw" }));
  await act(async () => modal.confirm.mock.calls[0][0].onOk());
  expect(conversationService.evolutionSetting).toHaveBeenCalledWith(42, "revoke");
  await waitFor(() => expect(active).toHaveAttribute("aria-checked", "false"));
  expect(other).toHaveAttribute("aria-checked", "true");
});
