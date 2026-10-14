import React from "react";
import { App } from "antd";
import { screen, waitFor } from "@testing-library/dom";
import { cleanup, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClientLayout } from "../../app/[locale]/layout.client";
import { useAuthenticationUI } from "@/hooks/auth/useAuthenticationUI";

const routerPush = vi.fn();

const authenticationContext = {
  isAuthenticated: false,
  isAuthPromptModalOpen: true,
  isSessionExpiredModalOpen: false,
  closeAuthPromptModal: vi.fn(),
  openLoginModal: vi.fn(),
  openRegisterModal: vi.fn(),
  closeSessionExpiredModal: vi.fn(),
  openLoginModalAfterSessionExpired: vi.fn(),
};

vi.mock("next/navigation", () => ({
  usePathname: () => "/zh/share/snapshot-id",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/image", () => ({
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} />
  ),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => authenticationContext,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    isAuthorized: false,
    isAuthzPromptModalOpen: false,
    closeAuthzPromptModal: vi.fn(),
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: false }),
}));
vi.mock("@/stores/global", () => ({
  useGlobalConfigStore: () => ({ config: { aboutConfig: "closed" } }),
}));
vi.mock("@/services/forcedLoginService", () => ({
  forcedLoginService: {
    redirectIfNeeded: vi.fn().mockResolvedValue(false),
    suppressOAuthAutoLogin: vi.fn(),
  },
}));
vi.mock("@/lib/auth", () => ({
  getEffectiveRoutePath: (pathname: string) => pathname.replace(/^\/zh/, ""),
}));
vi.mock("@/components/navigation/TopNavbar", () => ({ TopNavbar: () => null }));
vi.mock("@/components/navigation/SideNavigation", () => ({
  SideNavigation: () => null,
}));
vi.mock("@/components/navigation/FooterLayout", () => ({
  FooterLayout: () => null,
}));

afterEach(cleanup);

function LoginTransitionHarness() {
  const auth = useAuthenticationUI({
    isAuthenticated: false,
    isAuthChecking: false,
    clearLocalSession: vi.fn(),
  });

  return (
    <>
      <button
        onClick={() => {
          auth.closeAuthPromptModal();
          auth.openLoginModal();
        }}
      >
        Continue to login
      </button>
      {auth.isLoginModalOpen && <p>Login modal open</p>}
    </>
  );
}

describe("conversation share layout authentication", () => {
  it("renders the global login prompt for an unauthenticated conversation share route", () => {
    render(
      <ClientLayout>
        <main>Shared conversation</main>
      </ClientLayout>
    );

    expect(screen.getByText("Shared conversation")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "page.loginPrompt.login" })
    ).toBeInTheDocument();
  });

  it("keeps the conversation share return address when continuing from the login prompt", async () => {
    const user = userEvent.setup();
    render(
      <App>
        <LoginTransitionHarness />
      </App>
    );

    await user.click(screen.getByRole("button", { name: "Continue to login" }));

    await waitFor(() =>
      expect(screen.getByText("Login modal open")).toBeInTheDocument()
    );
    expect(routerPush).not.toHaveBeenCalled();
  });
});
