"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export const CatalogSnapshotIdentifier: React.FC<{
  recommendationBatchId: string;
}> = ({ recommendationBatchId }) => {
  const { t } = useTranslation("common");
  const workflow = useNl2AgentWorkflow();
  const batch =
    workflow.sessionState?.resource_review.recommendations?.[
      recommendationBatchId
    ];
  if (!batch?.catalog_version || !batch.catalog_hash) return null;

  return (
    <div
      className="mb-2 break-all text-[11px] text-gray-400"
      data-testid={`catalog-snapshot-${recommendationBatchId}`}
    >
      {t("nl2agent.catalogSnapshot.label", {
        defaultValue: "Catalog snapshot",
      })}
      {": "}
      <code>{batch.catalog_version}</code>
      {" · sha256:"}
      <code>{batch.catalog_hash}</code>
    </div>
  );
};
