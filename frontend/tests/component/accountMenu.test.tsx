import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { AvatarDropdown } from "@/components/auth/avatarDropdown";
import { APP_VERSION } from "@/const/constants";

const state = vi.hoisted(() => ({
  user: {
    username: "Admin",
    email: "admin@nexent.test",
    role: "ADMIN",
    avatarUrl: "",
  } as null | {
    username: string;
    email: string;
    role: string;
    avatarUrl: string;
  },
  loading: false,
  about: "open",
  version: "v2.6.0",
  monitoring: null as string | null,
  language: "zh",
  changeLanguage: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
  confirm: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/link", () => ({
  default: ({
    children,
    prefetch,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    prefetch?: boolean;
  }) => (
    <a {...props} data-prefetch={String(prefetch)}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: state.user }),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => ({
    isLoading: state.loading,
    logout: state.logout,
    openLoginModal: state.login,
    openRegisterModal: state.register,
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ appVersion: state.version }),
}));
vi.mock("@/stores/global", () => ({
  useGlobalConfigStore: () => ({ config: { aboutConfig: state.about } }),
}));
vi.mock("@/hooks/useAccountMonitoring", () => ({
  useAccountMonitoring: () => state.monitoring,
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: state.confirm }),
}));
vi.mock("@/lib/language", () => ({
  useLanguageSwitch: () => ({
    currentLanguage: state.language,
    handleLanguageChange: state.changeLanguage,
  }),
}));

beforeEach(() => {
  state.user = {
    username: "Admin",
    email: "admin@nexent.test",
    role: "ADMIN",
    avatarUrl: "",
  };
  state.loading = false;
  state.about = "open";
  state.version = "v2.6.0";
  state.monitoring = null;
  state.language = "zh";
});

async function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "accountMenu.open" }));
  await screen.findByRole("menu");
  await waitFor(() => expect(screen.getByRole("menu")).toBeVisible());
}

test("account menu retains identity, profile, all former bar links and no appearance entry", async () => {
  state.monitoring = "https://monitoring.nexent.test";
  render(<AvatarDropdown rail />);
  await openMenu();
  expect(screen.getByText("Admin")).toBeVisible();
  expect(screen.getByText("auth.admin")).toBeVisible();
  expect(screen.getByRole("link", { name: "profile.title" })).toHaveAttribute(
    "href",
    "/zh/users"
  );
  expect(screen.getByText("v2.6.0")).toBeVisible();
  expect(screen.getByText("page.copyright")).toBeVisible();
  expect(
    screen.getByRole("link", { name: "accountMenu.github" })
  ).toHaveAttribute("href", "https://github.com/ModelEngine-Group/nexent");
  expect(screen.getByRole("link", { name: "ModelEngine" })).toHaveAttribute(
    "href",
    "http://modelengine-ai.net"
  );
  expect(screen.getByRole("link", { name: "page.termsOfUse" })).toHaveAttribute(
    "href",
    "https://github.com/nexent-hub/nexent?tab=License-1-ov-file#readme"
  );
  expect(
    screen.getByRole("link", { name: "monitoring.topbar.openDashboard" })
  ).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.queryByText(/appearance/i)).toBeNull();
});

test.each(["zh", "en"])(
  "profile uses %s route without automatic prefetch",
  async (language) => {
    state.language = language;
    render(<AvatarDropdown rail />);
    await openMenu();
    const profile = screen.getByRole("link", { name: "profile.title" });
    expect(profile).toHaveAttribute("href", `/${language}/users`);
    expect(profile).toHaveAttribute("data-prefetch", "false");
  }
);

test("closed about settings hide links while retaining version fallback and language", async () => {
  state.about = "closed";
  state.version = "";
  render(<AvatarDropdown rail />);
  await openMenu();
  expect(screen.getByText(APP_VERSION)).toBeVisible();
  expect(screen.getByText("accountMenu.language")).toBeVisible();
  expect(screen.queryByRole("link", { name: "ModelEngine" })).toBeNull();
  expect(screen.queryByRole("link", { name: "accountMenu.github" })).toBeNull();
  expect(screen.queryByRole("link", { name: "page.termsOfUse" })).toBeNull();
  expect(
    screen.queryByRole("link", { name: "monitoring.topbar.openDashboard" })
  ).toBeNull();
});

test.each(["login", "register"])(
  "anonymous menu retains %s and supplemental entries",
  async (action) => {
    state.user = null;
    render(<AvatarDropdown rail />);
    await openMenu();
    expect(screen.getByText("auth.notLoggedIn")).toBeVisible();
    expect(screen.getByText("accountMenu.language")).toBeVisible();
    expect(screen.getByText("v2.6.0")).toBeVisible();
    expect(screen.queryByText("auth.logout")).toBeNull();
    fireEvent.click(screen.getByText(`auth.${action}`));
    expect(
      action === "login" ? state.login : state.register
    ).toHaveBeenCalledOnce();
  }
);

test("language submenu checks current locale and delegates selected language", async () => {
  render(<AvatarDropdown rail />);
  await openMenu();
  fireEvent.mouseEnter(
    screen
      .getByText("accountMenu.language")
      .closest(".ant-dropdown-menu-submenu-title")!
  );
  await screen.findByText("English");
  expect(
    screen.getByLabelText("accountMenu.selectedLanguage").parentElement
  ).toHaveTextContent("简体中文");
  fireEvent.click(screen.getByText("English"));
  expect(state.changeLanguage).toHaveBeenCalledWith("en");
  await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
});

test("logout retains confirmation and does not logout before acceptance", async () => {
  render(<AvatarDropdown rail />);
  await openMenu();
  fireEvent.click(screen.getByText("auth.logout"));
  expect(state.logout).not.toHaveBeenCalled();
  expect(state.confirm).toHaveBeenCalledWith(
    expect.objectContaining({
      title: "auth.confirmLogout",
      content: "auth.confirmLogoutPrompt",
    })
  );
  state.confirm.mock.calls[0][0].onOk();
  expect(state.logout).toHaveBeenCalledOnce();
});

test("loading has no actionable account menu; empty username falls back to email", async () => {
  state.loading = true;
  const { rerender } = render(<AvatarDropdown rail />);
  expect(screen.queryByRole("button")).toBeNull();
  state.loading = false;
  state.user!.username = " ";
  rerender(<AvatarDropdown rail />);
  await openMenu();
  expect(screen.getByText("admin@nexent.test")).toBeVisible();
});
