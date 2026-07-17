import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchWithAuth } from "@/lib/auth";
import {
  abandonNl2AgentSession,
  listActiveNl2AgentSessions,
  resolveNl2AgentSessionByConversation,
} from "@/services/nl2agentService";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

const session = {
  draft_agent_id: 202,
  conversation_id: 902,
  status: "active" as const,
};

describe("NL2AGENT durable session discovery", () => {
  beforeEach(() => {
    vi.mocked(fetchWithAuth).mockReset();
  });

  it("resolves an active draft by conversation", async () => {
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response(JSON.stringify(session), { status: 200 })
    );

    await expect(resolveNl2AgentSessionByConversation(902)).resolves.toEqual(
      session
    );
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/nl2agent/session/by-conversation/902")
    );
  });

  it("returns null for a normal or inaccessible conversation", async () => {
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response("", { status: 404 })
    );

    await expect(resolveNl2AgentSessionByConversation(902)).resolves.toBeNull();
  });

  it("lists active sessions from the typed response envelope", async () => {
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response(JSON.stringify({ sessions: [session] }), { status: 200 })
    );

    await expect(listActiveNl2AgentSessions()).resolves.toEqual([session]);
  });

  it("abandons a session explicitly", async () => {
    const abandoned = { ...session, status: "abandoned" as const };
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response(JSON.stringify(abandoned), { status: 200 })
    );

    await expect(abandonNl2AgentSession(202)).resolves.toEqual(abandoned);
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/nl2agent/session/202/abandon"),
      { method: "POST" }
    );
  });
});
