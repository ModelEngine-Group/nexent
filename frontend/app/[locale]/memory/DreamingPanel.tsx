"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Timeline,
  Tooltip,
  Typography,
} from "antd";
import { Brain, Loader2, Play, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { getAuthHeaders } from "@/lib/auth";
import {
  activateDreamingVersion,
  clearActiveDreamingVersion,
  undoClearActiveDreamingVersion,
  DreamingAudit,
  DreamingVersion,
  fetchDreamingAudits,
  fetchDreamingVersions,
  runDreaming,
} from "@/services/memoryService";

const phases = ["light", "rem", "deep", "compression"] as const;
export function DreamingPanel() {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const phaseLabels: Record<string, string> = {
    light: t("dreaming.phase.light.label"),
    rem: t("dreaming.phase.rem.label"),
    deep: t("dreaming.phase.deep.label"),
    compression: t("dreaming.phase.compression.label"),
  };
  const { user, hasPermission } = useAuthorizationContext();
  const agentId = "__user__";
  const [targetUserId, setTargetUserId] = useState<string>();
  const [audits, setAudits] = useState<DreamingAudit[]>([]);
  const [versions, setVersions] = useState<DreamingVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearedVersionId, setClearedVersionId] = useState<number | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
  const [memoryContents, setMemoryContents] = useState<Record<number, string>>(
    {}
  );

  const refresh = useCallback(async () => {
    const target =
      targetUserId && targetUserId !== user?.id ? targetUserId : undefined;
    const [nextAudits, nextVersions] = await Promise.all([
      fetchDreamingAudits(20, target),
      fetchDreamingVersions(20, target),
    ]);
    setAudits(nextAudits);
    setVersions(nextVersions);
  }, [targetUserId, user?.id]);

  useEffect(() => {
    if (user?.id && !targetUserId) setTargetUserId(user.id);
  }, [targetUserId, user?.id]);

  useEffect(() => {
    if (!agentId) return;
    setLoading(true);
    refresh()
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
    Date.now() - new Date(activeRun.started_at + "Z").getTime() > 60_000;
  useEffect(() => {
    if (!activeRun) return;
    const timer = window.setInterval(() => refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [activeRun, agentId, refresh]);

  useEffect(() => {
    const decisions = latestRun?.result?.decisions;
    if (!decisions?.length) return;
    const missingIds = decisions
      .map((d) => d.memory_id)
      .filter((id) => !(id in memoryContents));
    if (!missingIds.length) return;
    Promise.all(
      missingIds.map(async (id) => {
        try {
          const resp = await fetch(`/api/memory/records/${id}`, {
            headers: getAuthHeaders(),
          });
          if (resp.ok) {
            const data = await resp.json();
            return { id, content: data.content || "" };
          }
        } catch {
          // ignore
        }
        return { id, content: "" };
      })
    ).then((results) => {
      const updates: Record<number, string> = {};
      results.forEach(({ id, content }) => {
        updates[id] = content;
      });
      setMemoryContents((prev) => ({ ...prev, ...updates }));
    });
  }, [latestRun?.result?.decisions]);

  const trigger = async () => {
    if (!agentId) return;
    setTriggering(true);
    try {
      await runDreaming(agentId, selectedIsSelf ? undefined : targetUserId);
      message.success(t("dreaming.run.queued"));
      await refresh();
    } catch {
      message.error(t("dreaming.error.trigger"));
    } finally {
      setTriggering(false);
    }
  };

  const activate = async (version: DreamingVersion) => {
    if (!agentId) return;
    const activeVersion = versions.find((candidate) => candidate.is_active);
    try {
      await activateDreamingVersion(
        agentId,
        version.version_id,
        activeVersion?.version_id,
        selectedIsSelf ? undefined : targetUserId
      );
      message.success(
        t("dreaming.version.switched", { version: version.version_no })
      );
      await refresh();
    } catch {
      message.error(t("dreaming.error.activate"));
    }
  };

  const clearActiveVersion = async () => {
    Modal.confirm({
      title: t("dreaming.active.clearConfirmTitle"),
      content: t("dreaming.active.clearConfirmContent"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          setClearing(true);
          const result = await clearActiveDreamingVersion(
            selectedIsSelf ? undefined : targetUserId
          );
          if (result.success && result.deactivated_version_id) {
            setClearedVersionId(result.deactivated_version_id);
          }
          message.success(t("dreaming.active.cleared"));
          await refresh();
        } catch {
          message.error(t("dreaming.error.clear"));
        } finally {
          setClearing(false);
        }
      },
    });
  };

  const undoClear = async () => {
    if (clearedVersionId === null) return;
    try {
      setClearing(true);
      await undoClearActiveDreamingVersion(
        clearedVersionId,
        selectedIsSelf ? undefined : targetUserId
      );
      setClearedVersionId(null);
      message.success(t("dreaming.active.undoSuccess"));
      await refresh();
    } catch {
      message.error(t("dreaming.error.undoClear"));
    } finally {
      setClearing(false);
    }
  };

  useEffect(() => {
    if (clearedVersionId === null) return;
    const timer = setTimeout(() => {
      setClearedVersionId(null);
    }, 30000);
    return () => clearTimeout(timer);
  }, [clearedVersionId]);

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
              {t("dreaming.title")}
            </Typography.Title>
            <Typography.Text type="secondary">
              {t("dreaming.description")}
            </Typography.Text>
          </div>
          <div className="flex flex-col items-end gap-2">
            <Button
              type="primary"
              icon={<Play className="size-4" />}
              loading={triggering}
              disabled={!agentId || !!activeRun || !canEditTarget}
              onClick={trigger}
            >
              {t("dreaming.run.manual")}
            </Button>
            {activeRun && (
              <div className="flex items-center gap-1.5 text-xs">
                <Loader2 className="size-3.5 animate-spin text-gray-500 shrink-0" />
                <div className="flex items-center gap-0">
                  {phases.map((phase, i) => {
                    const currentIdx = activeRun.current_phase
                      ? phases.indexOf(
                          activeRun.current_phase as (typeof phases)[number]
                        )
                      : -1;
                    const isCompleted = currentIdx >= 0 && i < currentIdx;
                    const isCurrent = currentIdx >= 0 && i === currentIdx;
                    return (
                      <React.Fragment key={phase}>
                        {i > 0 && (
                          <span
                            className={`mx-1 ${
                              currentIdx >= 0 && i <= currentIdx
                                ? "text-green-500"
                                : "text-gray-300"
                            }`}
                          >
                            –
                          </span>
                        )}
                        <span
                          className={
                            isCompleted
                              ? "text-green-600"
                              : isCurrent
                                ? "text-gray-900 font-semibold"
                                : "text-gray-400"
                          }
                        >
                          {phaseLabels[phase]}
                        </span>
                      </React.Fragment>
                    );
                  })}
                </div>
                {queueDelayed && (
                  <span className="text-orange-500 ml-1 shrink-0">
                    ({t("dreaming.run.queueDelayed")})
                  </span>
                )}
              </div>
            )}
            {!activeRun && latestRun?.status === "completed" && (
              <div className="text-xs text-green-600">
                ✓ {t("dreaming.run.completed")} —{" "}
                {t("dreaming.run.completedDescription", {
                  promoted: latestRun.promoted_count,
                  deferred: latestRun.deferred_count,
                })}
              </div>
            )}
            {!activeRun && latestRun?.status === "failed" && (
              <div className="text-xs text-red-500">
                ✗ {t("dreaming.run.failed")} —{" "}
                {latestRun.error || t("dreaming.run.failedDescription")}
              </div>
            )}
            {!activeRun && latestRun?.status === "skipped" && (
              <div className="text-xs text-orange-500">
                ⚠ {t("dreaming.run.skipped")}
              </div>
            )}
          </div>
        </div>
      </Card>

      <Card title={t("dreaming.active.title")}>
        {versions.find((version) => version.is_active) ? (
          (() => {
            const active = versions.find((version) => version.is_active)!;
            return (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <Space>
                    <Tag color="green">
                      {t("dreaming.active.versionPrefix", {
                        version: active.version_no,
                      })}
                    </Tag>
                    <Tag>
                      {t("dreaming.characters", {
                        count: active.published_char_count,
                      })}
                    </Tag>
                    <Tag color={active.mechanical_truncation ? "orange" : "blue"}>
                      {t(`dreaming.compression.${active.compression_status}`)}
                    </Tag>
                    {versions.length > 1 && (
                      <Select
                        size="small"
                        style={{ width: 200 }}
                        value={active.version_id}
                        onChange={(versionId) => {
                          const version = versions.find(
                            (v) => v.version_id === versionId
                          );
                          if (version && !version.is_active) {
                            activate(version);
                          }
                        }}
                        options={versions.map((v) => ({
                          value: v.version_id,
                          label: `V${v.version_no}${v.is_active ? ` (${t("dreaming.version.current")})` : ""}`,
                        }))}
                      />
                    )}
                  </Space>
                  {canEditTarget && (
                    <Space>
                      <Button
                        size="small"
                        danger
                        icon={<Trash2 className="size-3" />}
                        loading={clearing}
                        onClick={clearActiveVersion}
                      >
                        {t("dreaming.active.clear")}
                      </Button>
                      {clearedVersionId !== null && (
                        <Button
                          size="small"
                          loading={clearing}
                          onClick={undoClear}
                        >
                          {t("dreaming.active.undo")}
                        </Button>
                      )}
                    </Space>
                  )}
                </div>
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
                    expandable: "collapsible" as const,
                    symbol: (expanded: boolean) =>
                      expanded ? t("dreaming.collapse") : t("dreaming.expand"),
                  }}
                >
                  {active.published_content}
                </Typography.Paragraph>
              </div>
            );
          })()
        ) : (
          <div>
            {clearedVersionId !== null &&
            versions.find((v) => v.version_id === clearedVersionId) ? (
              (() => {
                const cleared = versions.find(
                  (v) => v.version_id === clearedVersionId
                )!;
                return (
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <Space>
                        <Tag color="default">
                          {t("dreaming.active.versionPrefixCleared", {
                            version: cleared.version_no,
                          })}
                        </Tag>
                        <Tag>
                          {t("dreaming.characters", { count: 0 })}
                        </Tag>
                        <Tag color="blue">
                          {t("dreaming.compression.not_needed")}
                        </Tag>
                        {versions.length > 1 && (
                          <Select
                            size="small"
                            style={{ width: 200 }}
                            value={cleared.version_id}
                            onChange={(versionId) => {
                              const version = versions.find(
                                (v) => v.version_id === versionId
                              );
                              if (version && !version.is_active) {
                                activate(version);
                              }
                            }}
                            options={versions.map((v) => ({
                              value: v.version_id,
                              label: `V${v.version_no}${v.version_id === cleared.version_id ? ` (${t("dreaming.version.current")})` : ""}`,
                            }))}
                          />
                        )}
                      </Space>
                      {canEditTarget && (
                        <Button
                          size="small"
                          loading={clearing}
                          onClick={undoClear}
                        >
                          {t("dreaming.active.undo")}
                        </Button>
                      )}
                    </div>
                    <Typography.Paragraph className="whitespace-pre-wrap rounded-md bg-gray-50 p-4 text-gray-400 italic">
                      {t("dreaming.active.clearedContent")}
                    </Typography.Paragraph>
                  </div>
                );
              })()
            ) : (
              <div>
                {versions.length > 0 ? (
                  (() => {
                    const selected = versions.find(
                      (v) => v.version_id === (selectedVersionId ?? versions[0].version_id)
                    ) ?? versions[0];
                    return (
                      <div>
                        <div className="flex items-center justify-between mb-3">
                          <Space>
                            <Tag color="default">
                              V{selected.version_no}
                            </Tag>
                            <Tag>
                              {t("dreaming.characters", {
                                count: selected.published_char_count,
                              })}
                            </Tag>
                            <Tag color={selected.mechanical_truncation ? "orange" : "blue"}>
                              {t(`dreaming.compression.${selected.compression_status}`)}
                            </Tag>
                            {versions.length > 1 && (
                              <Select
                                size="small"
                                style={{ width: 200 }}
                                value={selected.version_id}
                                onChange={(versionId) => {
                                  setSelectedVersionId(versionId);
                                }}
                                options={versions.map((v) => ({
                                  value: v.version_id,
                                  label: `V${v.version_no} (${t("dreaming.characters", { count: v.published_char_count })})`,
                                }))}
                              />
                            )}
                          </Space>
                          {canEditTarget && (
                            <Button
                              size="small"
                              type="primary"
                              loading={clearing}
                              onClick={() => activate(selected)}
                            >
                              {t("dreaming.version.activate")}
                            </Button>
                          )}
                        </div>
                        {selected.mechanical_truncation && (
                          <Alert
                            className="mb-3"
                            type="warning"
                            showIcon
                            message={t("dreaming.fallback.title")}
                            description={t("dreaming.fallback.description", {
                              count: selected.omitted_evidence_ids.length,
                            })}
                          />
                        )}
                        <Typography.Paragraph
                          className="whitespace-pre-wrap rounded-md bg-gray-50 p-4"
                          ellipsis={{
                            rows: 12,
                            expandable: "collapsible" as const,
                            symbol: (expanded: boolean) =>
                              expanded ? t("dreaming.collapse") : t("dreaming.expand"),
                          }}
                        >
                          {selected.published_content}
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
              </div>
            )}
          </div>
        )}
      </Card>

      <Card title={t("dreaming.decisions.title")}>
        {latestRun?.result?.decisions?.length ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {latestRun.result.decisions.map((decision) => (
              <Tooltip
                key={decision.memory_id}
                title={
                  <div className="max-w-md">
                    <div className="font-medium mb-1">
                      {t("dreaming.decision.memory", {
                        id: decision.memory_id,
                      })}
                    </div>
                    <div className="text-xs opacity-80">
                      {memoryContents[decision.memory_id] || decision.reason}
                    </div>
                  </div>
                }
                placement="top"
                mouseEnterDelay={0.5}
              >
                <div
                  className={`rounded-lg border p-3 transition-all hover:shadow-md cursor-default ${
                    decision.event === "SELECT"
                      ? "border-green-200 bg-green-50 hover:border-green-300"
                      : "border-gray-200 bg-gray-50 hover:border-gray-300"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <Tag
                      color={decision.event === "SELECT" ? "green" : "default"}
                      style={{ margin: 0 }}
                    >
                      {t(`dreaming.decision.${decision.event.toLowerCase()}`)}
                    </Tag>
                    <Typography.Text type="secondary" className="text-xs">
                      #{decision.memory_id}
                    </Typography.Text>
                  </div>
                  <div className="flex gap-2 text-xs mb-1">
                    <span
                      className={
                        decision.noise ? "text-red-500" : "text-gray-500"
                      }
                    >
                      {t("dreaming.decision.noise")}{" "}
                      {decision.noise
                        ? t("dreaming.decision.noiseYes")
                        : t("dreaming.decision.noiseNo")}
                    </span>
                    <span className="text-gray-500">
                      {t("dreaming.decision.scoreLabel")}{" "}
                      {decision.score.toFixed(2)}
                    </span>
                    <span className="text-gray-500">
                      {t("dreaming.decision.recallLabel")}{" "}
                      {decision.signal_count}
                    </span>
                  </div>
                  <Typography.Paragraph
                    type="secondary"
                    className="text-xs mb-0"
                    ellipsis={{ rows: 2 }}
                    style={{ marginBottom: 0 }}
                  >
                    {memoryContents[decision.memory_id] ||
                      t("dreaming.decision.noContent")}
                  </Typography.Paragraph>
                </div>
              </Tooltip>
            ))}
          </div>
        ) : (
          <Empty description={t("dreaming.decisions.empty")} />
        )}
      </Card>
    </div>
  );
}
