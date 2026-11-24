// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Button, Flex, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { ReviewBatch } from "@/types/evolutionReview";

interface ReviewBatchResultsProps {
  batches: ReviewBatch[];
  refreshing: boolean;
  refresh: () => void;
  onDraft: (turn: number, previous: boolean) => void;
}

export default function ReviewBatchResults({ batches, refreshing, refresh, onDraft }: ReviewBatchResultsProps) {
  const { t } = useTranslation("common");

  return (
    <details>
      <summary>{t("evolution.recentReviewBatches")}</summary>
      <Button onClick={refresh} loading={refreshing}>{t("evolution.refreshReviewBatches")}</Button>
      {batches.map((batch) => {
        const title = <Typography.Text strong>{t("evolution.batchNumber", { id: batch.batch_id })}</Typography.Text>;
        if (batch.state === "pending") {
          return <div key={batch.batch_id}>{title} · {t("evolution.batchProcessing")}</div>;
        }
        const draftTurns = new Map(batch.draft_turns.map((turn) => [turn.turn_id, turn.use_previous_task]));
        const turnLinks = (ids: number[]) => (
          <Flex wrap align="center" gap={8}>
            {ids.map((id) => {
              const previous = draftTurns.get(id);
              if (previous === undefined) return <Typography.Text key={id}>#{id}</Typography.Text>;
              return <Button key={id} type="link" onClick={() => onDraft(id, previous)}>
                {t("evolution.makeBatchCase", { id })}
              </Button>;
            })}
          </Flex>
        );
        return (
          <Flex key={batch.batch_id} vertical gap={4}>
            <div>{title} · {t("evolution.batchCoverage", { reviewed: batch.reviewed, excluded: batch.excluded, missing: batch.missing })}</div>
            {batch.findings.map((finding) => (
              <div key={`${finding.direction}-${finding.reason}`}>
                {t(`evolution.diagnosis.${finding.reason}`)} · {t("evolution.batchFindingCount", { count: finding.turn_ids.length })}
                {turnLinks(finding.turn_ids)}
              </div>
            ))}
            {batch.reference_workflows.map((workflow) => (
              <div key={JSON.stringify(workflow.tools)}>
                {t("evolution.batchReferenceWorkflow", { tools: workflow.tools.join(" → ") })}
                {turnLinks(workflow.turn_ids)}
              </div>
            ))}
            {!batch.findings.length && !batch.reference_workflows.length && (
              <Typography.Text type="secondary">{t("evolution.batchNoFindings")}</Typography.Text>
            )}
          </Flex>
        );
      })}
    </details>
  );
}
