// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Drawer, Empty, Skeleton, Tag } from "antd";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyChunkDetailDrawer.module.css";

interface AidpOntologyChunkDetailDrawerProps {
  open: boolean;
  kdsId: string;
  chunkId: string | number | null;
  onClose: () => void;
}

const AidpOntologyChunkDetailDrawer: React.FC<
  AidpOntologyChunkDetailDrawerProps
> = ({ open, kdsId, chunkId, onClose }) => {
  const { t } = useTranslation();
  const scope = useAidpQueryScope();

  const query = useQuery({
    queryKey: [...scope.key, "ontology-chunk", kdsId, chunkId],
    queryFn: () =>
      aidpOntologyService.getChunk(kdsId, chunkId as string | number),
    enabled: scope.enabled && open && !!kdsId && chunkId !== null,
    staleTime: 0,
    retry: false,
  });

  const chunk = query.data;
  const metadataEntries = Object.entries(chunk?.metadata ?? {});

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={560}
      onClose={onClose}
      destroyOnHidden
      title={t("aidpKnowledge.ontologyChunkDetailTitle")}
    >
      {query.isLoading && <Skeleton active paragraph={{ rows: 5 }} />}
      {query.isError && (
        <div className={drawerStyles.error} role="alert">
          {getAidpErrorMessage(
            query.error,
            t,
            t("aidpKnowledge.ontologyChunkDetailLoadFailed")
          )}
        </div>
      )}
      {chunk && (
        <div className={styles.body}>
          <dl className={styles.meta}>
            <div>
              <dt>{t("aidpKnowledge.ontologyChunkId")}</dt>
              <dd>{chunk.chunk_id}</dd>
            </div>
            <div>
              <dt>{t("aidpKnowledge.ontologyChunkType")}</dt>
              <dd>
                <Tag className={styles.tag}>{chunk.chunk_type || "—"}</Tag>
              </dd>
            </div>
            <div>
              <dt>{t("aidpKnowledge.ontologyChunkFileName")}</dt>
              <dd>{chunk.file_name || "—"}</dd>
            </div>
            <div>
              <dt>{t("aidpKnowledge.ontologyChunkPageIds")}</dt>
              <dd>
                {chunk.page_ids?.length ? chunk.page_ids.join(", ") : "—"}
              </dd>
            </div>
          </dl>
          <section>
            <h3 className={styles.sectionTitle}>
              {t("aidpKnowledge.ontologyChunkText")}
            </h3>
            <div className={styles.textBlock}>{chunk.chunk_text || "—"}</div>
          </section>
          <section>
            <h3 className={styles.sectionTitle}>
              {t("aidpKnowledge.ontologyChunkMetadata")}
            </h3>
            {metadataEntries.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("aidpKnowledge.ontologyChunkMetadataEmpty")}
              />
            ) : (
              <table className={styles.metadataTable}>
                <thead>
                  <tr>
                    <th>{t("aidpKnowledge.ontologyMetadataFieldName")}</th>
                    <th>{t("aidpKnowledge.ontologyChunkMetadataValue")}</th>
                  </tr>
                </thead>
                <tbody>
                  {metadataEntries.map(([key, value]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td>{String(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
};

export default AidpOntologyChunkDetailDrawer;
