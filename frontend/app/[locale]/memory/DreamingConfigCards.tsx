"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Flex,
  InputNumber,
  Select,
  Switch,
  TimePicker,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";

import {
  fetchDreamingSchedule,
  saveDreamingSchedule,
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
  compression_max_attempts: 2,
} as const;

function parseCronExpr(
  cronExpr: string | null | undefined
): { hour: number; minute: number; weekday: number | null } | null {
  if (!cronExpr) return null;
  const parts = cronExpr.trim().split(/\s+/);
  if (parts.length < 5) return null;
  const minute = parseInt(parts[0], 10);
  const hour = parseInt(parts[1], 10);
  const dow = parts[4];
  if (isNaN(minute) || isNaN(hour)) return null;
  const weekday = dow === "*" ? null : parseInt(dow, 10);
  return { hour, minute, weekday: isNaN(weekday as number) ? null : weekday };
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
  const [compressionMaxAttempts, setCompressionMaxAttempts] = useState<
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
        setCompressionMaxAttempts(data.compression_max_attempts ?? null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

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
      timezone: base.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
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
      compression_max_attempts: compressionMaxAttempts,
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
    compressionMaxAttempts,
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

  const weekdayOptions = Array.from({ length: 7 }, (_, i) => ({
    value: i,
    label: t(`dreaming.schedule.weekday.${i}`),
  }));

  const frequencyOptions = [
    { value: "daily", label: t("dreaming.schedule.daily") },
    { value: "weekly", label: t("dreaming.schedule.weekly") },
    { value: "interval", label: t("dreaming.schedule.interval") },
  ];

  if (loading) {
    return (
      <Flex gap={24} className="mt-6">
        <Card className="memory-config-card" style={{ flex: 2 }} loading />
        <Card className="memory-config-card" style={{ flex: 1 }} loading />
      </Flex>
    );
  }

  return (
    <Flex gap={24} className="mt-6" align="stretch">
      <Card
        className="memory-config-card"
        style={{ flex: 2 }}
        title={t("dreaming.thresholds.title")}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
          <div>
            <Text strong>{t("dreaming.thresholds.minScore")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={0}
              max={1}
              step={0.01}
              value={minScore ?? DEFAULT_VALUES.min_score}
              onChange={(val) => setMinScore(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.minScoreHint")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.minRecallCount")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={0}
              max={100}
              step={1}
              value={minRecallCount ?? DEFAULT_VALUES.min_recall_count}
              onChange={(val) => setMinRecallCount(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.minRecallCountHint")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.minUniqueQueries")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={0}
              max={50}
              step={1}
              value={minUniqueQueries ?? DEFAULT_VALUES.min_unique_queries}
              onChange={(val) => setMinUniqueQueries(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.minUniqueQueriesHint")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.sourceLimit")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={1}
              max={100}
              step={1}
              value={sourceLimit ?? DEFAULT_VALUES.source_limit}
              onChange={(val) => setSourceLimit(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.sourceLimitHint")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.longTermMaxChars")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={100}
              max={1000000}
              step={100}
              value={longTermMaxChars ?? DEFAULT_VALUES.long_term_max_chars}
              onChange={(val) => setLongTermMaxChars(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.longTermMaxCharsHint")}
            </Text>
          </div>

          <div>
            <Text strong>{t("dreaming.thresholds.compressionMaxAttempts")}</Text>
            <InputNumber
              style={{ width: "100%" }}
              min={0}
              max={10}
              step={1}
              value={compressionMaxAttempts ?? DEFAULT_VALUES.compression_max_attempts}
              onChange={(val) => setCompressionMaxAttempts(val)}
              className="mt-1"
            />
            <Text type="secondary" className="block mt-1 text-xs">
              {t("dreaming.thresholds.compressionMaxAttemptsHint")}
            </Text>
          </div>
        </div>

        <div className="mt-6">
          <Button
            type="primary"
            loading={saving}
            onClick={handleSaveThresholds}
          >
            {t("dreaming.thresholds.save")}
          </Button>
        </div>
      </Card>

      <Card
        className="memory-config-card"
        style={{ flex: 1 }}
        title={t("dreaming.schedule.title")}
      >
        <Flex vertical gap={16}>
          <Flex align="center" justify="space-between">
            <Text strong>{t("dreaming.schedule.enabled")}</Text>
            <Switch
              checked={enabled}
              onChange={(checked) => setEnabled(checked)}
            />
          </Flex>

          {enabled ? (
            <>
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

              {frequency === "interval" ? (
                <div>
                  <Text strong className="block mb-1">
                    {t("dreaming.schedule.hours")}
                  </Text>
                  <InputNumber
                    style={{ width: "100%" }}
                    min={1}
                    max={168}
                    step={1}
                    value={intervalHours}
                    onChange={(val) => setIntervalHours(val ?? 6)}
                    addonAfter={t("dreaming.schedule.hours")}
                  />
                </div>
              ) : (
                <>
                  {frequency === "weekly" && (
                    <div>
                      <Select
                        style={{ width: "100%" }}
                        value={weekday}
                        onChange={(val) => setWeekday(val)}
                        options={weekdayOptions}
                      />
                    </div>
                  )}
                  <div>
                    <TimePicker
                      style={{ width: "100%" }}
                      format="HH:mm"
                      value={time}
                      onChange={(val) => {
                        if (val) setTime(val);
                      }}
                      needConfirm={false}
                    />
                  </div>
                </>
              )}

              <Button
                type="primary"
                loading={saving}
                onClick={handleSaveSchedule}
              >
                {t("dreaming.schedule.save")}
              </Button>

              {schedule?.next_fire_at && (
                <Text type="secondary" className="text-xs">
                  {t("dreaming.schedule.nextFire", {
                    time: dayjs(schedule.next_fire_at).format(
                      "YYYY-MM-DD HH:mm"
                    ),
                  })}
                </Text>
              )}
            </>
          ) : (
            <Text type="secondary">{t("dreaming.schedule.disabledHint")}</Text>
          )}
        </Flex>
      </Card>
    </Flex>
  );
}
