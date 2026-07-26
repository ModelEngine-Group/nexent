"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { ArrowLeft, BarChart2 } from "lucide-react";
import { Button, Flex, Typography } from "antd";
import { searchAgentInfo } from "@/services/agentConfigService";
import log from "@/lib/logger";

import EvaluationConfigCard from "../components/EvaluationConfigCard";
import EvaluationHistoryCard from "../components/EvaluationHistoryCard";
import EvaluationReportCard from "../components/EvaluationReportCard";
import TestCaseLibraryModal from "../components/TestCaseLibraryModal";
import { useEvaluationHistory } from "@/hooks/evaluation/useEvaluationHistory";
import type { AgentEvaluationRun, EvaluationSet, EvaluationHistoryItem } from "@/types/agentEvaluation";

const { Text } = Typography;

interface AgentEvaluateClientProps {
  agentId: number;
}

export default function AgentEvaluateClient({ agentId }: AgentEvaluateClientProps) {
  const params = useParams<{ locale: string }>();
  const router = useRouter();
  const { t } = useTranslation("common");
  const searchParams = useSearchParams();
  const locale = params?.locale || "en";
  const backTab = searchParams.get("back_tab");
  const backHref = backTab
    ? `/${locale}/agent-space?back_tab=${backTab}`
    : `/${locale}/agent-space`;

  const [agentName, setAgentName] = useState("");
  const [isLoadingAgent, setIsLoadingAgent] = useState(true);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedSet, setSelectedSet] = useState<EvaluationSet | null>(null);

  const handleEvaluationCompleted = useCallback(
    (item: EvaluationHistoryItem) => {
      setSelectedRun(item);
      setReportOpen(true);
    },
    []
  );

  const {
    history,
    loading: historyLoading,
    deletingId,
    loadHistory,
    deleteRun,
    setHistory,
  } = useEvaluationHistory(agentId, handleEvaluationCompleted);

  const [selectedRun, setSelectedRun] = useState<EvaluationHistoryItem | null>(null);
  const [reportOpen, setReportOpen] = useState(false);

  useEffect(() => {
    if (!Number.isFinite(agentId)) {
      setIsLoadingAgent(false);
      return;
    }
    searchAgentInfo(agentId)
      .then((res) => {
        if (res.success && res.data) {
          setAgentName(res.data.display_name || res.data.name || "");
        }
      })
      .catch((err) => {
        log.error("Failed to load agent info for evaluation page:", err);
      })
      .finally(() => setIsLoadingAgent(false));
  }, [agentId]);

  const handleSetSelected = useCallback((set: EvaluationSet | null) => {
    setSelectedSet(set);
  }, []);

  const handleHistorySelect = useCallback((item: EvaluationHistoryItem) => {
    setSelectedRun(item);
    setReportOpen(true);
  }, []);

  const handleEvaluationStarted = useCallback(
    (run: AgentEvaluationRun) => {
      const item: EvaluationHistoryItem = {
        agent_evaluation_id: run.agent_evaluation_id,
        agent_version_no: run.agent_version_no,
        evaluation_set_name: run.evaluation_set_name,
        judge_model_name: run.judge_model_name,
        status: run.status,
        score_overall: run.score_overall,
        case_count: run.case_count,
        pass_count: run.pass_count,
        fail_count: run.fail_count,
        progress_total: run.progress_total,
        progress_done: run.progress_done,
        create_time: run.create_time,
      };
      setHistory((prev) => [item, ...prev]);
      loadHistory();
    },
    [loadHistory]
  );

  const runningItem = history.find((r) => r.status === "RUNNING" || r.status === "PENDING");
  const runningProgress =
    runningItem && runningItem.progress_total
      ? { done: runningItem.progress_done ?? 0, total: runningItem.progress_total }
      : undefined;

  if (!Number.isFinite(agentId)) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-slate-500">{t("agentEvaluation.invalidAgentId")}</p>
        <Button icon={<ArrowLeft className="h-4 w-4" />} onClick={() => router.push(backHref)}>
          {t("common.back")}
        </Button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Page Header */}
      <div className="mx-auto max-w-6xl px-6 pt-6 pb-4">
        <Flex vertical gap={2}>
          <Button
            type="text"
            icon={<ArrowLeft className="h-4 w-4" />}
            onClick={() => router.push(backHref)}
            className="self-start px-0"
          >
            {t("common.back")}
          </Button>
          <Flex align="center" gap={3} wrap>
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
              <BarChart2 className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate font-semibold text-gray-900 dark:text-white">
                  {isLoadingAgent ? t("agentEvaluation.tab") : (agentName || t("agentEvaluation.tab"))}
                </h1>
                <Text className="shrink-0 rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
                  {t("agentEvaluation.badge")}
                </Text>
              </div>
              <p className="truncate text-sm text-gray-500 dark:text-gray-400">
                {t("agentEvaluation.pageDesc")}
              </p>
            </div>
          </Flex>
        </Flex>
      </div>

      {/* Scrollable Content */}
      <div className="mx-auto max-w-6xl px-6 pb-8">
        {/* Step 1 + History — equal height, full-width grid */}
        <div className="grid gap-6 lg:grid-cols-5 lg:items-stretch">
          <div className="lg:col-span-3">
            <EvaluationConfigCard
              agentId={agentId}
              selectedSet={selectedSet}
              onOpenLibrary={() => setLibraryOpen(true)}
              onOpenUpload={() => setUploadOpen(true)}
              onEvaluationStarted={handleEvaluationStarted}
              runningProgress={runningProgress}
            />
          </div>
          <div className="lg:col-span-2">
            <EvaluationHistoryCard
              history={history}
              loading={historyLoading}
              deletingId={deletingId}
              selectedId={selectedRun?.agent_evaluation_id ?? null}
              onSelect={handleHistorySelect}
              onDelete={deleteRun}
            />
          </div>
        </div>

        {/* Step 2 - Report */}
        {reportOpen && <EvaluationReportCard run={selectedRun} />}
      </div>
      <TestCaseLibraryModal
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        selectedSetId={selectedSet?.evaluation_set_id ?? null}
        onSelect={handleSetSelected}
        uploadOpen={uploadOpen}
        onUploadOpenChange={setUploadOpen}
      />
    </div>
  );
}