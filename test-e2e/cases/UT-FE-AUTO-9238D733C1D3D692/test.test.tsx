import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { ChatTopNavContent } from "@/components/navigation/ChatTopNavContent";
import { APP_DISPLAY_NAME } from "@/const/modelConfig";

const mocks = vi.hoisted(() => {
  const push = vi.fn();
  const getAppAvatarUrl = vi.fn();
  const state = {
    appConfig: { avatarUri: "", appName: "SomeOtherAppName" },
    language: "en",
  };
  return { push, getAppAvatarUrl, state };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { language: mocks.state.language },
  }),
}));

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({
    appConfig: mocks.state.appConfig,
    getAppAvatarUrl: mocks.getAppAvatarUrl,
  }),
}));

vi.mock("@/lib/avatar", () => ({
  extractColorsFromUri: () => ({ mainColor: "aabbcc", secondaryColor: "112233" }),
}));

describe("ChatTopNavContent", () => {
  beforeEach(() => {
    mocks.push.mockClear();
    mocks.getAppAvatarUrl.mockReturnValue("https://example.com/avatar.png");
    mocks.state.appConfig = { avatarUri: "", appName: "SomeOtherAppName" };
    mocks.state.language = "en";
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("UT-FE-AUTO-9238D733C1D3D692 renders top nav logo alt and app name text from APP_DISPLAY_NAME", () => {
    const { container } = render(<ChatTopNavContent />);

    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("alt")).toBe(APP_DISPLAY_NAME);
    expect(img!.getAttribute("src")).toBe("https://example.com/avatar.png");

    const span = container.querySelector("span");
    expect(span).not.toBeNull();
    expect(span!.textContent).toBe(APP_DISPLAY_NAME);

    expect(container.textContent).not.toMatch(/(api[_-]?key|secret|token|Bearer|password)/i);
  });

  it("keeps gradient styling and 16px font size on the app name span", () => {
    const { container } = render(<ChatTopNavContent />);

    const span = container.querySelector("span");
    expect(span).not.toBeNull();
    expect(span!.className).toContain("bg-clip-text");
    expect(span!.className).toContain("text-transparent");
    expect(span!.style.fontSize).toBe("16px");
    expect(span!.style.backgroundImage).toContain("linear-gradient");
  });

  it("calls router.push with /<language> when the container is clicked", () => {
    const { container } = render(<ChatTopNavContent />);

    const clickable = container.querySelector('div[class*="cursor-pointer"]');
    expect(clickable).not.toBeNull();
    fireEvent.click(clickable!);

    expect(mocks.push).toHaveBeenCalledTimes(1);
    expect(mocks.push).toHaveBeenCalledWith("/en");
  });

  it("stays decoupled from appConfig.appName when appName changes", () => {
    mocks.state.appConfig = { avatarUri: "", appName: "ChangedAppName" };
    const { container } = render(<ChatTopNavContent />);

    const img = container.querySelector("img");
    const span = container.querySelector("span");
    expect(img!.getAttribute("alt")).toBe(APP_DISPLAY_NAME);
    expect(span!.textContent).toBe(APP_DISPLAY_NAME);
  });
});
