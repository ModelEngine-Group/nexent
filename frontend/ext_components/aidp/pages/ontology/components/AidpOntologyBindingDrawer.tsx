// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  App,
  Button,
  Drawer,
  Skeleton,
  Table,
  type TableColumnsType,
} from "antd";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import AidpOntologyFieldLabel from "@/ext_components/aidp/shared/components/AidpOntologyFieldLabel";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import styles from "./AidpOntologyBindingDrawer.module.css";

interface AidpOntologyBindingDrawerProps {
  open: boolean;
  domainId: string;
  onClose: () => void;
  onBound: () => void;
}

const AidpOntologyBindingDrawer: React.FC<AidpOntologyBindingDrawerProps> = ({
  open,
  domainId,
  onClose,
  onBound,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const scope = useAidpQueryScope();
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const kbQuery = useQuery({
    queryKey: [...scope.key, "ontology-binding-kb-options"],
    queryFn: () => aidpKnowledgeService.listKbs(1, 100),
    enabled: scope.enabled && open,
    staleTime: 30_000,
    retry: false,
  });

  const bindingsQuery = useQuery({
    queryKey: [...scope.key, "ontology-all-bindings"],
    queryFn: () => aidpOntologyService.listAllBindings(),
    enabled: scope.enabled && open,
    staleTime: 0,
    retry: false,
  });

  const boundKbIds = useMemo(
    () => new Set((bindingsQuery.data?.value ?? []).map((item) => item.kds_id)),
    [bindingsQuery.data?.value]
  );

  const candidates = useMemo(
    () =>
      (kbQuery.data?.value ?? []).filter((kb) => !boundKbIds.has(kb.kds_id)),
    [boundKbIds, kbQuery.data?.value]
  );

  const handleClose = () => {
    setSelectedKeys([]);
    setErrorMessage(null);
    setSaving(false);
    onClose();
  };

  const handleSubmit = async () => {
    if (selectedKeys.length === 0) {
      setErrorMessage(t("aidpKnowledge.ontologyBindingSelectRequired"));
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    try {
      const outcomes = await Promise.allSettled(
        selectedKeys.map((kdsId) =>
          aidpOntologyService.createBinding(domainId, String(kdsId))
        )
      );
      const failed = outcomes.filter(
        (outcome) => outcome.status === "rejected"
      ).length;
      if (failed > 0) {
        setErrorMessage(
          t("aidpKnowledge.ontologyBindingBatchPartial", { count: failed })
        );
        setSelectedKeys([]);
        onBound();
        return;
      }
      message.success(t("aidpKnowledge.ontologyBindingCreated"));
      handleClose();
      onBound();
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.ontologyBindingCreateFailed")
        )
      );
    } finally {
      setSaving(false);
    }
  };

  const columns: TableColumnsType<AidpKnowledgeBaseItem> = [
    {
      title: t("aidpKnowledge.ontologyBindingColumnKbName"),
      dataIndex: "kds_name",
      key: "kds_name",
      width: 240,
      ellipsis: true,
    },
    {
      title: t("aidpKnowledge.ontologyBindingColumnDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (value: string | null | undefined) =>
        value || <span className={styles.muted}>—</span>,
    },
  ];

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={720}
      onClose={handleClose}
      destroyOnHidden
      title={t("aidpKnowledge.ontologyBindingAddTitle")}
      footer={
        <div className={drawerStyles.footer}>
          <Button onClick={handleClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={saving}
            disabled={selectedKeys.length === 0}
            onClick={() => void handleSubmit()}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <div className={styles.body}>
        <div className={styles.label}>
          <AidpOntologyFieldLabel
            label={t("aidpKnowledge.ontologyBindingSelectLabel")}
            help={t("aidpKnowledge.ontologyBindingSelectHelp")}
            required
          />
        </div>
        <AidpOntologyGapNote>
          {t("aidpKnowledge.ontologyBindingCandidateScanGap")}
        </AidpOntologyGapNote>
        {kbQuery.isLoading || bindingsQuery.isLoading ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : (
          <Table<AidpKnowledgeBaseItem>
            rowKey="kds_id"
            size="middle"
            columns={columns}
            dataSource={candidates}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            rowSelection={{
              selectedRowKeys: selectedKeys,
              onChange: setSelectedKeys,
            }}
            locale={{
              emptyText: kbQuery.isError
                ? getAidpErrorMessage(
                    kbQuery.error,
                    t,
                    t("aidpKnowledge.ontologyBindKbLoadFailed")
                  )
                : t("aidpKnowledge.ontologyBindNoKb"),
            }}
          />
        )}
        {bindingsQuery.isError && (
          <div className={drawerStyles.error} role="alert">
            {t("aidpKnowledge.ontologyBindingFilterGap")}
          </div>
        )}
        {errorMessage && (
          <div className={drawerStyles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </div>
    </Drawer>
  );
};

export default AidpOntologyBindingDrawer;
