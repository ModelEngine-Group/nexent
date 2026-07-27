"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  InputNumber,
  List,
  Progress,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  TimePicker,
  Timeline,
  Typography,
} from "antd";
import { Brain, Clock, History, Play, RotateCcw, Save } from "lucide-react";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import {
  activateDreamingVersion,
  DreamingAudit,
  DreamingVersion,
  fetchDreamingAgents,
  fetchDreamingAudits,
  fetchDreamingParameters,
  fetchDreamingSchedule,
  fetchDreamingVersions,
  runDreaming,
  saveDreamingSchedule,
} from "@/services/memoryService";
import type {
  DreamingParameters,
  DreamingSchedule,
} from "@/services/memoryService";
import { getTenantUsers, TenantUser } from "@/services/tenantService";

const phaseProgress: Record<string, number> = {
  light: 20,
  rem: 45,
  deep: 70,
  compression: 90,
};

export function DreamingPanel() {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const { user, hasPermission } = useAuthorizationContext();
  const [agents, setAgents] = useState<Array<{ value: string; label: string }>>(
    []
  );
  const [agentId, setAgentId] = useState<string>();
  const [tenantUsers, setTenantUsers] = useState<TenantUser[]>([]);
  const [targetUserId, setTargetUserId] = useState<string>();
  const [audits, setAudits] = useState<DreamingAudit[]>([]);
  const [versions, setVersions] = useState<DreamingVersion[]>([]);
  const [parameters, setParameters] = useState<DreamingParameters>();
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [schedule, setSchedule] = useState<DreamingSchedule>();
  const [scheduleMode, setScheduleMode] = useState<
    "daily" | "weekly" | "interval"
  >("daily");
  const [scheduleTime, setScheduleTime] = useState("03:00");
  const [scheduleWeekday, setScheduleWeekday] = useState(1);
  const [intervalHours, setIntervalHours] = useState(24);
  const [savingSchedule, setSavingSchedule] = useState(false);

  const refresh = useCallback(
    async (selectedAgent: string) => {
      const target =
        targetUserId && targetUserId !== user?.id ? targetUserId : undefined;
      const [nextAudits, nextVersions, nextSchedule] = await Promise.all([
        fetchDreamingAudits(selectedAgent, 20, target),
        fetchDreamingVersions(selectedAgent, 20, target),
        fetchDreamingSchedule(selectedAgent, target),
      ]);
      setAudits(nextAudits);
      setVersions(nextVersions);
      setSchedule(nextSchedule);
      if (nextSchedule.rule_type === "INTERVAL") {
        setScheduleMode("interval");
        setIntervalHours((nextSchedule.interval_seconds || 86400) / 3600);
      } else {
        const parts = (nextSchedule.cron_expr || "0 3 * * *").split(" ");
        setScheduleTime(
          `${parts[1].padStart(2, "0")}:${parts[0].padStart(2, "0")}`
        );
        if (parts[4] !== "*") {
          setScheduleMode("weekly");
          setScheduleWeekday(Number(parts[4]));
        } else {
          setScheduleMode("daily");
        }
      }
    },
    [targetUserId, user?.id]
  );

  useEffect(() => {
    if (user?.id && !targetUserId) setTargetUserId(user.id);
  }, [targetUserId, user?.id]);

  useEffect(() => {
    if (!user?.tenantId || !hasPermission("DREAMING:VIEW_TENANT")) {
      setTenantUsers([]);
      return;
    }
    getTenantUsers(user.tenantId)
      .then(({ users }) => setTenantUsers(users))
      .catch(() => message.error(t("dreaming.error.loadUsers")));
  }, [hasPermission, message, t, user?.tenantId]);

  useEffect(() => {
    Promise.all([fetchDreamingAgents(), fetchDreamingParameters()])
      .then(([options, effectiveParameters]) => {
        setAgents(options);
        setParameters(effectiveParameters);
        if (options.length) setAgentId(options[0].value);
      })
      .catch(() => message.error(t("dreaming.error.loadAgents")))
      .finally(() => setLoading(false));
  }, [message, t]);

  useEffect(() => {
    if (!agentId) return;
    setLoading(true);
    refresh(agentId)
      .catch(() => message.error(t("dreaming.error.loadStatus")))
      .finally(() => setLoading(false));
  }, [agentId, message, refresh, t]);

  const activeRun = useMemo(
    () => audits.find((run) => ["queued", "running"].includes(run.status)),
    [audits]
  );
  const latestRun = audits[0];
  const selectedIsSelf = !targetUserId || targetUserId === user?.id;
  const canEditTarget = selectedIsSelf || hasPermission("DREAMING:EDIT_TENANT");
  const queueDelayed =
    activeRun?.status === "queued" &&
    !!activeRun.started_at &&
    Date.now() - new Date(activeRun.started_at).getTime() > 60_000;
  useEffect(() => {
    if (!agentId || !activeRun) return;
    const timer = window.setInterval(() => refresh(agentId), 2000);
    return () => window.clearInterval(timer);
  }, [activeRun, agentId, refresh]);

  const trigger = async () => {
    if (!agentId) return;
    setTriggering(true);
    try {
      await runDreaming(agentId, selectedIsSelf ? undefined : targetUserId);
      message.success(t("dreaming.run.queued"));
      await refresh(agentId);
    } catch {
      message.error(t("dreaming.error.trigger"));
    } finally {
      setTriggering(false);
    }
  };

  const saveSchedule = async () => {
    if (!agentId || !schedule) return;
    const [hour, minute] = scheduleTime.split(":").map(Number);
    const timezone =
      Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
    setSavingSchedule(true);
    try {
      const saved = await saveDreamingSchedule({
        agent_id: agentId,
        enabled: schedule.enabled,
        rule_type: scheduleMode === "interval" ? "INTERVAL" : "CRON",
        timezone,
        start_at: new Date().toISOString(),
        cron_expr:
          scheduleMode === "interval"
            ? null
            : `${minute} ${hour} * * ${scheduleMode === "weekly" ? scheduleWeekday : "*"}`,
        interval_seconds:
          scheduleMode === "interval" ? Math.round(intervalHours * 3600) : null,
        ...(selectedIsSelf ? {} : { target_user_id: targetUserId }),
      });
      setSchedule(saved);
      message.success(t("dreaming.schedule.saved"));
    } catch {
      message.error(t("dreaming.schedule.saveFailed"));
    } finally {
      setSavingSchedule(false);
    }
  };

  const activate = async (version: DreamingVersion) => {
    if (!agentId) return;
    const activeVersion = versions.find((candidate) => candidate.is_active);
    if (!activeVersion) return;
    try {
      await activateDreamingVersion(
        agentId,
        version.version_id,
        activeVersion.version_id,
        selectedIsSelf ? undefined : targetUserId
      );
      message.success(
        t("dreaming.version.switched", { version: version.version_no })
      );
      await refresh(agentId);
    } catch {
      message.error(t("dreaming.error.activate"));
    }
  };

  if (loading && !agentId) return <Spin />;

  return (
    <div
      className="space-y-4 overflow-y-auto"
      style={{ maxHeight: "calc(100vh - 250px)" }}
    >
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>
              <Brain className="inline size-5 mr-2" />
              Dreaming
            </Typography.Title>
            <Typography.Text type="secondary">
              {t("dreaming.description")}
            </Typography.Text>
            <div className="mt-2">
              {parameters && (
                <Space wrap>
                  <Tag>
                    {t("dreaming.parameter.sourceLimit", {
                      count: parameters.source_limit,
                    })}
                  </Tag>
                  <Tag>
                    {t("dreaming.parameter.maxChars", {
                      count: parameters.long_term_max_chars,
                    })}
                  </Tag>
                  <Tag>
                    {t("dreaming.parameter.compressionRetries", {
                      count: parameters.compression_max_attempts,
                    })}
                  </Tag>
                </Space>
              )}
            </div>
          </div>
          <Space>
            {tenantUsers.length > 1 && (
              <Select
                aria-label={t("dreaming.user.placeholder")}
                style={{ minWidth: 220 }}
                options={tenantUsers.map((tenantUser) => ({
                  value: tenantUser.user_id,
                  label: tenantUser.user_email || tenantUser.user_id,
                }))}
                value={targetUserId}
                onChange={setTargetUserId}
                placeholder={t("dreaming.user.placeholder")}
              />
            )}
            <Select
              style={{ minWidth: 220 }}
              options={agents}
              value={agentId}
              onChange={setAgentId}
              placeholder={t("dreaming.agent.placeholder")}
            />
            <Button
              type="primary"
              icon={<Play className="size-4" />}
              loading={triggering}
              disabled={!agentId || !!activeRun || !canEditTarget}
              onClick={trigger}
            >
              {t("dreaming.run.manual")}
            </Button>
          </Space>
        </div>
      </Card>

      {agentId && schedule && (
        <Card
          title={
            <Space>
              <Clock className="size-4" />
              {t("dreaming.schedule.title")}
            </Space>
          }
          extra={
            <Button
              icon={<Save className="size-4" />}
              loading={savingSchedule}
              disabled={!canEditTarget}
              onClick={saveSchedule}
            >
              {t("dreaming.schedule.save")}
            </Button>
          }
        >
          <Space wrap size="large">
            <Space>
              <Typography.Text>
                {t("dreaming.schedule.enabled")}
              </Typography.Text>
              <Switch
                checked={schedule.enabled}
                disabled={!canEditTarget}
                onChange={(enabled) => setSchedule({ ...schedule, enabled })}
              />
            </Space>
            <Select
              aria-label={t("dreaming.schedule.frequency")}
              value={scheduleMode}
              disabled={!canEditTarget}
              style={{ width: 150 }}
              onChange={setScheduleMode}
              options={[
                { value: "daily", label: t("dreaming.schedule.daily") },
                { value: "weekly", label: t("dreaming.schedule.weekly") },
                { value: "interval", label: t("dreaming.schedule.interval") },
              ]}
            />
            {scheduleMode === "weekly" && (
              <Select
                value={scheduleWeekday}
                disabled={!canEditTarget}
                style={{ width: 130 }}
                onChange={setScheduleWeekday}
                options={[0, 1, 2, 3, 4, 5, 6].map((value) => ({
                  value,
                  label: t(`dreaming.schedule.weekday.${value}`),
                }))}
              />
            )}
            {scheduleMode !== "interval" ? (
              <TimePicker
                value={dayjs(`2000-01-01T${scheduleTime}:00`)}
                format="HH:mm"
                minuteStep={5}
                disabled={!canEditTarget}
                onChange={(value) =>
                  value && setScheduleTime(value.format("HH:mm"))
                }
              />
            ) : (
              <Space>
                <InputNumber
                  min={1}
                  max={720}
                  value={intervalHours}
                  disabled={!canEditTarget}
                  onChange={(value) => setIntervalHours(value || 1)}
                />
                <Typography.Text>
                  {t("dreaming.schedule.hours")}
                </Typography.Text>
              </Space>
            )}
          </Space>
          <div className="mt-3">
            <Typography.Text type="secondary">
              {schedule.next_fire_at
                ? t("dreaming.schedule.nextFire", {
                    time: new Date(schedule.next_fire_at).toLocaleString(),
                  })
                : t("dreaming.schedule.disabledHint")}
            </Typography.Text>
          </div>
        </Card>
      )}

      {activeRun && (
        <Alert
          type={queueDelayed ? "warning" : "info"}
          showIcon
          message={
            queueDelayed
              ? t("dreaming.run.queueDelayed")
              : t("dreaming.run.inProgress")
          }
          description={
            <div>
              {queueDelayed && (
                <div className="mb-2">
                  {t("dreaming.run.queueDelayedDescription")}
                </div>
              )}
              <div className="mb-2">
                {t("dreaming.run.currentPhase")}:{" "}
                {activeRun.current_phase
                  ? t(`dreaming.phase.${activeRun.current_phase}`, {
                      defaultValue: activeRun.current_phase,
                    })
                  : t("dreaming.phase.queued")}
              </div>
              <Progress
                percent={phaseProgress[activeRun.current_phase || ""] || 5}
                status="active"
              />
            </div>
          }
        />
      )}
      {!activeRun && latestRun?.status === "failed" && (
        <Alert
          type="error"
          showIcon
          message={t("dreaming.run.failed")}
          description={latestRun.error || t("dreaming.run.failedDescription")}
        />
      )}
      {!activeRun && latestRun?.status === "completed" && (
        <Alert
          type="success"
          showIcon
          message={t("dreaming.run.completed")}
          description={t("dreaming.run.completedDescription", {
            promoted: latestRun.promoted_count,
            deferred: latestRun.deferred_count,
          })}
        />
      )}
      {!activeRun && latestRun?.status === "skipped" && (
        <Alert
          type="warning"
          showIcon
          message={t("dreaming.run.skipped")}
          description={t("dreaming.run.skippedDescription")}
        />
      )}

      <Card title={t("dreaming.active.title")}>
        {versions.find((version) => version.is_active) ? (
          (() => {
            const active = versions.find((version) => version.is_active)!;
            return (
              <div>
                <Space className="mb-3">
                  <Tag color="green">Active V{active.version_no}</Tag>
                  <Tag>
                    {t("dreaming.characters", {
                      count: active.published_char_count,
                    })}
                  </Tag>
                  <Tag color={active.mechanical_truncation ? "orange" : "blue"}>
                    {active.compression_status}
                  </Tag>
                </Space>
                {active.mechanical_truncation && (
                  <Alert
                    className="mb-3"
                    type="warning"
                    showIcon
                    message={t("dreaming.fallback.title")}
                    description={t("dreaming.fallback.description", {
                      count: active.omitted_evidence_ids.length,
                    })}
                  />
                )}
                <Typography.Paragraph
                  className="whitespace-pre-wrap rounded-md bg-gray-50 p-4"
                  ellipsis={{
                    rows: 12,
                    expandable: true,
                    symbol: t("dreaming.expand"),
                  }}
                >
                  {active.published_content}
                </Typography.Paragraph>
              </div>
            );
          })()
        ) : (
          <Empty
            description={
              latestRun?.status === "completed" &&
              latestRun.promoted_count === 0
                ? t("dreaming.active.noEligible")
                : t("dreaming.active.empty")
            }
          />
        )}
      </Card>

      <Card title={t("dreaming.decisions.title")}>
        {latestRun?.result?.decisions?.length ? (
          <List
            dataSource={latestRun.result.decisions}
            renderItem={(decision) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Space>
                      <Tag
                        color={
                          decision.event === "SELECT" ? "green" : "default"
                        }
                      >
                        {t(`dreaming.decision.${decision.event.toLowerCase()}`)}
                      </Tag>
                      <span>
                        {t("dreaming.decision.memory", {
                          id: decision.memory_id,
                        })}
                      </span>
                      <Tag>
                        {t("dreaming.decision.score", {
                          score: decision.score.toFixed(3),
                        })}
                      </Tag>
                    </Space>
                  }
                  description={
                    <div>
                      <div>{decision.reason}</div>
                      <Typography.Text type="secondary">
                        {t("dreaming.decision.evidence", {
                          ids: (
                            decision.evidence_ids || [
                              String(decision.memory_id),
                            ]
                          ).join(", "),
                        })}
                      </Typography.Text>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty description={t("dreaming.decisions.empty")} />
        )}
      </Card>

      <Card
        title={
          <>
            <History className="inline size-4 mr-2" />
            {t("dreaming.history.title")}
          </>
        }
      >
        {versions.length ? (
          <Timeline
            items={versions.map((version) => ({
              color: version.is_active ? "green" : "gray",
              children: (
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <Space>
                      <strong>V{version.version_no}</strong>
                      {version.is_active && (
                        <Tag color="green">{t("dreaming.version.current")}</Tag>
                      )}
                      <Tag>{version.compression_status}</Tag>
                    </Space>
                    <div className="mt-1 text-xs text-gray-500">
                      {t("dreaming.version.lengths", {
                        raw: version.raw_char_count,
                        published: version.published_char_count,
                      })}
                    </div>
                  </div>
                  {!version.is_active && canEditTarget && (
                    <Button
                      size="small"
                      icon={<RotateCcw className="size-3" />}
                      onClick={() => activate(version)}
                    >
                      {t("dreaming.version.activate")}
                    </Button>
                  )}
                </div>
              ),
            }))}
          />
        ) : (
          <Empty description={t("dreaming.history.empty")} />
        )}
      </Card>
    </div>
  );
}
