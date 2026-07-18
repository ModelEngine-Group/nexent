import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useNl2AgentSessionRecovery } from "@/hooks/useNl2AgentSessionRecovery";
import { resolveNl2AgentSessionByConversation } from "@/services/nl2agentService";

vi.mock("@/services/nl2agentService", () => ({
  resolveNl2AgentSessionByConversation: vi.fn(),
}));

const session = {
  nl2agent_agent_id: 101,
  draft_agent_id: 202,
  conversation_id: 902,
  status: "active" as const,
};

describe("NL2AGENT session recovery", () => {
  beforeEach(() => {
    vi.mocked(resolveNl2AgentSessionByConversation).mockReset();
  });

  it("recovers the complete active session after a fresh mount", async () => {
    vi.mocked(resolveNl2AgentSessionByConversation).mockResolvedValue(session);
    const onActivate = vi.fn();

    const { result } = renderHook(() =>
      useNl2AgentSessionRecovery({
        conversationId: 902,
        onActivate,
        onDeactivate: vi.fn(),
        onError: vi.fn(),
      })
    );

    await waitFor(() => expect(result.current.activeSession).toEqual(session));
    expect(onActivate).toHaveBeenCalledWith(session);
    expect(resolveNl2AgentSessionByConversation).toHaveBeenCalledOnce();
  });

  it("reuses the verified session when switching away and back", async () => {
    vi.mocked(resolveNl2AgentSessionByConversation).mockImplementation(
      async (conversationId) => (conversationId === 902 ? session : null)
    );
    const onActivate = vi.fn();
    const { result, rerender } = renderHook(
      ({ conversationId }: { conversationId: number | null }) =>
        useNl2AgentSessionRecovery({
          conversationId,
          onActivate,
          onDeactivate: vi.fn(),
          onError: vi.fn(),
        }),
      { initialProps: { conversationId: 902 } }
    );
    await waitFor(() => expect(result.current.activeSession).toEqual(session));

    rerender({ conversationId: 903 });
    await waitFor(() => expect(result.current.activeSession).toBeUndefined());
    rerender({ conversationId: 902 });
    await waitFor(() => expect(result.current.activeSession).toEqual(session));

    expect(resolveNl2AgentSessionByConversation).toHaveBeenCalledTimes(2);
    expect(onActivate).toHaveBeenLastCalledWith(session);
  });

  it("does not repeat discovery for a verified normal conversation", async () => {
    vi.mocked(resolveNl2AgentSessionByConversation).mockResolvedValue(null);
    const onDeactivate = vi.fn();
    const { result } = renderHook(() =>
      useNl2AgentSessionRecovery({
        conversationId: 903,
        onActivate: vi.fn(),
        onDeactivate,
        onError: vi.fn(),
      })
    );
    await waitFor(() => expect(onDeactivate).toHaveBeenCalledWith(903));

    await act(async () => {
      await expect(result.current.resolveSession(903)).resolves.toBeNull();
    });

    expect(resolveNl2AgentSessionByConversation).toHaveBeenCalledOnce();
  });
});
