import { beforeEach, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { useConversationRouteGuard } from "@/features/workbench/hooks/useConversationRouteGuard";
import { conversationService } from "@/services/conversationService";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  useParams: () => ({ locale: "zh" }),
}));
vi.mock("@/lib/basePath", () => ({ withBasePath: (path: string) => path }));
vi.mock("@/services/conversationService", () => ({
  conversationService: { getById: vi.fn() },
}));

function Guard({ expected }: { expected: "agent_chat" | "workbench" }) {
  useConversationRouteGuard(expected);
  return null;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/zh/newchat?conversation_id=42");
});

it("routes historical Workbench chats out of Start Chat", async () => {
  vi.mocked(conversationService.getById).mockResolvedValue({
    workbench_config: { mode: "single_agent_chat" },
  } as Awaited<ReturnType<typeof conversationService.getById>>);
  render(<Guard expected="agent_chat" />);
  await waitFor(() =>
    expect(navigation.replace).toHaveBeenCalledWith(
      "/zh/workbench?conversation_id=42"
    )
  );
});

it("routes ordinary Agent chats out of Workbench", async () => {
  vi.mocked(conversationService.getById).mockResolvedValue({
    workbench_config: null,
  } as Awaited<ReturnType<typeof conversationService.getById>>);
  render(<Guard expected="workbench" />);
  await waitFor(() =>
    expect(navigation.replace).toHaveBeenCalledWith(
      "/zh/newchat?conversation_id=42"
    )
  );
});
