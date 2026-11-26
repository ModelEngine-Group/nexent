// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button, Descriptions, Drawer, Tag, Tooltip } from "antd";
import { DeleteOutlined, EditOutlined } from "@ant-design/icons";

import type { AidpOntologyEntity } from "@/ext_components/aidp/shared/types/ontology";
import { aidpRelationName } from "@/ext_components/aidp/shared/utils/aidpRelationDisplay";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import { formatAidpDateTime } from "@/ext_components/aidp/shared/utils/aidpTime";
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

const propertyTypeLabel = (
  value: string | undefined,
  t: (key: string) => string
): string => {
  switch (value) {
    case "str":
    case "string":
      return t("aidpKnowledge.ontologyMetadataTypeText");
    case "float":
      return t("aidpKnowledge.ontologyMetadataTypeNumber");
    case "datetime":
      return t("aidpKnowledge.ontologyMetadataTypeDate");
    case "list[str]":
      return t("aidpKnowledge.ontologyEntityPropertyTypeMultiText");
    default:
      return value || "—";
  }
};

const AidpOntologyEntityDetailDrawer: React.FC<
  AidpOntologyEntityDetailDrawerProps
> = ({ open, entity, onClose, onEdit, onDelete }) => {
  const { t } = useTranslation();
  const properties = (entity?.properties ?? []).filter(
    (property) => property.api_name !== "synonym"
  );

  const renderRelations = (values: unknown[] | undefined) => {
    if (!values || values.length === 0) {
      return <span className={styles.muted}>—</span>;
    }
    return (
      <div className={tableStyles.metadataTags}>
        {values.map((value, index) => (
          <Tag key={`${aidpRelationName(value)}-${index}`}>
            {aidpRelationName(value)}
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
        <>
          <AidpOntologyGapNote>
            {t("aidpKnowledge.ontologyEntityRelationScanGap")}
          </AidpOntologyGapNote>
          <Descriptions
            size="small"
            column={1}
            bordered
            items={[
              {
                key: "description",
                label: t("aidpKnowledge.ontologyEntityDescription"),
                children: entity.description || "—",
              },
              {
                key: "created",
                label: t("aidpKnowledge.ontologyMetadataColumnCreateTime"),
                children: formatAidpDateTime(entity.create_time),
              },
              {
                key: "updated",
                label: t("aidpKnowledge.ontologyMetadataColumnUpdateTime"),
                children: formatAidpDateTime(entity.update_time),
              },
              {
                key: "parents",
                label: t("aidpKnowledge.ontologyEntityParent"),
                children: renderRelations(entity.parent_entities),
              },
              {
                key: "synonyms",
                label: t("aidpKnowledge.ontologyEntitySynonym"),
                children: renderRelations(entity.synonym_entities),
              },
              {
                key: "children",
                label: t("aidpKnowledge.ontologyEntityChild"),
                children: renderRelations(entity.child_entities),
              },
              {
                key: "properties",
                label: t("aidpKnowledge.ontologyEntityExtended"),
                children:
                  properties.length === 0 ? (
                    "—"
                  ) : (
                    <div className={styles.propertyTable}>
                      <div className={styles.propertyTableHeader}>
                        <span>
                          {t("aidpKnowledge.ontologyEntityPropertyName")}
                        </span>
                        <span>
                          {t("aidpKnowledge.ontologyEntityPropertyType")}
                        </span>
                        <span>
                          {t("aidpKnowledge.ontologyEntityPropertyValue")}
                        </span>
                        <span>
                          {t("aidpKnowledge.ontologyEntityPropertyRange")}
                        </span>
                      </div>
                      {properties.map((property, index) => (
                        <div
                          key={`${property.api_name}-${index}`}
                          className={styles.propertyTableRow}
                        >
                          <span>
                            {property.display_name || property.api_name}
                          </span>
                          <span>
                            {propertyTypeLabel(property.data_type, t)}
                          </span>
                          <span>{property.value || "—"}</span>
                          <span>{property.range || "—"}</span>
                        </div>
                      ))}
                    </div>
                  ),
              },
            ]}
          />
        </>
      )}
    </Drawer>
  );
};

export default AidpOntologyEntityDetailDrawer;
