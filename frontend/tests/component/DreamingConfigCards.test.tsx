// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, test, vi } from "vitest";
import en from "../../public/locales/en/common.json";
import zh from "../../public/locales/zh/common.json";
import { DreamingConfigCards } from "@/app/memory/DreamingConfigCards";
import {
  fetchDreamingAudits,
  fetchDreamingSchedule,
  type DreamingAudit,
} from "@/services/memoryService";

const language = vi.hoisted(() => ({ current: "zh" as "zh" | "en" }));
const translations = { zh, en };
const reasons = [
  "no_candidates",
  "no_eligible_candidates",
  "no_new_evidence",
] as const;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const dictionary = translations[language.current];
      return dictionary[key as keyof typeof dictionary] ?? key;
    },
  }),
}));

vi.mock("@/services/memoryService", () => ({
  fetchDreamingAudits: vi.fn(),
  fetchDreamingSchedule: vi.fn(),
  runDreaming: vi.fn(),
  saveDreamingSchedule: vi.fn(),
}));

beforeEach(() => {
  language.current = "zh";
  vi.mocked(fetchDreamingSchedule).mockResolvedValue({
    agent_id: "__user__",
    enabled: false,
    rule_type: "CRON",
    timezone: "UTC",
    cron_expr: "0 3 * * *",
    fire_count: 0,
  });
});

function showRun(overrides: Partial<DreamingAudit>) {
  vi.mocked(fetchDreamingAudits).mockResolvedValue([
    {
      run_id: 1,
      status: "completed",
      light_count: 0,
      rem_count: 0,
      promoted_count: 0,
      deferred_count: 0,
      ...overrides,
    },
  ]);
  render(
    <App>
      <DreamingConfigCards />
    </App>
  );
}

for (const locale of ["zh", "en"] as const) {
  test.each(reasons)(
    "%s is visible after completion in " + locale,
    async (reason) => {
      language.current = locale;
      showRun({ reason });
      expect(
        await screen.findByText(translations[locale]["dreaming.run.completed"])
      ).toBeVisible();
      expect(
        await screen.findByText(
          translations[locale][`dreaming.reason.${reason}`]
        )
      ).toBeVisible();
      expect(
        screen.queryByText(reason, { exact: true })
      ).not.toBeInTheDocument();
    }
  );
}

test.each([null, "unknown_reason"])(
  "completion handles reason %s without exposing internal codes",
  async (reason) => {
    showRun({ reason, published_version_id: reason === null ? 7 : null });
    expect(await screen.findByText(zh["dreaming.run.completed"])).toBeVisible();
    for (const known of reasons) {
      expect(
        screen.queryByText(zh[`dreaming.reason.${known}`])
      ).not.toBeInTheDocument();
    }
    expect(
      screen.queryByText("unknown_reason", { exact: true })
    ).not.toBeInTheDocument();
  }
);

test.each(["queued", "running", "failed", "skipped"] as const)(
  "%s does not show a completion reason",
  async (status) => {
    showRun({
      status,
      reason: "no_new_evidence",
      error: "database unavailable",
    });
    const text = {
      queued: zh["dreaming.run.queued"],
      running: zh["dreaming.run.runningPhase"],
      failed: zh["dreaming.run.failed"],
      skipped: zh["dreaming.run.skipped"],
    }[status];
    expect(await screen.findByText(text)).toBeVisible();
    expect(
      screen.queryByText(zh["dreaming.reason.no_new_evidence"])
    ).not.toBeInTheDocument();
    if (status === "failed") {
      expect(screen.getByText("database unavailable")).toBeVisible();
    }
  }
);
