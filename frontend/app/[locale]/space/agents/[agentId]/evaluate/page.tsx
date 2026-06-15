"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { ArrowLeft } from "lucide-react";
import { searchAgentInfo } from "@/services/agentConfigService";
import AgentEvaluationTab from "@/app/[locale]/agents/components/agentInfo/AgentEvaluationTab";
import log from "@/lib/logger";

export default function AgentEvaluatePage() {
  const params = useParams();
  const router = useRouter();
  const { t } = useTranslation("common");
  const agentId = Number(params?.agentId);
  const [agentName, setAgentName] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!Number.isFinite(agentId)) {
      setIsLoading(false);
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
      .finally(() => {
        setIsLoading(false);
      });
  }, [agentId]);

  if (!Number.isFinite(agentId)) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-slate-500">{t("agentEvaluation.invalidAgentId", "Invalid agent ID")}</p>
        <Button icon={<ArrowLeft className="h-4 w-4" />} onClick={() => router.push("/space")}>
          {t("common.back", "Back")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full p-6">
      <div className="flex items-center gap-3 mb-4">
        <Button
          type="text"
          icon={<ArrowLeft className="h-4 w-4" />}
          onClick={() => router.push("/space")}
        >
          {t("common.back", "Back")}
        </Button>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
          {isLoading
            ? t("agentEvaluation.pageTitle", "Evaluation")
            : `${t("agentEvaluation.pageTitle", "Evaluation")} - ${agentName}`}
        </h1>
      </div>
      <div className="flex-1 min-h-0">
        <AgentEvaluationTab agentId={agentId} />
      </div>
    </div>
  );
}
