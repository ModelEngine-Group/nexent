// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button, Switch, Tag, Tooltip } from "antd";
import { EditOutlined } from "@ant-design/icons";

import type { AidpKbDetail } from "@/ext_components/aidp/shared/types/management";
import { AIDP_UNKNOWN_VALUE, formatAidpCreator } from "@/ext_components/aidp/shared/utils/aidpKnowledgeDisplay";
import AidpGroupNamesDisplay from "@/ext_components/aidp/shared/components/AidpGroupNamesDisplay";

export const AidpDetailField = ({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) => (
  <div className={`min-w-0 ${className}`}>
    <dt className="mb-1 min-h-5 text-xs leading-5 text-gray-500">{label}</dt>
    <dd className="m-0 min-h-6 break-words text-sm leading-6 text-gray-800">
      {children}
    </dd>
  </div>
);

/** Editable detail settings owned by the information tab's edit modals. */
export type AidpDetailSetting =
  | "chunk_mode"
  | "topk"
  | "vlm"
  | "graph_llm"
  | "graph_hop"
  | "graph_thinking"
  | "graph_synonym"
  | "graph_disambiguation";

interface AidpKnowledgeDetailInformationProps {
  detail: AidpKbDetail;
  graphConfig: Record<string, unknown>;
  groupNames: string[];
  canConfigureGroupPermissions: boolean;
  /** Friendly embedding model label resolved from AIDP ModelService. */
  embeddingModelLabel?: string;
  formatDateTime: (value: unknown) => string;
  onEditSetting: (setting: AidpDetailSetting) => void;
  onEditPermissions: () => void;
  /** Opens the permanent-disable confirmation for the knowledge graph. */
  onDisableGraph: () => void;
}

const FIELD_GRID =
  "grid grid-cols-1 gap-x-8 gap-y-5 @min-[640px]:grid-cols-2 @min-[800px]:grid-cols-4";

const AidpKnowledgeDetailInformation = ({
  detail,
  graphConfig,
  groupNames,
  canConfigureGroupPermissions,
  embeddingModelLabel,
  formatDateTime,
  onEditSetting,
  onEditPermissions,
  onDisableGraph,
}: AidpKnowledgeDetailInformationProps) => {
  const { t } = useTranslation();
  const canEdit = detail.permission === "EDIT";
  const privateScope = detail.ingroup_permission === "PRIVATE";
  const multimodalEnabled =
    detail.is_multimodal === true || detail.caption_enable === 1;
  const displayValue = (value: unknown): string => {
    if (value === undefined || value === null || value === "")
      return AIDP_UNKNOWN_VALUE;
    if (typeof value === "boolean")
      return value ? t("common.yes") : t("common.no");
    return String(value);
  };
  const editButton = (setting: AidpDetailSetting, label: string) =>
    canEdit && (
      <Tooltip title={label}>
        <Button
          className="ml-2"
          type="text"
          size="small"
          aria-label={label}
          icon={<EditOutlined />}
          onClick={() => onEditSetting(setting)}
        />
      </Tooltip>
    );

  return (
    <div className="@container w-full shrink-0 divide-y divide-gray-200 pb-4">
      <section className="pb-6 pt-1">
        <h2 className="mb-5 text-lg font-semibold leading-7 text-gray-800">
          {t("aidpKnowledge.detailBasicInformation")}
        </h2>
        <dl className={FIELD_GRID}>
          <AidpDetailField label={t("aidpKnowledge.detailKbId")}>
            {detail.kds_id}
          </AidpDetailField>
          <AidpDetailField label={t("aidpKnowledge.detailCreatedAt")}>
            {formatDateTime(detail.created_at)}
          </AidpDetailField>
          <AidpDetailField label={t("aidpKnowledge.detailCreator")}>
            {formatAidpCreator(detail.creator_name) || AIDP_UNKNOWN_VALUE}
          </AidpDetailField>
        </dl>
      </section>

      <section className="pb-6 pt-6">
        <h2 className="mb-5 text-lg font-semibold leading-7 text-gray-800">
          {t("aidpKnowledge.detailConfiguration")}
        </h2>
        <dl className={FIELD_GRID}>
          <AidpDetailField label={t("aidpKnowledge.detailChunkMode")}>
            <span>
              {detail.chunk_mode === 1
                ? t("aidpKnowledge.chunkModeLegal")
                : detail.chunk_mode === 0
                  ? t("aidpKnowledge.chunkModeSmart")
                  : AIDP_UNKNOWN_VALUE}
            </span>
            {editButton("chunk_mode", t("aidpKnowledge.detailEditChunkMode"))}
          </AidpDetailField>
          <AidpDetailField label={t("aidpKnowledge.detailEmbeddingModel")}>
            {embeddingModelLabel ||
              detail.embedding_model ||
              AIDP_UNKNOWN_VALUE}
          </AidpDetailField>
          <AidpDetailField label={t("aidpKnowledge.detailVlmModel")}>
            {multimodalEnabled ? (
              <>
                <Tag color="green">{t("common.enabled")}</Tag>
                <span className="ml-2">
                  {detail.vlm_model || AIDP_UNKNOWN_VALUE}
                </span>
              </>
            ) : (
              <Tag color="default">{t("common.disabled")}</Tag>
            )}
            {editButton("vlm", t("aidpKnowledge.detailEditVlm"))}
          </AidpDetailField>
          <AidpDetailField label={t("aidpKnowledge.detailSimilarity")}>
            {displayValue(detail.similarity)}
          </AidpDetailField>
          <AidpDetailField label={t("aidpKnowledge.detailVectorTopK")}>
            <span>{displayValue(detail.topk)}</span>
            {editButton("topk", t("aidpKnowledge.detailEditTopK"))}
          </AidpDetailField>
        </dl>
      </section>

      <section className="py-6">
        <div className="mb-5 flex items-center gap-3">
          <h2 className="text-lg font-semibold leading-7 text-gray-800">
            {t("aidpKnowledge.detailGraph")}
          </h2>
          {detail.is_exist_graph === true && (
            <Switch
              checked
              disabled={!canEdit}
              aria-label={t("aidpKnowledge.detailGraph")}
              onChange={(checked) => {
                if (!checked) onDisableGraph();
              }}
            />
          )}
        </div>
        {detail.is_exist_graph !== true ? (
          <p className="text-sm text-gray-500">
            {t("aidpKnowledge.detailGraphDisabled")}
          </p>
        ) : (
          <dl className={FIELD_GRID}>
            <AidpDetailField label={t("aidpKnowledge.detailGraphModel")}>
              <span>{detail.llm_model_name || AIDP_UNKNOWN_VALUE}</span>
              {editButton("graph_llm", t("aidpKnowledge.detailEditGraphModel"))}
            </AidpDetailField>
            <AidpDetailField label={t("aidpKnowledge.detailGraphHops")}>
              <span>{displayValue(graphConfig.retrieve_subgraph_hop)}</span>
              {editButton("graph_hop", t("aidpKnowledge.detailEditGraphHop"))}
            </AidpDetailField>
            <AidpDetailField label={t("aidpKnowledge.detailGraphDomain")}>
              {displayValue(graphConfig.domain)}
            </AidpDetailField>
            <AidpDetailField label={t("aidpKnowledge.detailGraphThinking")}>
              <span>
                {displayValue(
                  graphConfig.no_think_mode === undefined
                    ? undefined
                    : !graphConfig.no_think_mode
                )}
              </span>
              {editButton(
                "graph_thinking",
                t("aidpKnowledge.detailEditGraphThinking")
              )}
            </AidpDetailField>
            <AidpDetailField label={t("aidpKnowledge.detailGraphSynonym")}>
              <span>{displayValue(graphConfig.synonym_merge_enable)}</span>
              {editButton(
                "graph_synonym",
                t("aidpKnowledge.detailEditGraphSynonym")
              )}
            </AidpDetailField>
            <AidpDetailField
              label={t("aidpKnowledge.detailGraphDisambiguation")}
            >
              <span>{displayValue(graphConfig.disambiguation_enable)}</span>
              {editButton(
                "graph_disambiguation",
                t("aidpKnowledge.detailEditGraphDisambiguation")
              )}
            </AidpDetailField>
            <AidpDetailField
              label={t("aidpKnowledge.detailGraphPromptLanguage")}
            >
              {displayValue(graphConfig.prompt_language)}
            </AidpDetailField>
            <AidpDetailField
              label={t("aidpKnowledge.detailGraphPrompt")}
              className="col-span-full"
            >
              <div className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words">
                {displayValue(graphConfig.prompt_text)}
              </div>
            </AidpDetailField>
          </dl>
        )}
      </section>

      <section className="py-6">
        <div className="mb-5 flex items-center gap-2">
          <h2 className="text-lg font-semibold leading-7 text-gray-800">
            {t("aidpKnowledge.detailPermissions")}
          </h2>
          {canEdit && canConfigureGroupPermissions && (
            <Tooltip title={t("common.edit")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.detailPermissions")}
                icon={<EditOutlined />}
                onClick={onEditPermissions}
              />
            </Tooltip>
          )}
        </div>
        <dl className={FIELD_GRID}>
          <AidpDetailField label={t("aidpKnowledge.detailScope")}>
            {privateScope
              ? t("aidpKnowledge.scopePrivate")
              : t("aidpKnowledge.scopeShared")}
          </AidpDetailField>
          <AidpDetailField label={t("aidpKnowledge.detailGroupPermission")}>
            {privateScope
              ? t("aidpKnowledge.detailOwnerOnly")
              : detail.ingroup_permission === "EDIT"
                ? t("aidpKnowledge.scopeGroupEdit")
                : t("aidpKnowledge.scopeGroupRead")}
          </AidpDetailField>
          <AidpDetailField
            label={t("aidpKnowledge.detailAllowedGroups")}
            className="@min-[640px]:col-span-2"
          >
            {privateScope ? (
              t("aidpKnowledge.detailOwnerOnly")
            ) : groupNames.length > 0 || (detail.group_ids || []).length > 0 ? (
              <AidpGroupNamesDisplay
                groupNames={
                  groupNames.length > 0
                    ? groupNames
                    : (detail.group_ids || []).map(String)
                }
              />
            ) : (
              AIDP_UNKNOWN_VALUE
            )}
          </AidpDetailField>
        </dl>
      </section>
    </div>
  );
};

export default AidpKnowledgeDetailInformation;
