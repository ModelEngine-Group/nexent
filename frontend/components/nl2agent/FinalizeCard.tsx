"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { CheckCircle2, ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";

export interface FinalizeCardProps {
  agentId: number;
  status?: string;
}

/**
 * Renders a "Your agent is ready" summary card with a link to the draft
 * agent config page for review and publish.
 *
 * Rendered from a ```nl2agent-finalize fenced JSON block.
 */
export const FinalizeCard: React.FC<FinalizeCardProps> = ({ agentId, status }) => {
  const { t } = useTranslation("common");
  const router = useRouter();

  const handleReview = () => {
    router.push(`/en/agents?agent_id=${agentId}`);
  };

  return (
    <div className="my-3 border border-emerald-200 rounded-lg p-4 bg-emerald-50/50">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="h-5 w-5 text-emerald-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="font-medium text-emerald-800 text-sm mb-1">
            {t("nl2agent.finalize.title", "Your agent is ready")}
          </div>
          <div className="text-xs text-emerald-700 mb-3">
            {t("nl2agent.finalize.description", {
              defaultValue:
                "The draft agent has been generated. Review and publish it to start using.",
            })}
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="small"
              type="primary"
              onClick={handleReview}
              icon={<ArrowRight className="h-3.5 w-3.5" />}
            >
              {t("nl2agent.finalize.review", "Review & Publish")}
            </Button>
            <span className="text-[11px] text-gray-400">
              agent_id: {agentId}
              {status ? ` · ${status}` : ""}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
