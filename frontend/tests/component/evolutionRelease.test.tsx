// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ReleasePage from "@/app/evaluation/releases/[lockId]/page";
import { evolutionService as api } from "@/services/evolutionService";

vi.mock("next/navigation", () => ({ useParams: () => ({ lockId: "8" }) }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { id: "owner", tenantId: "pilot" } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/evolutionService", () => ({
  evolutionService: { release: vi.fn(), promote: vi.fn(), rollback: vi.fn() },
}));

const passed: Awaited<ReturnType<typeof api.release>> = {
  agent_id: 7,
  experiment_id: 11,
  base_version: 2,
  current_version: 2,
  paused: false,
  candidate_digest: "a".repeat(64),
  candidate_type: "skill_step",
  release: null,
  summary: { decision: "passed", valid_pairs: 3, total_pairs: 3, regressed: 0 },
};
function open() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ReleasePage />
    </QueryClientProvider>
  );
}
it("publishes the independently confirmed digest and requires a reason", async () => {
  vi.mocked(api.release).mockResolvedValue(passed);
  open();
  const publish = await screen.findByRole("button", {
    name: "evolution.release.publish",
  });
  expect(publish).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: " passed pilot " },
  });
  fireEvent.click(publish);
  await waitFor(() =>
    expect(api.promote).toHaveBeenCalledWith(
      8,
      2,
      passed.candidate_digest,
      "passed pilot"
    )
  );
});
it("can emergency-stop a version after its normal rollback", async () => {
  vi.mocked(api.release).mockResolvedValue({
    ...passed,
    release: { new_version: 3, rollback_at: "today", disabled: false },
  });
  open();
  const reason = await screen.findByRole("textbox");
  fireEvent.change(reason, { target: { value: "stop old sessions" } });
  expect(
    screen.getByRole("button", { name: "evolution.release.rollback" })
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", { name: "evolution.release.stop" })
  );
  await waitFor(() =>
    expect(api.rollback).toHaveBeenCalledWith(8, 3, "stop old sessions", true)
  );
});
it("shows authorization failures without release actions", async () => {
  vi.mocked(api.release).mockRejectedValue(
    new Error("Publisher permission required")
  );
  open();
  expect(
    await screen.findByText("Publisher permission required")
  ).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).toBeNull();
});
