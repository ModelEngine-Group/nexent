import React from "react";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentVersionPubulishModal from "../../app/[locale]/agents/versions/AgentVersionPubulishModal";
import AgentSharePage from "../../app/[locale]/share/agent/[shareToken]/page";
import { publishVersion } from "@/services/agentVersionService";
import { agentShareRuntimeService } from "@/services/agentShareRuntimeService";

let authenticated = true;
vi.mock("next/navigation", () => ({
  useParams: () => ({ shareToken: "route-token" }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => ({
    isAuthenticated: authenticated,
    isAuthChecking: false,
  }),
}));
vi.mock("@/components/ui/textarea", () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea {...props} />
  ),
}));
vi.mock("@/hooks/agent/useAgentVersionList", () => ({
  useAgentVersionList: () => ({ agentVersionList: [] }),
}));
vi.mock("@/services/agentVersionService", () => ({
  publishVersion: vi.fn(),
  updateVersion: vi.fn(),
}));
vi.mock("@/services/agentShareRuntimeService", () => ({
  agentShareRuntimeService: {
    getMetadata: vi.fn(),
    getHistory: vi.fn(),
    run: vi.fn(),
    stop: vi.fn(),
  },
}));

function renderApp(node: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <App>{node}</App>
    </QueryClientProvider>
  );
}

async function submitPublish(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("agent.version.versionName"), "v1");
  await user.click(
    screen.getByRole("button", { name: "agent.version.publish" })
  );
}

const metadata = {
  display_name: "Fixed Agent",
  description: "Only this Agent",
  icon_url: null,
  greeting_message: "Welcome",
  session_recoverable: true,
};

beforeEach(() => {
  authenticated = true;
  vi.mocked(publishVersion).mockResolvedValue({
    success: true,
    data: {},
  } as never);
  vi.mocked(agentShareRuntimeService.getMetadata).mockResolvedValue(metadata);
  vi.mocked(agentShareRuntimeService.getHistory).mockResolvedValue({
    history: [],
    session_recoverable: true,
  });
  vi.mocked(agentShareRuntimeService.run).mockResolvedValue({
    read: vi.fn().mockResolvedValueOnce({ done: true, value: undefined }),
  } as never);
  vi.mocked(agentShareRuntimeService.stop).mockResolvedValue(undefined);
});

describe("publish navigation component contract", () => {
  it("UT-FE-AGUG-001 closes a successful normal publish and invokes navigation callback once", async () => {
    const user = userEvent.setup();
    const onPublished = vi.fn();
    const onClose = vi.fn();
    renderApp(
      <AgentVersionPubulishModal
        open
        onClose={onClose}
        agentId={41}
        onPublished={onPublished}
      />
    );
    await submitPublish(user);
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("UT-FE-AGUG-002 uses the same single completion callback for an A2A-capable Agent", async () => {
    const user = userEvent.setup();
    const onPublished = vi.fn();
    renderApp(
      <AgentVersionPubulishModal
        open
        onClose={vi.fn()}
        agentId={42}
        onPublished={onPublished}
      />
    );
    await submitPublish(user);
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(
      screen.queryByText("a2a.publishSuccessTitle")
    ).not.toBeInTheDocument();
  });

  it("UT-FE-AGUG-003 keeps the editor modal open and skips navigation on publish failure", async () => {
    const user = userEvent.setup();
    vi.mocked(publishVersion).mockResolvedValue({
      success: false,
      message: "failed",
    } as never);
    const onPublished = vi.fn();
    const onClose = vi.fn();
    renderApp(
      <AgentVersionPubulishModal
        open
        onClose={onClose}
        agentId={41}
        onPublished={onPublished}
      />
    );
    await submitPublish(user);
    await waitFor(() => expect(publishVersion).toHaveBeenCalledOnce());
    expect(onPublished).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("minimal authenticated Agent share page", () => {
  it("UT-FE-AGUG-014 performs no metadata, history, session, or run side effect before login", async () => {
    authenticated = false;
    renderApp(<AgentSharePage />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(agentShareRuntimeService.getMetadata).not.toHaveBeenCalled();
    expect(agentShareRuntimeService.getHistory).not.toHaveBeenCalled();
    expect(agentShareRuntimeService.run).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("Fixed Agent");
  });

  it("UT-FE-AGUG-015 renders only the fixed Agent chat and sends through the share runtime", async () => {
    const user = userEvent.setup();
    vi.mocked(agentShareRuntimeService.run).mockResolvedValue({
      read: vi.fn(() => new Promise(() => undefined)),
    } as never);
    renderApp(<AgentSharePage />);
    expect(
      await screen.findByRole("heading", { name: "Fixed Agent" })
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/repository|automation|conversation list/i)
    ).not.toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Ask a question" });
    await user.type(input, "Hello{Shift>}{Enter}{/Shift}world");
    expect(agentShareRuntimeService.run).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(agentShareRuntimeService.run).toHaveBeenCalledOnce()
    );
    expect(agentShareRuntimeService.run).toHaveBeenCalledWith(
      "route-token",
      expect.objectContaining({ query: "Hello\nworld" }),
      expect.any(AbortSignal)
    );
    await user.click(
      await screen.findByRole("button", { name: "Stop response" })
    );
    expect(agentShareRuntimeService.stop).toHaveBeenCalledWith("route-token");
  });

  it("UT-FE-AGUG-016 presents one indistinguishable unavailable state for all lookup failures", async () => {
    for (const reason of ["invalid token", "revoked", "agent missing"]) {
      vi.mocked(agentShareRuntimeService.getMetadata).mockRejectedValueOnce(
        new Error(reason)
      );
      renderApp(<AgentSharePage />);
      expect(
        await screen.findByText("This Agent share is unavailable.")
      ).toBeInTheDocument();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(document.body.textContent).not.toContain(reason);
      cleanup();
    }
  });
});
