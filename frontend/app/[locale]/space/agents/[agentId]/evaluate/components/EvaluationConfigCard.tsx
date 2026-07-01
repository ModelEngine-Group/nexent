"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Flex, Select, Typography, message } from "antd";
import { BookOpen, PlayCircle, Download, FileSpreadsheet, Upload } from "lucide-react";
import { useModelList } from "@/hooks/model/useModelList";
import { useStartEvaluation } from "@/hooks/evaluation/useStartEvaluation";
import { evaluationService } from "@/services/evaluationService";
import type { AgentEvaluationRun, EvaluationSet } from "@/types/agentEvaluation";

const { Text } = Typography;

interface EvaluationConfigCardProps {
  agentId: number;
  selectedSet: EvaluationSet | null;
  onOpenLibrary: () => void;
  onOpenUpload: () => void;
  onEvaluationStarted: (run: AgentEvaluationRun) => void;
  runningProgress?: { done: number; total: number };
}

export default function EvaluationConfigCard({
  agentId,
  selectedSet,
  onOpenLibrary,
  onOpenUpload,
  onEvaluationStarted,
  runningProgress,
}: EvaluationConfigCardProps) {
  const { t } = useTranslation("common");
  const { availableLlmModels } = useModelList();
  const { startEvaluation, starting } = useStartEvaluation();

  const [judgeModelId, setJudgeModelId] = useState<number | null>(null);
  const [agentVersionNo, setAgentVersionNo] = useState<number | null>(null);
  const [agentVersions, setAgentVersions] = useState<{ label: string; value: number }[]>([]);

  const modelOptions = useMemo(
    () =>
      availableLlmModels.map((m) => ({
        label: m.displayName || m.name,
        value: m.id,
      })),
    [availableLlmModels]
  );

  useEffect(() => {
    if (modelOptions.length && judgeModelId == null) {
      setJudgeModelId(modelOptions[0].value);
    }
  }, [modelOptions, judgeModelId]);

  useEffect(() => {
    fetch(`/api/agent/${agentId}/versions`)
      .then((r) => r.json())
      .then((res) => {
        const versions = (res.items || []).map((v: { version_no: number }) => ({
          label: `v${v.version_no}`,
          value: v.version_no,
        }));
        setAgentVersions(versions);
        if (versions.length && agentVersionNo == null) {
          setAgentVersionNo(versions[0].value);
        }
      })
      .catch(() => {});
  }, [agentId]);

  const handleStart = async () => {
    if (!judgeModelId) {
      message.error(t("agentEvaluation.selectJudgeModelFirst"));
      return;
    }
    if (!selectedSet) {
      message.error(t("agentEvaluation.step1.selectFirst"));
      return;
    }
    const result = await startEvaluation({
      agentId,
      evaluationSetId: selectedSet.evaluation_set_id,
      judgeModelId,
    });
    if (result) {
      onEvaluationStarted(result);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const blob = await evaluationService.downloadEvaluationSetTemplate();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "agent_evaluation_template.xlsx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      message.error(err?.message || t("agentEvaluation.downloadTemplateFailed"));
    }
  };

  const isRunning = runningProgress != null;

  return (
    <div className="flex flex-col rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900">
      {/* Step 1 header with number circle */}
      <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
        <Flex align="center" gap={2}>
          <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
            <Text className="text-xs font-semibold text-white leading-none">1</Text>
          </div>
          <Text className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {t("agentEvaluation.step1.title")}
          </Text>
        </Flex>
      </div>

      {/* Content */}
      <div className="px-4 py-4">
        <Flex vertical gap={5}>
          {/* Config area: model + version in a gray box */}
          <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 p-4">
            <Flex gap={12} wrap>
              <Flex vertical gap={1.5} className="flex-1 min-w-[200px]">
                <Text className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  {t("agentEvaluation.step1.judgeModel")}
                </Text>
                <Select
                  placeholder={t("agentEvaluation.selectJudgeModel")}
                  options={modelOptions}
                  value={judgeModelId}
                  onChange={setJudgeModelId}
                  className="w-full"
                  size="middle"
                />
                <Text className="text-xs text-slate-400 dark:text-slate-500">
                  {t("agentEvaluation.step1.judgeModelHint")}
                </Text>
              </Flex>

              <Flex vertical gap={1.5} className="flex-1 min-w-[200px]">
                <Text className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  {t("agentEvaluation.step1.agentVersion")}
                </Text>
                <Select
                  placeholder={t("agentEvaluation.step1.agentVersionHint")}
                  options={agentVersions}
                  value={agentVersionNo}
                  onChange={setAgentVersionNo}
                  className="w-full"
                  size="middle"
                />
                <Text className="text-xs text-slate-400 dark:text-slate-500">
                  {t("agentEvaluation.step1.agentVersionHint2")}
                </Text>
              </Flex>
            </Flex>
          </div>

          {/* Download template + Test case selector — equal height stretch */}
          <div className="grid gap-4 sm:grid-cols-2 items-stretch">
            {/* Download template */}
            <div className="flex flex-col rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 p-4">
              <div className="flex size-10 w-10 items-center justify-center rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 flex-shrink-0">
                <FileSpreadsheet className="size-5" />
              </div>
              <Text className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("agentEvaluation.step1.downloadTemplate")}
              </Text>
              <Text className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                {t("agentEvaluation.step1.downloadTemplateHint")}
              </Text>
              <div className="mt-auto pt-3">
                <Button
                  variant="outline"
                  size="small"
                  icon={<Download className="size-4" />}
                  onClick={handleDownloadTemplate}
                  block
                >
                  {t("agentEvaluation.step1.downloadTemplateBtn")}
                </Button>
              </div>
            </div>

            {/* Test case selector */}
            <div className="flex flex-col rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 p-4">
              <div className="flex size-10 w-10 items-center justify-center rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 flex-shrink-0">
                <BookOpen className="size-5" />
              </div>
              <Text className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("agentEvaluation.step1.selectTestCaseSet")}
              </Text>
              {selectedSet ? (
                <Flex
                  align="center"
                  justify="space-between"
                  className="mt-2 rounded-md bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-1.5"
                >
                  <Text className="truncate text-xs text-slate-600 dark:text-slate-300">
                    {selectedSet.name}
                  </Text>
                  <Button
                    type="link"
                    size="small"
                    onClick={onOpenLibrary}
                    className="text-blue-600 dark:text-blue-400 text-xs px-0 py-0 h-auto"
                  >
                    {t("agentEvaluation.step1.changeSet")}
                  </Button>
                </Flex>
              ) : (
                <Text className="mt-2 text-xs text-slate-400 dark:text-slate-500">
                  {t("agentEvaluation.step1.selectTestCaseSetHint")}
                </Text>
              )}
              <Flex gap={4} className="mt-auto pt-3" wrap>
                <Button size="small" icon={<Upload className="size-4" />} onClick={onOpenUpload} block>
                  {t("agentEvaluation.lib.uploadExcel")}
                </Button>
                <Button size="small" icon={<BookOpen className="size-4" />} onClick={onOpenLibrary} block>
                  {t("agentEvaluation.step1.testCaseLibrary")}
                </Button>
              </Flex>
            </div>
          </div>

          {/* Start button */}
          <Flex align="center" justify="space-between">
            {isRunning ? (
              <Flex align="center" gap={3} className="flex-1 min-w-0">
                <Text className="text-xs text-slate-400 whitespace-nowrap">
                  {t("agentEvaluation.step1.runningHint", {
                    done: runningProgress?.done ?? 0,
                    total: runningProgress?.total ?? 0,
                  })}
                </Text>
                <div className="h-1.5 flex-1 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden max-w-[160px]">
                  <div
                    className="h-full rounded-full bg-blue-500 transition-all duration-300"
                    style={{
                      width: `${Math.round(
                        ((runningProgress?.done ?? 0) / (runningProgress?.total ?? 1)) * 100
                      )}%`,
                    }}
                  />
                </div>
                <Text className="text-xs text-slate-400 whitespace-nowrap">
                  {Math.round(
                    ((runningProgress?.done ?? 0) / (runningProgress?.total ?? 1)) * 100
                  )}%
                </Text>
              </Flex>
            ) : (
              <Text className="text-xs text-slate-400">
                {selectedSet
                  ? t("agentEvaluation.step1.ready")
                  : t("agentEvaluation.step1.selectFirst")}
              </Text>
            )}
            <Button
              type="primary"
              icon={<PlayCircle className="w-4 h-4" />}
              loading={starting}
              disabled={!selectedSet || isRunning}
              onClick={handleStart}
            >
              {isRunning ? t("agentEvaluation.step1.running") : t("agentEvaluation.step1.start")}
            </Button>
          </Flex>
        </Flex>
      </div>
    </div>
  );
}
