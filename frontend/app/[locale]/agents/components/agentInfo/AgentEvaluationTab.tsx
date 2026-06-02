"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Divider, Flex, Input, Modal, Select, Table, Typography, message } from "antd";
import { Upload, X } from "lucide-react";

import type { ColumnsType } from "antd/es/table";

import { evaluationService } from "@/services/evaluationService";
import { useModelList } from "@/hooks/model/useModelList";
import type { AgentEvaluationRun, EvaluationSet } from "@/types/agentEvaluation";
import { formatDateTime } from "@/lib/utils";

const { Text } = Typography;

export default function AgentEvaluationTab(props: { agentId: number | null | undefined }) {
  const { t } = useTranslation("common");
  const agentId = props.agentId;

  const [evaluationSets, setEvaluationSets] = useState<EvaluationSet[]>([]);
  const [runs, setRuns] = useState<AgentEvaluationRun[]>([]);

  const [loadingSets, setLoadingSets] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(false);

  const [createSetOpen, setCreateSetOpen] = useState(false);
  const [setName, setSetName] = useState("");
  const [setDesc, setSetDesc] = useState("");
  const [excelFiles, setExcelFiles] = useState<File[]>([]);

  const [judgeModelId, setJudgeModelId] = useState<number | null>(null);
  const [selectedEvaluationSetIds, setSelectedEvaluationSetIds] = useState<number[]>([]);

  const { availableLlmModels } = useModelList();

  const modelOptions = useMemo(() => {
    return availableLlmModels.map((m) => ({
      label: m.displayName || m.name,
      value: m.id,
    }));
  }, [availableLlmModels]);

  const loadSets = async () => {
    setLoadingSets(true);
    try {
      const data = await evaluationService.listEvaluationSets({ limit: 200, offset: 0 });
      setEvaluationSets(data);
      if (data?.length && !selectedEvaluationSetIds.length) {
        setSelectedEvaluationSetIds([data[0].evaluation_set_id]);
      }
    } catch (e: any) {
      message.error(e?.message || t("agentEvaluation.message.loadSetsFailed"));
    } finally {
      setLoadingSets(false);
    }
  };

  const loadRuns = async () => {
    if (!agentId) return;
    setLoadingRuns(true);
    try {
      const data = await evaluationService.listAgentEvaluationsByAgent(agentId, { limit: 200, offset: 0 });
      setRuns(data);
    } catch (e: any) {
      message.error(e?.message || t("agentEvaluation.message.loadRunsFailed"));
    } finally {
      setLoadingRuns(false);
    }
  };

  // Keep consistent with Agent model selector: only show available LLM models.
  useEffect(() => {
    if (!modelOptions.length) return;
    if (judgeModelId != null && modelOptions.some((o) => o.value === judgeModelId)) return;
    setJudgeModelId(modelOptions[0].value);
  }, [modelOptions, judgeModelId]);

  useEffect(() => {
    loadSets();
  }, []);

  useEffect(() => {
    loadRuns();
  }, [agentId]);

  // Lightweight polling for runs status
  useEffect(() => {
    if (!agentId) return;
    const hasRunning = runs.some((r) => r.status === "PENDING" || r.status === "RUNNING");
    if (!hasRunning) return;

    const timer = setInterval(() => {
      loadRuns();
    }, 2000);

    return () => clearInterval(timer);
  }, [agentId, runs]);

  const setColumns: ColumnsType<EvaluationSet> = [
    { title: t("common.name"), dataIndex: "name", key: "name" },
    { title: t("common.description"), dataIndex: "description", key: "description", render: (v) => <Text type="secondary">{v || "-"}</Text> },
    { title: t("common.count"), dataIndex: "case_count", key: "case_count", width: 120 },
  ];

  const STATUS_LABELS: Record<string, string> = {
    PENDING: t("agentEvaluation.status.pending"),
    RUNNING: t("agentEvaluation.status.running"),
    COMPLETED: t("agentEvaluation.status.completed"),
    FAILED: t("agentEvaluation.status.failed"),
  };

  const runColumns: ColumnsType<AgentEvaluationRun> = [
    { title: t("common.id"), dataIndex: "agent_evaluation_id", key: "id", width: 80 },
    {
      title: t("common.status"),
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (v) => STATUS_LABELS[v] ?? v,
    },
    {
      title: t("common.progress"),
      key: "progress",
      render: (_, r) => {
        const done = r.progress_done ?? 0;
        const total = r.progress_total ?? 0;
        return (
          <Text>
            {done}/{total}
          </Text>
        );
      },
    },
    { title: t("common.score"), dataIndex: "score_overall", key: "score_overall", width: 80, render: (v) => (v == null ? "-" : v.toFixed(3)) },
    {
      title: t("common.failedReason"),
      dataIndex: "error_message",
      key: "error_message",
      ellipsis: true,
      render: (v, r) => {
        if (!v) return "-";
        return (
          <Text type={r.status === "FAILED" ? "danger" : undefined} title={String(v)}>
            {String(v)}
          </Text>
        );
      },
    },
    { title: t("common.createdAt"), dataIndex: "create_time", key: "create_time", render: (v) => formatDateTime(v || "") },
    {
      title: t("common.downloadReport"),
      key: "report",
      width: 100,
      render: (_, r) => (
        <Button
          size="small"
          onClick={async (e) => {
            e.stopPropagation();
            try {
              const blob = await evaluationService.downloadEvaluationReport(r.agent_evaluation_id);
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `evaluation_report_${r.agent_evaluation_id}.xlsx`;
              document.body.appendChild(a);
              a.click();
              a.remove();
              URL.revokeObjectURL(url);
            } catch (e: any) {
              message.error(e?.message || "Download report failed");
            }
          }}
        >
          {t("common.downloadReport")}
        </Button>
      ),
    },
  ];

  const startEvaluations = async () => {
    if (!agentId) return;
    if (!judgeModelId) {
      message.error(t("agentEvaluation.selectJudgeModelFirst"));
      return;
    }
    if (!selectedEvaluationSetIds.length) {
      message.error(t("agentEvaluation.selectEvaluationSetFirst"));
      return;
    }
    try {
      for (const evaluation_set_id of selectedEvaluationSetIds) {
        await evaluationService.createAgentEvaluation({
          agent_id: agentId,
          evaluation_set_id,
          judge_model_id: judgeModelId,
        });
      }
      message.success(t("agentEvaluation.message.startSuccess"));
      await loadRuns();
    } catch (e: any) {
      message.error(e?.message || t("agentEvaluation.message.startFailed"));
    }
  };

  // Reset form when modal closes
  useEffect(() => {
    if (!createSetOpen) {
      setSetName("");
      setSetDesc("");
      setExcelFiles([]);
    }
  }, [createSetOpen]);

  const createSet = async () => {
    try {
      const name = setName.trim();
      if (!name) {
        message.error(t("agentEvaluation.createSetModal.nameRequired"));
        return;
      }
      if (!excelFiles.length) {
        message.error(t("agentEvaluation.createSetModal.fileRequired"));
        return;
      }

      await evaluationService.uploadEvaluationSetExcel({
        name,
        description: setDesc || undefined,
        files: excelFiles,
      });
      message.success(t("agentEvaluation.message.createSetSuccess"));
      setCreateSetOpen(false);
      await loadSets();
    } catch (e: any) {
      message.error(e?.message || t("agentEvaluation.message.createSetFailed"));
    }
  };

  return (
    <Flex vertical gap={12} className="h-full">
      <Flex justify="space-between" align="center">
        <Flex align="center" gap={12}>
          <Text strong>{t("agentEvaluation.evaluationSet")}</Text>
          <Button onClick={() => setCreateSetOpen(true)} type="primary" disabled={!agentId}>
            {t("agentEvaluation.uploadExcel")}
          </Button>
          <Button
            onClick={async () => {
              try {
                const blob = await evaluationService.downloadEvaluationSetTemplate();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "evaluation_set_template.xlsx";
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
              } catch (e: any) {
                message.error(e?.message || t("agentEvaluation.downloadTemplateFailed"));
              }
            }}
          >
            {t("agentEvaluation.downloadTemplate")}
          </Button>
        </Flex>

        <Flex align="center" gap={8}>
          <Text type="secondary">{t("agentEvaluation.judgeModel")}</Text>
          <Select
            style={{ width: 260 }}
            value={judgeModelId ?? undefined}
            onChange={(v) => setJudgeModelId(v)}
            options={modelOptions}
            placeholder={t("agentEvaluation.selectJudgeModel")}
          />
          <Button
            type="primary"
            disabled={!agentId || !judgeModelId || !selectedEvaluationSetIds.length}
            onClick={() => {
              if (!judgeModelId) {
                message.error(t("agentEvaluation.selectJudgeModelFirst"));
                return;
              }
              if (!selectedEvaluationSetIds.length) {
                message.error(t("agentEvaluation.selectEvaluationSetFirst"));
                return;
              }
              startEvaluations();
            }}
          >
            {t("agentEvaluation.startEvaluation")}
          </Button>
        </Flex>
      </Flex>

      <Table
        rowKey={(r) => r.evaluation_set_id}
        size="small"
        columns={setColumns}
        dataSource={evaluationSets}
        loading={loadingSets}
        pagination={false}
        rowSelection={{
          type: "checkbox",
          selectedRowKeys: selectedEvaluationSetIds,
          onChange: (keys) => {
            setSelectedEvaluationSetIds(keys.map((k) => Number(k)));
          },
        }}
      />

      <Divider style={{ margin: "8px 0" }} />

      <Flex justify="space-between" align="center">
        <Text strong>{t("agentEvaluation.evaluationTasks")}</Text>
        <Button onClick={loadRuns} disabled={!agentId}>
          {t("agentEvaluation.refreshRuns")}
        </Button>
      </Flex>

      <Table
        rowKey={(r) => String(r.agent_evaluation_id)}
        size="small"
        columns={runColumns}
        dataSource={runs}
        loading={loadingRuns}
        pagination={false}
      />

      <Modal
        open={createSetOpen}
        onCancel={() => setCreateSetOpen(false)}
        onOk={createSet}
        title={t("agentEvaluation.createSetModal.title")}
        okText={t("agentEvaluation.createSetModal.create")}
        cancelText={t("common.cancel")}
      >
        <Flex vertical gap={8}>
          <Input value={setName} onChange={(e) => setSetName(e.target.value)} placeholder={t("agentEvaluation.createSetModal.namePlaceholder")} />
          <Input value={setDesc} onChange={(e) => setSetDesc(e.target.value)} placeholder={t("agentEvaluation.createSetModal.descPlaceholder")} />
          <div className="space-y-2">
            <input
              id="excel-file-input"
              type="file"
              multiple
              accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
              style={{ display: "none" }}
              onChange={(e) => {
                const files = Array.from(e.target.files || []);
                if (files.length > 0) {
                  setExcelFiles((prev) => [...prev, ...files]);
                }
                e.target.value = "";
              }}
            />
            <Button
              onClick={() => {
                document.getElementById("excel-file-input")?.click();
              }}
              icon={<Upload size={14} />}
            >
              {t("agentEvaluation.createSetModal.chooseFile")}
            </Button>
            {excelFiles.length > 0 ? (
              <div className="space-y-1">
                {excelFiles.map((f, idx) => (
                  <Flex key={idx} align="center" gap={4} className="text-xs">
                    <Text className="truncate max-w-[300px]">{f.name}</Text>
                    <button
                      onClick={() => setExcelFiles((prev) => prev.filter((_, i) => i !== idx))}
                      className="flex-shrink-0 text-gray-400 hover:text-red-500"
                    >
                      <X size={12} />
                    </button>
                  </Flex>
                ))}
              </div>
            ) : (
              <Text type="secondary" className="text-xs">
                {t("agentEvaluation.createSetModal.noFile")}
              </Text>
            )}
          </div>
        </Flex>
      </Modal>
    </Flex>
  );
}
