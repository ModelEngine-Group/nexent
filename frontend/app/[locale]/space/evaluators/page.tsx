"use client";
import { useState, useEffect, useCallback } from "react";
import { Card, Space, Spin, Tag, Typography, App } from "antd";
import { useTranslation } from "react-i18next";
import { API_ENDPOINTS } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";

const { Title, Text } = Typography;

export default function EvaluatorPage() {
  const { t, i18n } = useTranslation("common");
  const currentLang = (i18n.language || "zh").startsWith("zh") ? "zh" : "en";
  const { message: msg } = App.useApp();
  const [evaluators, setEvaluators] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchEvaluators = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(API_ENDPOINTS.evaluators.list, {
        headers: getAuthHeaders(),
      });
      const data = await resp.json();
      setEvaluators(data?.data || []);
    } catch {
      msg.error(t("common.error.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEvaluators();
  }, []);

  const builtin = evaluators.filter((e: any) => e.source === "builtin");
  const custom = evaluators.filter((e: any) => e.source === "custom");
  const typeLabels: Record<string, string> = {
    llm: t("agentEvaluation.evaluatorType.llm"),
    code: t("agentEvaluation.evaluatorType.code"),
  };
  const statusLabels: Record<string, { color: string; text: string }> = {
    PUBLISHED: { color: "green", text: t("agentEvaluation.published") },
    DRAFT: { color: "orange", text: t("agentEvaluation.draft") },
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <Title level={4}>{t("agentEvaluation.evaluatorManager")}</Title>
      <Spin spinning={loading}>
        {[
          { label: t("agentEvaluation.builtin"), data: builtin },
          { label: t("agentEvaluation.custom"), data: custom },
        ].map((group) => (
          <div key={group.label} className="mb-6">
            <Text strong className="text-lg mb-3 block">
              {group.label} ({group.data.length})
            </Text>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {group.data.map((e: any) => (
                <Card
                  key={e.evaluator_id}
                  size="small"
                  title={
                    currentLang === "en"
                      ? e.name_en || e.name
                      : e.name || e.name_en
                  }
                >
                  <Space wrap>
                    <Tag color={e.evaluator_type === "llm" ? "blue" : "purple"}>
                      {typeLabels[e.evaluator_type] || e.evaluator_type}
                    </Tag>
                    <Tag color={statusLabels[e.status]?.color || "default"}>
                      {statusLabels[e.status]?.text || e.status}
                    </Tag>
                  </Space>
                  <div className="text-xs text-gray-500 mt-2">
                    {currentLang === "en"
                      ? e.description_en ||
                        e.description ||
                        t("agentEvaluation.noDescription")
                      : e.description ||
                        e.description_en ||
                        t("agentEvaluation.noDescription")}
                  </div>
                </Card>
              ))}
            </div>
            {group.data.length === 0 && (
              <Text type="secondary">{t("agentEvaluation.none")}</Text>
            )}
          </div>
        ))}
      </Spin>
    </div>
  );
}
