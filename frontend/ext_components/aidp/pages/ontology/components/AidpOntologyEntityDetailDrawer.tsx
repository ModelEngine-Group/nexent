// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button, Drawer, Tag, Tooltip } from "antd";
import { DeleteOutlined, EditOutlined } from "@ant-design/icons";

import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import type { AidpOntologyEntity } from "@/ext_components/aidp/shared/types/ontology";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import tableStyles from "@/ext_components/aidp/shared/styles/AidpOntologyTable.module.css";
import styles from "./AidpOntologyEntityDetailDrawer.module.css";

interface AidpOntologyEntityDetailDrawerProps {
  open: boolean;
  entity: AidpOntologyEntity | null;
  onClose: () => void;
  onEdit?: (entity: AidpOntologyEntity) => void;
  onDelete?: (entity: AidpOntologyEntity) => void;
}

const relationName = (value: unknown): string => {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(
      record.display_name ??
        record.displayName ??
        record.api_name ??
        record.name ??
        record.id ??
        "—"
    );
  }
  return "—";
};

/** Format an audit value with minutes without inventing a timestamp. */
const formatAuditTime = (value?: string | null): string => {
  if (!value) return "—";
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) {
    return text.slice(0, 16).replace("T", " ");
  }
  return text || "—";
};

const AidpOntologyEntityDetailDrawer: React.FC<
  AidpOntologyEntityDetailDrawerProps
> = ({ open, entity, onClose, onEdit, onDelete }) => {
  const { t } = useTranslation();
  const demo = useAidpOntologyDemoMode();

  const renderRelations = (values: unknown[] | undefined) => {
    if (!values || values.length === 0) {
      return <span className={styles.muted}>—</span>;
    }
    return (
      <div className={tableStyles.metadataTags}>
        {values.map((value, index) => (
          <Tag key={`${relationName(value)}-${index}`}>
            {relationName(value)}
          </Tag>
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
      title={entity ? entity.display_name || entity.api_name : ""}
      extra={
        entity ? (
          <div className={styles.headerActions}>
            <Tooltip title={t("aidpKnowledge.ontologyEdit")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.ontologyEdit")}
                icon={<EditOutlined />}
                onClick={() => onEdit?.(entity)}
              />
            </Tooltip>
            <Tooltip title={t("aidpKnowledge.ontologyDelete")}>
              <Button
                type="text"
                size="small"
                aria-label={t("aidpKnowledge.ontologyDelete")}
                icon={<DeleteOutlined />}
                onClick={() => onDelete?.(entity)}
              />
            </Tooltip>
          </div>
        ) : null
      }
    >
      {entity && (
        <div className={styles.body}>
          <p className={styles.description}>{entity.description || "—"}</p>

          <div className={styles.auditRow}>
            <div className={styles.auditItem}>
              <span className={styles.auditLabel}>
                {t("aidpKnowledge.ontologyMetadataColumnCreateTime")}
              </span>
              <span>{formatAuditTime(entity.create_time)}</span>
            </div>
            <div className={styles.auditItem}>
              <span className={styles.auditLabel}>
                {t("aidpKnowledge.ontologyMetadataColumnUpdateTime")}
              </span>
              <span>{formatAuditTime(entity.update_time)}</span>
            </div>
          </div>

          <section>
            <div className={styles.sectionTitle}>
              {t("aidpKnowledge.ontologyEntityRelations")}
            </div>
            <div className={styles.relationGroup}>
              <span className={styles.relationLabel}>
                {t("aidpKnowledge.ontologyEntityParent")}
              </span>
              {renderRelations(entity.parent_entities)}
            </div>
            <div className={styles.relationGroup}>
              <span className={styles.relationLabel}>
                {t("aidpKnowledge.ontologyEntitySynonym")}
              </span>
              {renderRelations(entity.synonym_entities)}
            </div>
            <div className={styles.relationGroup}>
              <span className={styles.relationLabel}>
                {t("aidpKnowledge.ontologyEntityChild")}
              </span>
              {renderRelations(entity.child_entities)}
            </div>
          </section>

          <section>
            <div className={styles.sectionTitle}>
              {t("aidpKnowledge.ontologyEntityExtended")}
            </div>
            {(entity.properties ?? []).length === 0 ? (
              <span className={styles.muted}>—</span>
            ) : (
              <div className={styles.propertyTags}>
                {(entity.properties ?? []).map((property, index) => (
                  <Tag key={`${property.api_name}-${index}`}>
                    {property.display_name || property.api_name}:{" "}
                    {property.value || "—"}
                  </Tag>
                ))}
              </div>
            )}
          </section>

          <AidpOntologyGapNote>
            {demo
              ? t("aidpKnowledge.ontologyEntityDetailDemoGap")
              : t("aidpKnowledge.ontologyEntityDetailRealGap")}
          </AidpOntologyGapNote>
        </div>
      )}
    </Drawer>
  );
};

export default AidpOntologyEntityDetailDrawer;
