"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  App,
  Badge,
  Button,
  Card,
  Flex,
  InputNumber,
  Modal,
  Select,
  Switch,
  TimePicker,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";

import {
  fetchDreamingSchedule,
  fetchDreamingAudits,
  runDreaming,
  saveDreamingSchedule,
  type DreamingAudit,
  type DreamingSchedule,
} from "@/services/memoryService";

const { Text } = Typography;

type FrequencyMode = "daily" | "weekly" | "interval";

const DEFAULT_VALUES = {
  min_score: 0.75,
  min_recall_count: 3,
  min_unique_queries: 3,
  source_limit: 10,
  long_term_max_chars: 10000,
  summarization_max_attempts: 2,
} as const;

const INPUT_RANGES = {
  minScore: { min: 0, max: 1 },
  minRecallCount: { min: 0, max: 100 },
  minUniqueQueries: { min: 0, max: 50 },
  sourceLimit: { min: 1, max: 100 },
  longTermMaxChars: { min: 100, max: 1_000_000 },
  summarizationMaxAttempts: { min: 0, max: 10 },
} as const;

function parseCronExpr(
  cronExpr: string | null | undefined
): { hour: number; minute: number; weekday: number | null } | null {
  if (!cronExpr) return null;
  const parts = cronExpr.trim().split(/\s+/);
  if (parts.length < 5) return null;
  const minute = Number.parseInt(parts[0], 10);
  const hour = Number.parseInt(parts[1], 10);
  const dow = parts[4];
  if (Number.isNaN(minute) || Number.isNaN(hour)) return null;
  const weekday = dow === "*" ? null : Number.parseInt(dow, 10);
  return {
    hour,
    minute,
    weekday: Number.isNaN(weekday as number) ? null : weekday,
  };
}

function buildCronExpr(
  hour: number,
  minute: number,
  mode: FrequencyMode,
  weekday: number
): string {
  if (mode === "weekly") {
    return `${minute} ${hour} * * ${weekday}`;
  }
  return `${minute} ${hour} * * *`;
}

