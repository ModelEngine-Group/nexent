// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button, Descriptions, Drawer, Tag, Tooltip } from "antd";
import { DeleteOutlined, EditOutlined } from "@ant-design/icons";

import type { AidpOntologyRule } from "@/ext_components/aidp/shared/types/ontology";
import { formatAidpDateTime } from "@/ext_components/aidp/shared/utils/aidpTime";
import { ruleOperatorLabel } from "@/ext_components/aidp/shared/utils/aidpOntologyRule";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyRuleDetailDrawer.module.css";

interface AidpOntologyRuleDetailDrawerProps {
  open: boolean;
  rule: AidpOntologyRule | null;
  onClose: () => void;
  onEdit?: (rule: AidpOntologyRule) => void;
  onDelete?: (rule: AidpOntologyRule) => void;
}

const AidpOntologyRuleDetailDrawer: React.FC<
  AidpOntologyRuleDetailDrawerProps
> = ({ open, rule, onClose, onEdit, onDelete }) => {
  const { t } = useTranslation();
  const conditions = rule?.condition?.value?.conditions ?? [];
  const action = rule?.action?.value;
  const dynamic = !!action?.field;
  const logicOperator =
    rule?.condition?.value?.logical_operator === "or" ? "or" : "and";

  const renderConditions = () => {
    if (conditions.length === 0) return "—";
    return (
      <div className={styles.conditionList}>
        {conditions.map((condition, index) => (
          <div
            key={`${condition.field}-${index}`}
            className={styles.conditionRow}
          >
            <span className={styles.conditionField}>{condition.field}</span>
            <span>{ruleOperatorLabel(condition.operator)}</span>
            <span className={styles.conditionValue}>
              {condition.value === null ||
              condition.value === undefined ||
              condition.value === ""
                ? "—"
                : String(condition.value)}
            </span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={560}
      onClose={onClose}
      destroyOnHidden
      mask={false}
      title={rule?.name ?? t("aidpKnowledge.ontologyRulesDetailTitle")}
      extra={
        rule ? (
          <div className={styles.headerActions}>
            <Tooltip title={t("aidpKnowledge.ontologyEdit")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.ontologyEdit")}
                icon={<EditOutlined />}
                onClick={() => onEdit?.(rule)}
              />
            </Tooltip>
            <Tooltip title={t("aidpKnowledge.ontologyDelete")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.ontologyDelete")}
                icon={<DeleteOutlined />}
                onClick={() => onDelete?.(rule)}
              />
            </Tooltip>
          </div>
        ) : null
      }
    >
      {rule && (
        <Descriptions
          size="small"
          column={1}
          bordered
          items={[
            {
              key: "description",
              label: t("aidpKnowledge.ontologyRulesDescription"),
              children: rule.description || "—",
            },
            {
              key: "status",
              label: t("aidpKnowledge.ontologyRulesStatus"),
              children: (
                <Tag color={rule.enabled ? "green" : "default"}>
                  {rule.enabled
                    ? t("aidpKnowledge.ontologyRulesEnabled")
                    : t("aidpKnowledge.ontologyRulesDisabled")}
                </Tag>
              ),
            },
            {
              key: "conditions",
              label: t("aidpKnowledge.ontologyRulesFilterRules"),
              children: renderConditions(),
            },
            {
              key: "logic",
              label: t("aidpKnowledge.ontologyRulesLogicalOperator"),
              children:
                logicOperator === "or"
                  ? t("aidpKnowledge.ontologyRulesOrShort")
                  : t("aidpKnowledge.ontologyRulesAndShort"),
            },
            {
              key: "aggregation",
              label: t("aidpKnowledge.ontologyRulesAggregation"),
              children:
                action?.effect_mode === "multiply"
                  ? t("aidpKnowledge.ontologyRulesMultiplyShort")
                  : t("aidpKnowledge.ontologyRulesAddShort"),
            },
            {
              key: "source",
              label: t("aidpKnowledge.ontologyRulesScoreSource"),
              children: dynamic
                ? t("aidpKnowledge.ontologyRulesDynamicScale")
                : t("aidpKnowledge.ontologyRulesFixedValue"),
            },
            ...(dynamic
              ? [
                  {
                    key: "field",
                    label: t("aidpKnowledge.ontologyRulesScaleMetadata"),
                    children: action?.field || "—",
                  },
                  {
                    key: "scale",
                    label: t("aidpKnowledge.ontologyRulesScaleCoefficient"),
                    children:
                      action?.field_scale !== null &&
                      action?.field_scale !== undefined
                        ? String(action.field_scale)
                        : "—",
                  },
                  {
                    key: "transform",
                    label: t("aidpKnowledge.ontologyRulesScaleMethod"),
                    children:
                      action?.field_transform === "log"
                        ? t("aidpKnowledge.ontologyRulesLog")
                        : t("aidpKnowledge.ontologyRulesLinear"),
                  },
                  ...(action?.field_transform === "linear" && action.field_range
                    ? [
                        {
                          key: "range",
                          label: t("aidpKnowledge.ontologyRulesLinearRange"),
                          children: action.field_range.join(" ~ "),
                        },
                      ]
                    : []),
                ]
              : [
                  {
                    key: "coefficient",
                    label: t("aidpKnowledge.ontologyRulesCoefficient"),
                    children:
                      action?.coefficient !== null &&
                      action?.coefficient !== undefined
                        ? String(action.coefficient)
                        : "—",
                  },
                ]),
            {
              key: "created",
              label: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
              children: formatAidpDateTime(rule.created_at),
            },
            {
              key: "updated",
              label: t("aidpKnowledge.ontologyMetadataColumnUpdateTime"),
              children: formatAidpDateTime(rule.updated_at),
            },
          ]}
        />
      )}
    </Drawer>
  );
};

export default AidpOntologyRuleDetailDrawer;
