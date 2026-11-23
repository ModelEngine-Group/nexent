// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ConversationEvolutionSwitch } from "@/app/newchat/assistant-ui/conversation-evolution-switch";
import { conversationService } from "@/services/conversationService";

vi.mock("@/services/conversationService", () => ({
  conversationService: { evolutionSetting: vi.fn() },
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { id: "owner", tenantId: "t" } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it("reads the saved setting and applies changes to the selected conversation", async () => {
  let saved = false;
  vi.mocked(conversationService.evolutionSetting).mockImplementation(async (_, enabled) => {
    saved = enabled ?? saved;
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
});
