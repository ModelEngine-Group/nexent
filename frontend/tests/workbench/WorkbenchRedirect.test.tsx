import { beforeEach, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import WorkbenchRedirect from "@/features/workbench/WorkbenchRedirect";

const navigation = vi.hoisted(() => ({ replace: vi.fn(), locale: "zh" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace }),
  useParams: () => ({ locale: navigation.locale }),
}));
vi.mock("@/lib/basePath", () => ({
  withBasePath: (value: string) => `/base${value}`,
}));

beforeEach(() => {
  navigation.replace.mockClear();
  window.history.replaceState(
    {},
    "",
    "/zh/chat?conversation_id=7&share=token#message-3"
  );
});

it("UT-FE-WB-001 routes the locale root to canonical Workbench without losing state", async () => {
  render(<WorkbenchRedirect />);
  await waitFor(() =>
    expect(navigation.replace).toHaveBeenCalledWith(
      "/base/zh/newchat?conversation_id=7&share=token#message-3"
    )
  );
});

it("UT-FE-WB-002 routes legacy chat to the same canonical Workbench", async () => {
  window.history.replaceState(
    {},
    "",
    "/zh/chat?thread_id=8&automation=1#latest"
  );
  render(<WorkbenchRedirect />);
  await waitFor(() =>
    expect(navigation.replace).toHaveBeenCalledWith(
      "/base/zh/newchat?thread_id=8&automation=1#latest"
    )
  );
});
