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

  // One KB can bind to only one ontology/jargon library. The KB list already
  // carries that binding, so candidates need no all-bindings scan. AIDP uses
  // 0 (or "0") for "unbound", so only a real non-zero id means already bound.
  const candidates = useMemo(
    () =>
      (kbQuery.data?.value ?? []).filter((kb) => {
        const type = kb.bind_lib_type;
        const boundId = kb.bind_lib_id;
        const hasBinding =
          type === "ontology" ||
          type === "jargon" ||
          (boundId !== null &&
            boundId !== undefined &&
            String(boundId).trim() !== "0");
        return !hasBinding;
      }),
    [kbQuery.data?.value]
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
      const failures = outcomes.filter(
        (outcome): outcome is PromiseRejectedResult =>
          outcome.status === "rejected"
      );
      if (failures.length > 0) {
        const detail = getAidpErrorMessage(
          failures[0].reason,
          t,
          t("aidpKnowledge.ontologyBindingCreateFailed")
        );
        setErrorMessage(
          `${t("aidpKnowledge.ontologyBindingBatchFailed", {
            count: failures.length,
          })}${detail ? `：${detail}` : ""}`
        );
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
        {kbQuery.isLoading ? (
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
