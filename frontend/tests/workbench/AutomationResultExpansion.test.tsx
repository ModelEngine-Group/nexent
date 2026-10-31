// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { message } from "antd";
import AgentTasksPage from "@/app/agent-tasks/page";
import { agentAutomationService } from "@/services/agentAutomationService";
import { conversationService } from "@/services/conversationService";
import type { AgentAutomationTask } from "@/types/agentAutomation";

const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ locale: "en" }),
}));
vi.mock(
  "@/features/agentAutomation/components/AutomationDateTimePicker",
  () => ({
    default: () => null,
  })
);
vi.mock("@/services/agentAutomationService", () => ({
  agentAutomationService: { list: vi.fn(), runs: vi.fn(), run: vi.fn() },
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: { getDetail: vi.fn() },
}));

const task = {
  task_id: 31,
  conversation_id: 41,
  title: "Result fixture",
  agent_name: "Fixture agent",
  status: "PAUSED",
  last_run_status: "SUCCEEDED",
  schedule_config: {
    mode: "RECURRING",
    rule_type: "INTERVAL",
    interval_seconds: 60,
    start_at: "2026-10-21T00:00:00Z",
    timezone: "Asia/Shanghai",
  },
} as AgentAutomationTask;
const runs = {
  items: [
    {
      run_id: 51,
      task_id: 31,
      status: "SUCCEEDED",
      trigger_type: "MANUAL",
      assistant_message_id: 61,
    },
  ],
  total: 1,
  page: 1,
  page_size: 1,
};
const detail = {
  code: 0,
  message: "ok",
  data: [
    {
      conversation_id: 41,
      message: [
        { message_id: 61, role: "assistant", message: "RESULT_OUTPUT" },
      ],
    },
  ],
};

function eye() {
  return screen.getByRole("button", {
    name: /agentAutomation.page.(viewResult|collapseResult)/,
  });
}
async function openPage() {
  render(<AgentTasksPage />);
  await screen.findByText(task.title);
}
beforeEach(() => {
  vi.mocked(agentAutomationService.list)
    .mockReset()
    .mockResolvedValue({ items: [task], total: 1, page: 1, page_size: 20 });
  vi.mocked(agentAutomationService.runs)
    .mockReset()
    .mockResolvedValue(runs as never);
  vi.mocked(conversationService.getDetail)
    .mockReset()
    .mockResolvedValue(detail as never);
});

it("keeps only the Recent Result control and removes the empty expansion column", async () => {
  await openPage();
  expect(
    screen.queryByRole("button", { name: /Expand row|Collapse row/ })
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("columnheader")).toHaveLength(7);
  expect(eye()).toBeVisible();
  expect(agentAutomationService.runs).not.toHaveBeenCalled();
  expect(conversationService.getDetail).not.toHaveBeenCalled();
});

it("loads fresh output whenever Recent Result is reopened", async () => {
  await openPage();
  fireEvent.click(eye());
  expect(await screen.findByText("RESULT_OUTPUT")).toBeVisible();
  expect(agentAutomationService.runs).toHaveBeenCalledWith(31, {
    page: 1,
    pageSize: 1,
  });
  expect(conversationService.getDetail).toHaveBeenCalledWith(41);
  fireEvent.click(eye());
  await waitFor(() =>
    expect(screen.queryByText("RESULT_OUTPUT")).not.toBeVisible()
  );
  fireEvent.click(eye());
  expect(await screen.findByText("RESULT_OUTPUT")).toBeVisible();
  expect(agentAutomationService.runs).toHaveBeenCalledTimes(2);
  expect(conversationService.getDetail).toHaveBeenCalledTimes(2);
});

it("reports a failed load and retries through Recent Result", async () => {
  const report = vi
    .spyOn(message, "error")
    .mockImplementation(() => ({}) as never);
  vi.mocked(agentAutomationService.runs).mockRejectedValueOnce(
    new Error("offline")
  );
  await openPage();
  fireEvent.click(eye());
  await waitFor(() =>
    expect(report).toHaveBeenCalledWith(
      "agentAutomation.page.historyLoadFailed"
    )
  );
  fireEvent.click(eye());
  fireEvent.click(eye());
  expect(await screen.findByText("RESULT_OUTPUT")).toBeVisible();
  expect(agentAutomationService.runs).toHaveBeenCalledTimes(2);
  expect(conversationService.getDetail).toHaveBeenCalledTimes(2);
});

it("refetches an empty result when reopened", async () => {
  vi.mocked(agentAutomationService.runs).mockResolvedValue({
    ...runs,
    items: [],
  });
  await openPage();
  fireEvent.click(eye());
  expect(await screen.findByText("agentAutomation.page.noRuns")).toBeVisible();
  fireEvent.click(eye());
  fireEvent.click(eye());
  expect(agentAutomationService.runs).toHaveBeenCalledTimes(2);
});

function nextResult(text: string) {
  vi.mocked(agentAutomationService.runs).mockResolvedValue({
    ...runs,
    items: [{ ...runs.items[0], run_id: 52, assistant_message_id: 62 }],
  } as never);
  vi.mocked(conversationService.getDetail).mockResolvedValue({
    ...detail,
    data: [
      {
        conversation_id: 41,
        message: [{ message_id: 62, role: "assistant", message: text }],
      },
    ],
  } as never);
  vi.mocked(agentAutomationService.list).mockResolvedValue({
    items: [{ ...task }],
    total: 1,
    page: 1,
    page_size: 20,
  });
}

it("refreshes the open result when the list is refreshed", async () => {
  await openPage();
  fireEvent.click(eye());
  expect(await screen.findByText("RESULT_OUTPUT")).toBeVisible();
  nextResult("SCHEDULED_OUTPUT");
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  expect(await screen.findByText("SCHEDULED_OUTPUT")).toBeVisible();
  expect(screen.queryByText("RESULT_OUTPUT")).not.toBeInTheDocument();
});

it("ignores a slower response after a newer refresh", async () => {
  let resolveOld!: (value: never) => void;
  vi.mocked(agentAutomationService.runs).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve;
      })
  );
  await openPage();
  fireEvent.click(eye());
  nextResult("NEWEST_OUTPUT");
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  expect(await screen.findByText("NEWEST_OUTPUT")).toBeVisible();
  await act(async () => resolveOld(runs as never));
  expect(screen.getByText("NEWEST_OUTPUT")).toBeVisible();
  expect(screen.queryByText("RESULT_OUTPUT")).not.toBeInTheDocument();
});

it.each(["CANCELED", "FAILED", "TIMEOUT", "SKIPPED"])(
  "reports %s without a success notification",
  async (status) => {
    const success = vi
      .spyOn(message, "success")
      .mockImplementation(() => ({}) as never);
    const notify = vi
      .spyOn(
        message,
        status === "FAILED" || status === "TIMEOUT" ? "error" : "info"
      )
      .mockImplementation(() => ({}) as never);
    vi.mocked(agentAutomationService.run).mockResolvedValue({
      ...runs.items[0],
      status,
    } as never);
    await openPage();
    fireEvent.click(
      screen.getByRole("button", { name: "agentAutomation.page.run" })
    );
    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith(`agentAutomation.runStatus.${status}`)
    );
    expect(success).not.toHaveBeenCalled();
  }
);
