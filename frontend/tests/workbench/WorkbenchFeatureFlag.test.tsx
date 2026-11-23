import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import WorkbenchRoute from "@/app/workbench/page";

const state = vi.hoisted(() => ({
  enabled: false,
  ready: false,
  replace: vi.fn(),
}));

vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({
    isDeploymentReady: state.ready,
    enableAgentWorkbench: state.enabled,
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: state.replace }),
}));
vi.mock("@/features/workbench/WorkbenchPage", () => ({
  default: () => <div>Workbench mounted</div>,
}));

beforeEach(() => {
  state.enabled = false;
  state.ready = false;
  state.replace.mockReset();
});

it("waits for deployment config before mounting Workbench", () => {
  render(<WorkbenchRoute />);
  expect(screen.queryByText("Workbench mounted")).not.toBeInTheDocument();
  expect(state.replace).not.toHaveBeenCalled();
});

it("redirects when the Workbench feature is disabled", async () => {
  state.ready = true;
  render(<WorkbenchRoute />);
  expect(screen.queryByText("Workbench mounted")).not.toBeInTheDocument();
  await waitFor(() => expect(state.replace).toHaveBeenCalledWith("/"));
});

it("mounts Workbench only when the feature is enabled", () => {
  state.ready = true;
  state.enabled = true;
  render(<WorkbenchRoute />);
  expect(screen.getByText("Workbench mounted")).toBeInTheDocument();
  expect(state.replace).not.toHaveBeenCalled();
});
