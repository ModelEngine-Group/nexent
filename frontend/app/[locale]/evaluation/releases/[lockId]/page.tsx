// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Checkbox, Flex, Input, Typography } from "antd";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { evolutionService as api } from "@/services/evolutionService";

export default function ReleasePage() {
  const { t } = useTranslation("common");
  const { lockId } = useParams<{ lockId: string }>();
  const { user } = useAuthorizationContext();
  const lock = Number(lockId);
  const [reason, setReason] = useState("");
  const [emergency, setEmergency] = useState(false);
  const report = useQuery({
    queryKey: ["evolution-release", user?.tenantId, user?.id, lock],
    queryFn: () => api.release(lock),
    enabled: !!user && Number.isSafeInteger(lock) && lock > 0,
    retry: false,
  });
  const data = report.data;
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
      setReason("");
      setEmergency(false);
    },
  });
  const error = action.error || report.error;
  const release = data?.release;
  const supported =
    data && ["prompt", "skill_step", "tool_set"].includes(data.candidate_type);
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
