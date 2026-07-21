import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchWithAuth } from "@/lib/auth";
import {
  Nl2AgentRequestError,
  resolveNl2AgentSessionByConversation,
  resumeNl2AgentSession,
  startNl2AgentSession,
} from "@/services/nl2agentService";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

const session = {
  nl2agent_agent_id: 101,
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

  it("resolves a completed session for historical review", async () => {
    const completed = { ...session, status: "completed" as const };
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response(JSON.stringify(completed), { status: 200 })
    );

    await expect(resolveNl2AgentSessionByConversation(902)).resolves.toEqual(
      completed
    );
  });

  it("resumes a completed session explicitly", async () => {
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response(JSON.stringify(session), { status: 200 })
    );

    await expect(resumeNl2AgentSession(202)).resolves.toEqual(session);
    expect(fetchWithAuth).toHaveBeenCalledWith(
      expect.stringContaining("/nl2agent/session/202/resume"),
      { method: "POST" }
    );
  });

  it("returns null for a normal or inaccessible conversation", async () => {
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response("", { status: 404 })
    );

    await expect(resolveNl2AgentSessionByConversation(902)).resolves.toBeNull();
  });

  it("preserves structured status, code, and details on discovery failure", async () => {
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "100401",
          message: "Session state is unavailable.",
          details: { retryable: true },
        }),
        { status: 503 }
      )
    );

    const error = await resolveNl2AgentSessionByConversation(902).catch(
      (caught: unknown) => caught
    );

    expect(error).toBeInstanceOf(Nl2AgentRequestError);
    expect(error).toMatchObject({
      message: "Session state is unavailable.",
      status: 503,
      code: "100401",
      details: { retryable: true },
    });
  });

  it("coalesces concurrent session starts into one backend request", async () => {
    const started = {
      nl2agent_agent_id: 101,
      draft_agent_id: 202,
      conversation_id: 902,
      draft_name: "draft_abc",
    };
    vi.mocked(fetchWithAuth).mockResolvedValue(
      new Response(JSON.stringify(started), { status: 200 })
    );

    const [first, second] = await Promise.all([
      startNl2AgentSession(),
      startNl2AgentSession(),
    ]);

    expect(first).toEqual(started);
    expect(second).toEqual(started);
    expect(fetchWithAuth).toHaveBeenCalledTimes(1);
  });
});