export function DreamingConfigCards() {
  const { message } = App.useApp();
  const { t } = useTranslation("common");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [latestRun, setLatestRun] = useState<DreamingAudit | null>(null);
  const [schedule, setSchedule] = useState<DreamingSchedule | null>(null);

  const [enabled, setEnabled] = useState(false);
  const [frequency, setFrequency] = useState<FrequencyMode>("daily");
  const [time, setTime] = useState(dayjs().hour(3).minute(0));
  const [weekday, setWeekday] = useState(1);
  const [intervalHours, setIntervalHours] = useState(6);

  const [minScore, setMinScore] = useState<number | null>(null);
  const [minRecallCount, setMinRecallCount] = useState<number | null>(null);
  const [minUniqueQueries, setMinUniqueQueries] = useState<number | null>(null);
  const [sourceLimit, setSourceLimit] = useState<number | null>(null);
  const [longTermMaxChars, setLongTermMaxChars] = useState<number | null>(null);
  const [summarizationMaxAttempts, setSummarizationMaxAttempts] = useState<
    number | null
  >(null);

  useEffect(() => {
    let active = true;
    fetchDreamingSchedule()
      .then((data) => {
        if (!active) return;
        setSchedule(data);
        setEnabled(data.enabled);

        if (data.rule_type === "INTERVAL") {
          setFrequency("interval");
          setIntervalHours(
            data.interval_seconds ? data.interval_seconds / 3600 : 6
          );
        } else {
          const parsed = parseCronExpr(data.cron_expr);
          if (parsed) {
            setTime(dayjs().hour(parsed.hour).minute(parsed.minute));
            if (parsed.weekday !== null) {
              setFrequency("weekly");
              setWeekday(parsed.weekday);
            } else {
              setFrequency("daily");
            }
          }
        }

        setMinScore(data.min_score ?? null);
        setMinRecallCount(data.min_recall_count ?? null);
        setMinUniqueQueries(data.min_unique_queries ?? null);
        setSourceLimit(data.source_limit ?? null);
        setLongTermMaxChars(data.long_term_max_chars ?? null);
        setSummarizationMaxAttempts(data.summarization_max_attempts ?? null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refreshLatestRun = async () => {
      try {
        const audits = await fetchDreamingAudits(1);
        if (!active) return;
        const latest = audits[0] ?? null;
        setLatestRun(latest);
        setRunning(latest?.status === "queued" || latest?.status === "running");
        if (latest?.status === "completed") {
          window.dispatchEvent(new Event("user-long-term-memory-updated"));
        }
        if (latest?.status === "queued" || latest?.status === "running") {
          timer = setTimeout(refreshLatestRun, 2000);
        }
      } catch {
        if (active) setRunning(false);
      }
    };
    void refreshLatestRun();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [latestRun?.run_id, latestRun?.status]);

  const buildSchedulePayload = useCallback((): Omit<
    DreamingSchedule,
    "fire_count"
  > => {
    const base = schedule!;
    const hour = time.hour();
    const minute = time.minute();

    let ruleType: "CRON" | "INTERVAL" = "CRON";
    let cronExpr: string | null = null;
    let intervalSeconds: number | null = null;

    if (frequency === "interval") {
      ruleType = "INTERVAL";
      intervalSeconds = intervalHours * 3600;
    } else {
      cronExpr = buildCronExpr(hour, minute, frequency, weekday);
    }

    return {
      schedule_id: base.schedule_id,
      agent_id: base.agent_id,
      enabled,
      rule_type: ruleType,
      timezone:
        base.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
      start_at: base.start_at,
      cron_expr: cronExpr,
      interval_seconds: intervalSeconds,
      next_fire_at: base.next_fire_at,
      last_fire_at: base.last_fire_at,
      min_score: minScore,
      min_recall_count: minRecallCount,
      min_unique_queries: minUniqueQueries,
      source_limit: sourceLimit,
      long_term_max_chars: longTermMaxChars,
      summarization_max_attempts: summarizationMaxAttempts,
    };
  }, [
    schedule,
    enabled,
    frequency,
    time,
    weekday,
    intervalHours,
    minScore,
    minRecallCount,
    minUniqueQueries,
    sourceLimit,
    longTermMaxChars,
    summarizationMaxAttempts,
  ]);

  const handleSaveSchedule = async () => {
    if (!schedule) return;
    setSaving(true);
    try {
      const payload = buildSchedulePayload();
      const saved = await saveDreamingSchedule(payload);
      setSchedule(saved);
      message.success(t("dreaming.schedule.saved"));
    } catch {
      message.error(t("dreaming.schedule.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveThresholds = async () => {
    if (!schedule) return;
    setSaving(true);
    try {
      const payload = buildSchedulePayload();
      const saved = await saveDreamingSchedule(payload);
      setSchedule(saved);
      message.success(t("dreaming.thresholds.saved"));
    } catch {
      message.error(t("dreaming.thresholds.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleRunNow = async () => {
    setRunning(true);
    try {
      const queued = await runDreaming(schedule?.agent_id ?? "__user__");
      setLatestRun({
        run_id: queued.run_id,
        status: queued.status,
        light_count: 0,
        rem_count: 0,
        promoted_count: 0,
        deferred_count: 0,
      });
      message.success(t("dreaming.run.queued"));
    } catch {
      setRunning(false);
      message.error(t("dreaming.error.trigger"));
    }
  };

  const weekdayOptions = Array.from({ length: 7 }, (_, i) => ({
    value: i,
    label: t(`dreaming.schedule.weekday.${i}`),
  }));

  const frequencyOptions = [
    { value: "daily", label: t("dreaming.schedule.daily") },
    { value: "weekly", label: t("dreaming.schedule.weekly") },
    { value: "interval", label: t("dreaming.schedule.interval") },
  ];

  const runStatus = (() => {
    if (!latestRun) {
      return { status: "default" as const, text: t("dreaming.run.notRunYet") };
    }
    if (latestRun.status === "queued") {
      return { status: "processing" as const, text: t("dreaming.run.queued") };
    }
    if (latestRun.status === "running") {
      const phase = latestRun.current_phase
        ? t(`dreaming.phase.${latestRun.current_phase}`)
        : t("dreaming.run.inProgress");
      return {
        status: "processing" as const,
        text: t("dreaming.run.runningPhase", { phase }),
      };
    }
    if (latestRun.status === "completed") {
      return { status: "success" as const, text: t("dreaming.run.completed") };
    }
    if (latestRun.status === "failed") {
      return { status: "error" as const, text: t("dreaming.run.failed") };
    }
    return { status: "warning" as const, text: t("dreaming.run.skipped") };
  })();
  const lastRunAt = latestRun?.finished_at ?? latestRun?.started_at;

  if (loading) {
    return <Card className="memory-config-card mt-6" loading />;
  }

  return (
    <Flex gap={24} className="mt-6" align="stretch">
      <Modal
        title={t("dreaming.advanced.title")}
        open={advancedOpen}
        onCancel={() => setAdvancedOpen(false)}
        footer={null}
        width={640}
      >
        <Text type="secondary" className="block mb-5">
          {t("dreaming.advanced.description")}
        </Text>
        <div className="grid grid-cols-1 gap-y-5">
          <div>
            <Text strong>{t("dreaming.thresholds.minScore")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={INPUT_RANGES.minScore.min}
              max={INPUT_RANGES.minScore.max}
              step={0.01}
              value={minScore ?? DEFAULT_VALUES.min_score}
              onChange={(val) => setMinScore(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.minScoreHint", INPUT_RANGES.minScore)}
            </Text>
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.minScoreGuide")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.minRecallCount")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={INPUT_RANGES.minRecallCount.min}
              max={INPUT_RANGES.minRecallCount.max}
              step={1}
              value={minRecallCount ?? DEFAULT_VALUES.min_recall_count}
              onChange={(val) => setMinRecallCount(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t(
                "dreaming.thresholds.minRecallCountHint",
                INPUT_RANGES.minRecallCount
              )}
            </Text>
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.minRecallCountGuide")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.minUniqueQueries")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={INPUT_RANGES.minUniqueQueries.min}
              max={INPUT_RANGES.minUniqueQueries.max}
              step={1}
              value={minUniqueQueries ?? DEFAULT_VALUES.min_unique_queries}
              onChange={(val) => setMinUniqueQueries(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t(
                "dreaming.thresholds.minUniqueQueriesHint",
                INPUT_RANGES.minUniqueQueries
              )}
            </Text>
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.minUniqueQueriesGuide")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.sourceLimit")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={INPUT_RANGES.sourceLimit.min}
              max={INPUT_RANGES.sourceLimit.max}
              step={1}
              value={sourceLimit ?? DEFAULT_VALUES.source_limit}
              onChange={(val) => setSourceLimit(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t(
                "dreaming.thresholds.sourceLimitHint",
                INPUT_RANGES.sourceLimit
              )}
            </Text>
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.sourceLimitGuide")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.longTermMaxChars")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={INPUT_RANGES.longTermMaxChars.min}
              max={INPUT_RANGES.longTermMaxChars.max}
              step={100}
              value={longTermMaxChars ?? DEFAULT_VALUES.long_term_max_chars}
              onChange={(val) => setLongTermMaxChars(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t(
                "dreaming.thresholds.longTermMaxCharsHint",
                INPUT_RANGES.longTermMaxChars
              )}
            </Text>
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.longTermMaxCharsGuide")}
            </Text>
          </div>

          <div>
            <Text strong>
              {t("dreaming.thresholds.summarizationMaxAttempts")}
            </Text>
            <InputNumber
              style={{ width: "100%" }}
              min={INPUT_RANGES.summarizationMaxAttempts.min}
              max={INPUT_RANGES.summarizationMaxAttempts.max}
              step={1}
              value={
                summarizationMaxAttempts ??
                DEFAULT_VALUES.summarization_max_attempts
              }
              onChange={(val) => setSummarizationMaxAttempts(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t(
                "dreaming.thresholds.summarizationMaxAttemptsHint",
                INPUT_RANGES.summarizationMaxAttempts
              )}
            </Text>
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.summarizationMaxAttemptsGuide")}
            </Text>
          </div>
        </div>

        <div className="mt-6 flex justify-end">
          <Button
            type="primary"
            loading={saving}
            onClick={handleSaveThresholds}
          >
            {t("dreaming.thresholds.save")}
          </Button>
        </div>
      </Modal>

      <Card
        className="memory-config-card"
        style={{ flex: 1, width: "100%" }}
        styles={{ body: { paddingTop: 16, paddingBottom: 16 } }}
        title={t("dreaming.execution.title")}
      >
        <Flex vertical gap={12}>
          <Flex align="center" justify="space-between" gap={12} wrap="wrap">
            <Text type="secondary" style={{ flex: "1 1 480px" }}>
              {t("dreaming.alwaysOn.description")}
            </Text>
            <Flex gap={8} wrap="wrap">
              <Button onClick={() => setAdvancedOpen(true)}>
                {t("dreaming.advanced.open")}
              </Button>
              <Button type="primary" loading={running} onClick={handleRunNow}>
                {t("dreaming.run.executeNow")}
              </Button>
            </Flex>
          </Flex>

          <Flex
            align="center"
            justify="space-between"
            gap={12}
            className="rounded-md bg-gray-50 px-3 py-2"
          >
            <Text strong>{t("dreaming.schedule.enabled")}</Text>
            <Switch
              size="small"
              checked={enabled}
              onChange={(checked) => setEnabled(checked)}
            />
          </Flex>

          {enabled || schedule?.enabled ? (
            <>
              <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
                <div>
                  <Text strong className="block mb-1">
                    {t("dreaming.schedule.frequency")}
                  </Text>
                  <Select
                    style={{ width: "100%" }}
                    value={frequency}
                    onChange={(val) => setFrequency(val)}
                    options={frequencyOptions}
                  />
                </div>

                <div>
                  <Text strong className="block mb-1">
                    {frequency === "interval"
                      ? t("dreaming.schedule.hours")
                      : t("dreaming.schedule.executionTime")}
                  </Text>
                  {frequency === "interval" ? (
                    <InputNumber
                      style={{ width: "100%" }}
                      min={1}
                      max={168}
                      step={1}
                      value={intervalHours}
                      onChange={(val) => setIntervalHours(val ?? 6)}
                      addonAfter={t("dreaming.schedule.hours")}
                    />
                  ) : (
                    <Flex gap={8}>
                      {frequency === "weekly" && (
                        <Select
                          style={{ width: "100%" }}
                          value={weekday}
                          onChange={(val) => setWeekday(val)}
                          options={weekdayOptions}
                        />
                      )}
                      <TimePicker
                        style={{ width: "100%" }}
                        format="HH:mm"
                        value={time}
                        onChange={(val) => {
                          if (val) setTime(val);
                        }}
                        needConfirm={false}
                      />
                    </Flex>
                  )}
                </div>
                <Button loading={saving} onClick={handleSaveSchedule}>
                  {t("dreaming.schedule.save")}
                </Button>
              </div>

              <Text type="secondary" className="text-xs">
                {t("dreaming.schedule.nextFire", {
                  time: schedule?.next_fire_at
                    ? dayjs(schedule.next_fire_at).format("YYYY-MM-DD HH:mm")
                    : "--",
                })}
              </Text>
            </>
          ) : (
            <Text type="secondary" className="text-xs">
              {t("dreaming.schedule.disabledHint")}
            </Text>
          )}

          <Flex align="center" justify="space-between" gap={8} wrap="wrap">
            <Badge status={runStatus.status} text={runStatus.text} />
            <Text type="secondary" className="text-xs">
              {t("dreaming.schedule.lastFire", {
                time: lastRunAt
                  ? dayjs(lastRunAt).format("YYYY-MM-DD HH:mm")
                  : t("dreaming.schedule.neverRun"),
              })}
            </Text>
            {latestRun?.status === "failed" && latestRun.error && (
              <Text type="danger" className="w-full text-xs">
                {latestRun.error}
              </Text>
            )}
          </Flex>
        </Flex>
      </Card>
    </Flex>
  );
}
