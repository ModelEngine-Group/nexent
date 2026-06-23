"use client";

import { useState } from "react";
import { Button, Empty, Flex, Modal, Pagination, Spin, Typography } from "antd";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { EvaluationHistoryItem } from "@/types/agentEvaluation";
import { formatDateTime } from "@/lib/utils";

const { Text } = Typography;

const PAGE_SIZE = 3;

interface EvaluationHistoryCardProps {
  history: EvaluationHistoryItem[];
  loading: boolean;
  deletingId: number | null;
  selectedId: number | null;
  onSelect: (item: EvaluationHistoryItem) => void;
  onDelete: (evaluationId: number) => Promise<{ success: boolean }>;
}

export default function EvaluationHistoryCard({
  history,
  loading,
  deletingId,
  selectedId,
  onSelect,
  onDelete,
}: EvaluationHistoryCardProps) {
  const { t } = useTranslation("common");
  const [page, setPage] = useState(1);
  const total = history.length;
  const pageData = history.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const passRate = (item: EvaluationHistoryItem) => {
    const pass = item.pass_count ?? 0;
    const fail = item.fail_count ?? 0;
    const total = pass + fail;
    if (total === 0) return "-";
    return `${Math.round((pass / total) * 100)}%`;
  };

  const caseCount = (item: EvaluationHistoryItem) => {
    return (item.pass_count ?? 0) + (item.fail_count ?? 0);
  };

  const STATUS_LABELS: Record<string, string> = {
    PENDING: t("agentEvaluation.status.pending"),
    RUNNING: t("agentEvaluation.status.running"),
    COMPLETED: t("agentEvaluation.status.completed"),
    FAILED: t("agentEvaluation.status.failed"),
  };

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900 h-full">
        <div className="bg-slate-50 dark:bg-slate-800 px-4 py-3 border-b border-slate-100 dark:border-slate-700">
          <Text className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {t("agentEvaluation.history.title")}
            {history.length > 0 && (
              <Text className="text-xs text-slate-400 ml-1.5">
                ({t("agentEvaluation.history.count", { n: history.length })})
              </Text>
            )}
          </Text>
        </div>
        <Flex align="center" justify="center" className="py-12">
          <Spin />
        </Flex>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900 h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
        <Flex align="center" justify="space-between">
          <Text className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {t("agentEvaluation.history.title")}
            {history.length > 0 && (
              <Text className="text-xs text-slate-400 ml-1.5">
                ({t("agentEvaluation.history.count", { n: history.length })})
              </Text>
            )}
          </Text>
        </Flex>
      </div>

      {/* Body */}
      <div className="flex flex-col flex-1 overflow-y-auto px-3 py-3">
        {history.length === 0 ? (
          <Flex align="center" justify="center" className="py-8">
            <Empty
              description={
                <Text className="text-xs text-slate-400">{t("agentEvaluation.history.empty")}</Text>
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </Flex>
        ) : (
          <Flex vertical gap={3} className="flex-1">
            {pageData.map((item) => {
              const rate = passRate(item);
              const total = caseCount(item);
              return (
                <Flex
                  key={item.agent_evaluation_id}
                  vertical
                  gap={2}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    selectedId === item.agent_evaluation_id
                      ? "border-blue-400 bg-blue-50 dark:bg-blue-900/20"
                      : "border-slate-100 dark:border-slate-700 hover:border-blue-300 hover:bg-blue-50/50 dark:hover:bg-blue-900/10"
                  }`}
                  onClick={() => onSelect(item)}
                >
                  {/* Top row: version tag + set name */}
                  <Flex justify="space-between" align="center">
                    <Flex gap={6} align="center">
                      <Text className="text-xs px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 font-medium font-mono">
                        v{item.agent_version_no}
                      </Text>
                      <Text
                        className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate max-w-[120px]"
                        title={item.evaluation_set_name}
                      >
                        {item.evaluation_set_name || t("agentEvaluation.history.noSet")}
                      </Text>
                    </Flex>
                    <Text className="text-xs px-2 py-0.5 rounded-full font-medium bg-green-100 dark:bg-green-900/40 text-green-600 dark:text-green-400">
                      {STATUS_LABELS[item.status] || item.status}
                    </Text>
                  </Flex>

                  {/* Middle row: pass rate + case count spread across */}
                  <Flex gap={8} align="center">
                    <Text className="text-2xl font-bold text-slate-800 dark:text-slate-100 leading-none">
                      {rate}
                    </Text>
                    <Text className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                      {total} {t("agentEvaluation.history.pieces")}
                    </Text>
                  </Flex>

                  {/* Bottom row: time + delete */}
                  <Flex justify="space-between" align="center">
                    <Text className="text-xs text-slate-400">
                      {item.create_time ? formatDateTime(item.create_time) : "-"}
                    </Text>
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<Trash2 className="w-3.5 h-3.5" />}
                      loading={deletingId === item.agent_evaluation_id}
                      className="opacity-60 hover:opacity-100"
                      onClick={(e) => {
                        e.stopPropagation();
                        Modal.confirm({
                          title: t("agentEvaluation.history.confirmDelete"),
                          okText: t("common.confirm"),
                          cancelText: t("common.cancel"),
                          async onOk() {
                            await onDelete(item.agent_evaluation_id);
                          },
                        });
                      }}
                    />
                  </Flex>
                </Flex>
              );
            })}

            {total > PAGE_SIZE && (
              <Flex justify="center" className="mt-2">
                <Pagination
                  size="small"
                  current={page}
                  pageSize={PAGE_SIZE}
                  total={total}
                  onChange={setPage}
                  showSizeChanger={false}
                />
              </Flex>
            )}
          </Flex>
        )}
      </div>
    </div>
  );
}
