import React from "react";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/dom";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentVersionPubulishModal from "../../app/[locale]/agents/versions/AgentVersionPubulishModal";
import { publishVersion } from "@/services/agentVersionService";

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => ({
    isAuthenticated: true,
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

beforeEach(() => {
  vi.mocked(publishVersion).mockResolvedValue({
    success: true,
    data: {},
  } as never);
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

  it("UT-FE-AGUG-025 refreshes the editable Agent list after a successful publish", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    render(
      <QueryClientProvider client={queryClient}>
        <App>
          <AgentVersionPubulishModal
            open
            onClose={vi.fn()}
            agentId={41}
            onPublished={vi.fn()}
          />
        </App>
      </QueryClientProvider>
    );

    await submitPublish(user);

    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["myEditableAgents"],
      })
    );
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

describe("Agent publish version name default", () => {
  it("prefills an editable version name when the publish modal opens", () => {
    renderApp(
      <AgentVersionPubulishModal
        open
        onClose={vi.fn()}
        agentId={41}
        defaultVersionName="Medic 2-2609220930"
      />
    );

    expect(
      (screen.getByLabelText("agent.version.versionName") as HTMLInputElement)
        .value
    ).toBe("Medic 2-2609220930");
  });
});
