"use client";

import { useEffect, useState } from "react";
import { Alert, App, Button, Select, Table, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { evaluationService } from "@/services/evaluationService";
import type {
  AgentEvaluationCase,
  EvaluationHistoryItem,
} from "@/types/agentEvaluation";

interface Props {
  run: EvaluationHistoryItem;
  onUpdated: () => Promise<void>;
}

export default function EvaluationCaseTable({ run, onUpdated }: Props) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [rows, setRows] = useState<AgentEvaluationCase[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  const [saving, setSaving] = useState<number | null>(null);
  const terminal = run.status === "COMPLETED" || run.status === "FAILED";

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    evaluationService
      .listAgentEvaluationCases(run.agent_evaluation_id, {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      .then((data) => {
        if (active) setRows(data);
      })
      .catch(() => {
        if (active) {
          setRows([]);
          setError(true);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    run.agent_evaluation_id,
    run.status,
    run.progress_done,
    page,
    pageSize,
    revision,
  ]);

  const revise = async (row: AgentEvaluationCase, value: "pass" | "fail") => {
    setSaving(row.agent_evaluation_case_id);
    try {
      await evaluationService.reviseAgentEvaluationCase(
        run.agent_evaluation_id,
        row.agent_evaluation_case_id,
        value
      );
      setRows((current) =>
        current.map((item) =>
          item.agent_evaluation_case_id === row.agent_evaluation_case_id
            ? { ...item, pass_status: value, score: value === "pass" ? 1 : 0 }
            : item
        )
      );
      message.success(t("agentEvaluation.cases.saved"));
      await onUpdated();
    } catch (err) {
      message.error(
        err instanceof Error
          ? err.message
          : t("agentEvaluation.cases.saveFailed")
      );
    } finally {
      setSaving(null);
    }
  };
  const detail = (value?: string | null) => (
    <div className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
      {value || "—"}
    </div>
  );

  return (
    <div className="mt-5 min-w-0">
      <Typography.Title level={5}>
        {t("agentEvaluation.cases.title")}
      </Typography.Title>
      {error && (
        <Alert
          type="error"
          title={t("agentEvaluation.cases.loadFailed")}
          action={
            <Button size="small" onClick={() => setRevision((n) => n + 1)}>
              {t("agentEvaluation.cases.retry")}
            </Button>
          }
        />
      )}
      <Table<AgentEvaluationCase>
        rowKey="agent_evaluation_case_id"
        size="small"
        loading={loading}
        dataSource={rows}
        tableLayout="fixed"
        scroll={{ x: 1150 }}
        pagination={{
          current: page,
          pageSize,
          total: run.case_count ?? run.progress_total ?? 0,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50],
          onChange: (nextPage, nextSize) => {
            setPage(nextSize === pageSize ? nextPage : 1);
            setPageSize(nextSize);
          },
        }}
        columns={[
          {
            title: t("agentEvaluation.cases.number"),
            width: 65,
            render: (_, __, index) => (page - 1) * pageSize + index + 1,
          },
          {
            title: t("agentEvaluation.cases.question"),
            width: 230,
            render: (_, row) => detail(row.inputs?.query),
          },
          {
            title: t("agentEvaluation.cases.expected"),
            width: 230,
            render: (_, row) => detail(row.label?.answer),
          },
          {
            title: t("agentEvaluation.cases.answer"),
            width: 230,
            render: (_, row) =>
              detail(
                row.predict?.answer ?? t("agentEvaluation.cases.notSaved")
              ),
          },
          {
            title: t("agentEvaluation.cases.result"),
            width: 120,
            render: (_, row) => (
              <Select
                aria-label={t("agentEvaluation.cases.result")}
                className="w-full"
                value={row.pass_status ?? undefined}
                placeholder="—"
                loading={saving === row.agent_evaluation_case_id}
                disabled={
                  !terminal ||
                  loading ||
                  saving !== null ||
                  !["COMPLETED", "FAILED"].includes(row.status)
                }
                options={[
                  { value: "pass", label: t("agentEvaluation.cases.pass") },
                  { value: "fail", label: t("agentEvaluation.cases.fail") },
                ]}
                onChange={(value) => void revise(row, value)}
              />
            ),
          },
          {
            title: t("agentEvaluation.cases.reason"),
            width: 260,
            render: (_, row) =>
              detail(
                [row.reason, row.error_message].filter(Boolean).join("\n")
              ),
          },
        ]}
      />
    </div>
  );
}
