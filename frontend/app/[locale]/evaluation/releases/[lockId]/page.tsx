// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Checkbox, Flex, Input, Typography } from "antd";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { evolutionService as api } from "@/services/evolutionService";

import ReleaseMonitoring from "./ReleaseMonitoring";

export default function ReleasePage() {
  const { t } = useTranslation("common");
  const { lockId } = useParams<{ lockId: string }>();
  const { user } = useAuthorizationContext();
  const lock = Number(lockId);
  const cache = useQueryClient();
  const [reason, setReason] = useState("");
  const [emergency, setEmergency] = useState(false);
  const report = useQuery({
    queryKey: ["evolution-release", user?.tenantId, user?.id, lock],
    queryFn: () => api.release(lock),
    enabled: !!user && Number.isSafeInteger(lock) && lock > 0,
    retry: false,
  });
  const data = report.error ? undefined : report.data;
  const action = useMutation({
    mutationFn: async () => {
      if (!data || !reason.trim()) return;
      if (data.release)
        await api.rollback(
          lock,
          data.release.new_version,
          reason.trim(),
          emergency
        );
      else
        await api.promote(
          lock,
          data.base_version,
          data.candidate_digest,
          reason.trim()
        );
    },
    onSettled: () => report.refetch(),
    onSuccess: () => {
      void cache.invalidateQueries({queryKey:["release-monitoring",user?.tenantId,user?.id,lock]});
      setReason("");
      setEmergency(false);
    },
  });
  const error = action.error || report.error;
  const release = data?.release;
  const supported = data?.supported_type;
  const canAct =
    data &&
    (release
      ? (!release.rollback_at &&
          data.current_version === release.new_version) ||
        (!release.disabled && emergency)
      : data.summary?.decision === "passed" &&
        data.current_version === data.base_version &&
        supported);
  return (
    <main className="mx-auto max-w-3xl p-6">
      <Card title={t("evolution.release.open")} loading={report.isLoading}>
        <Flex vertical gap={14}>
          {error instanceof Error && (
            <Alert type="error" showIcon message={error.message} />
          )}
          {data && (
            <>
              <Typography.Text>
                {t("evolution.release.scope", {
                  agent: data.agent_id,
                  experiment: data.experiment_id,
                  base: data.base_version,
                  current: data.current_version,
                })}
              </Typography.Text>
              {data.script_build && <Typography.Paragraph>
                {data.script_build.name} · <code>{data.script_build.path}</code> · <code>{data.script_build.function}</code>
                <br/>{t("evolution.verifiedImage")} <code>{data.script_build.image}</code>
              </Typography.Paragraph>}
              {data.tool_build && <Typography.Paragraph>
                {t("evolution.kind.tool_build")} · {data.tool_build.tool}
                <br/><del><code>{data.tool_build.base.image}</code></del>
                <br/><ins><code>{data.tool_build.result.image}</code></ins>
              </Typography.Paragraph>}
              {data.tool_mapping && <Typography.Text>
                {data.tool_mapping.tool}.{data.tool_mapping.field} · {t(`evolution.mapping.${data.tool_mapping.proposed[data.tool_mapping.field].kind}`)}
              </Typography.Text>}
              {!!data.components?.length && (
                <ul aria-label={t("evolution.chooseComponents")}>
                  {data.components.map(part => (
                    <li key={part.experiment_id}>
                      {t("evolution.release.component", {
                        kind: t(`evolution.kind.${part.candidate_type}`),
                        candidate: part.candidate_id, experiment: part.experiment_id,
                      })}
                    </li>
                  ))}
                </ul>
              )}
              {data.skill_description && (
                <section>
                  <Typography.Text strong>{data.skill_description.name}</Typography.Text>
                  <dl>
                    <dt>{t("evolution.release.previousDescription")}</dt>
                    <dd>{data.skill_description.previous}</dd>
                    <dt>{t("evolution.release.proposedDescription")}</dt>
                    <dd>{data.skill_description.proposed}</dd>
                  </dl>
                </section>
              )}
              {data.added_guide && <Typography.Text>
                {t("evolution.release.addedGuide", {name:data.added_guide.name, digest:data.added_guide.digest.slice(0,12)})}
              </Typography.Text>}
              {!!data.excluded_tools?.length && (
                <Typography.Text>
                  {t("evolution.release.excludedTools", {
                    names: data.excluded_tools.join(", "),
                  })}
                </Typography.Text>
              )}
              {data.summary && (
                <Typography.Text>
                  {t(`evolution.confirmation.${data.summary.decision}`)} ·{" "}
                  {t("evolution.confirmation.pairs", {
                    valid: data.summary.valid_pairs,
                    total: data.summary.total_pairs,
                    regressed: data.summary.regressed,
                  })}
                </Typography.Text>
              )}
              {release && (
                <Typography.Text>
                  {t(
                    release.disabled
                      ? "evolution.release.stopped"
                      : release.rollback_at
                        ? "evolution.release.restored"
                        : "evolution.release.published",
                    { version: release.new_version }
                  )}
                </Typography.Text>
              )}
              {release && user && <ReleaseMonitoring lock={lock} tenant={user.tenantId} viewer={user.id}/>}
              {!release && !supported && (
                <Alert
                  type="info"
                  message={t("evolution.release.unsupported")}
                />
              )}
              {data.paused && (
                <Alert
                  type="warning"
                  showIcon
                  message={t("evolution.release.paused")}
                />
              )}
              {release && !release.disabled && (
                <Checkbox
                  checked={emergency}
                  onChange={(e) => setEmergency(e.target.checked)}
                >
                  {t("evolution.release.emergency")}
                </Checkbox>
              )}
              <Input.TextArea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={1200}
                aria-label={t("evolution.release.reason")}
                placeholder={t("evolution.release.reason")}
              />
              <Button
                type="primary"
                danger={!!release}
                loading={action.isPending}
                disabled={!canAct || !reason.trim() || report.isFetching}
                onClick={() => action.mutate()}
              >
                {t(
                  release
                    ? emergency
                      ? "evolution.release.stop"
                      : "evolution.release.rollback"
                    : "evolution.release.publish"
                )}
              </Button>
            </>
          )}
        </Flex>
      </Card>
    </main>
  );
}
