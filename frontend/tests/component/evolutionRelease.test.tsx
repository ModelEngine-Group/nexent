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
  useTranslation: () => ({
    t: (key: string, values?: { names?: string; name?: string; digest?: string; candidate?: number; experiment?: number }) =>
      key === "evolution.release.component" ? `#${values?.candidate} from ${values?.experiment}` :
      key === "evolution.release.addedGuide" ? `${values?.name} ${values?.digest}` : values?.names ?? key,
  }),
}));
vi.mock("@/services/evolutionService", () => ({
  evolutionService: { releaseMonitoring: vi.fn(), release: vi.fn(), promote: vi.fn(), rollback: vi.fn() },
}));

const passed: Awaited<ReturnType<typeof api.release>> = {
  agent_id: 7,
  experiment_id: 11,
  base_version: 2,
  current_version: 2,
  paused: false,
  candidate_digest: "a".repeat(64),
  candidate_type: "skill_step",
  supported_type: true,
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

it("shows the specific tool removed by a confirmed T3 candidate before promotion", async () => {
  vi.mocked(api.release).mockResolvedValue({
    ...passed,
    candidate_type: "tool_set",
    excluded_tools: ["analyze_text_file"],
  });
  open();
  expect(await screen.findByText("analyze_text_file")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Confirmed text intake scope" },
  });
  expect(
    screen.getByRole("button", { name: "evolution.release.publish" })
  ).toBeEnabled();
});

it("identifies the exact new Skill package before a publisher changes the default", async () => {
  vi.mocked(api.release).mockResolvedValue({
    ...passed,
    candidate_type: "skill_new",
    added_guide: {candidate_id: 7, name:"intake", digest:"abcdef12".repeat(8)},
  });
  open();
  expect(await screen.findByText("intake abcdef12abcd")).toBeInTheDocument();
  expect(screen.getByRole("button", {name:"evolution.release.publish"})).toBeDisabled();
});

it("shows the old and proposed catalog description", async () => {
  vi.mocked(api.release).mockResolvedValue({
    ...passed, candidate_type: "skill_discovery",
    skill_description: {name: "meeting", previous: "Summarize meetings", proposed: "Summarize meetings and handovers"},
  });
  open();
  expect(await screen.findByText("Summarize meetings")).toBeInTheDocument();
  expect(screen.getByText("Summarize meetings and handovers")).toBeInTheDocument();
});

it("identifies both tested revisions in a combined release", async () => {
  vi.mocked(api.release).mockResolvedValue({
    ...passed, candidate_type: "combination", components: [
      {experiment_id: 12, candidate_type: "prompt", candidate_id: 5},
      {experiment_id: 16, candidate_type: "tool_set", candidate_id: 8},
    ], excluded_tools: ["file_analysis"],
  });
  open();
  expect(await screen.findByText("#5 from 12")).toBeInTheDocument();
  expect(screen.getByText("#8 from 16")).toBeInTheDocument();
  expect(screen.getByText("file_analysis")).toBeInTheDocument();
});

it("shows the approved script and the sandbox image verified before release", async () => {
  const image = `sha256:${"a".repeat(64)}`;
  vi.mocked(api.release).mockResolvedValue({
    ...passed, candidate_type: "skill_script",
    script_build: {name: "weekly", path: "scripts/weekly.py", function: "normalize", image},
  });
  open();
  expect(await screen.findByText("scripts/weekly.py")).toBeInTheDocument();
  expect(screen.getByText("normalize")).toBeInTheDocument();
  expect(screen.getByText(image)).toBeInTheDocument();
});

it.each(["skill_new","skill_discovery","skill_script","tool_mapping","combination"])(
  "submits a supported %s release after the owner supplies a reason", async kind => {
    vi.mocked(api.release).mockResolvedValue({...passed,candidate_type:kind});
    open();
    fireEvent.change(await screen.findByRole("textbox"),{target:{value:"verified scope"}});
    expect(screen.getByRole("button",{name:"evolution.release.publish"})).toBeEnabled();
    fireEvent.click(screen.getByRole("button",{name:"evolution.release.publish"}));
    await waitFor(()=>expect(api.promote).toHaveBeenCalledWith(8,2,passed.candidate_digest,"verified scope"));
  }
);

it("keeps unknown candidate types closed and distinguishes absent samples from zero", async () => {
  vi.mocked(api.release).mockResolvedValue({...passed,supported_type:false,candidate_type:"unbound"});
  const view=render(<QueryClientProvider client={new QueryClient()}><ReleasePage/></QueryClientProvider>);
  fireEvent.change(await screen.findByRole("textbox"),{target:{value:"not bound"}});
  expect(screen.getByRole("button",{name:"evolution.release.publish"})).toBeDisabled();
  view.unmount();
  vi.mocked(api.release).mockResolvedValue({...passed,current_version:3,release:{new_version:3,disabled:false,rollback_at:null}});
  vi.mocked(api.releaseMonitoring).mockResolvedValue({
    since:"2026-01-01T00:00:00Z",until:"2026-01-02T00:00:00Z",versions:[{
      version_no:3,sessions:1,executions:2,unverified:0,binding_mismatches:0,failed:0,stopped:0,timed:2,p90_ms:150.6,metered:0,mean_tokens:null,
      reviewed:0,tool_errors:0,corrected:0,disliked:0,missing_files:0}],
    events:[{action:"publish",actor:"publisher",reason:"validated cases",created_at:"2026-01-01T00:00:00Z"}]});
  open();
  fireEvent.click(await screen.findByRole("button",{name:"evolution.monitor.open"}));
  expect(await screen.findByText("151 ms")).toBeInTheDocument();
  expect(screen.getByText(/validated cases/)).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThan(1);
  expect(api.releaseMonitoring).toHaveBeenCalledWith(8);
});
