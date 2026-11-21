// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  App,
  Button,
  Drawer,
  Input,
  Skeleton,
  Table,
  type TableColumnsType,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyDomain } from "@/ext_components/aidp/shared/types/ontology";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpKnowledgeOntologyPicker.module.css";

interface AidpKnowledgeOntologyPickerProps {
  open: boolean;
  kdsId: string;
  /** "change" when the KB already has an ontology, "add" otherwise. */
  mode?: "add" | "change";
  onClose: () => void;
  onBound: () => void;
}

const AidpKnowledgeOntologyPicker: React.FC<
  AidpKnowledgeOntologyPickerProps
> = ({ open, kdsId, mode = "add", onClose, onBound }) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const scope = useAidpQueryScope();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedSearch(search.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const query = useQuery({
    queryKey: [...scope.key, "ontology-domain-picker", { page, appliedSearch }],
    queryFn: () => aidpOntologyService.listDomains(page, 20, appliedSearch),
    enabled: scope.enabled && open,
    staleTime: 0,
    retry: false,
  });

  const domains = query.data?.value ?? [];
  const total = query.data?.total_count ?? domains.length;

  const handleBind = async () => {
    if (!selectedId) {
      setErrorMessage(t("aidpKnowledge.ontologyBindingSelectRequired"));
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    try {
      await aidpOntologyService.createBinding(selectedId, kdsId);
      message.success(t("aidpKnowledge.ontologyBindingCreated"));
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

  const columns: TableColumnsType<AidpOntologyDomain> = [
    {
      title: t("aidpKnowledge.ontologyDomainColumnName"),
      dataIndex: "name",
      key: "name",
      width: 180,
      ellipsis: true,
    },
    {
      title: t("aidpKnowledge.ontologyDomainColumnDescription"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (value: string) => value || "—",
    },
  ];

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={640}
      onClose={onClose}
      afterOpenChange={(visible) => {
        if (visible) {
          setSelectedId(null);
          setErrorMessage(null);
        }
      }}
      destroyOnHidden
      title={
        mode === "change"
          ? t("aidpKnowledge.ontologyPickerChangeTitle")
          : t("aidpKnowledge.ontologyPickerAddTitle")
      }
      footer={
        <div className={drawerStyles.footer}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={saving}
            disabled={!selectedId}
            onClick={() => void handleBind()}
          >
            {t("aidpKnowledge.ontologyBindingConfirm")}
          </Button>
        </div>
      }
    >
      <div className={styles.body}>
        <AidpOntologyGapNote>
          {t("aidpKnowledge.ontologyPickerGap")}
        </AidpOntologyGapNote>
        <AidpOntologyGapNote>
          {t("aidpKnowledge.ontologyPickerCountsGap")}
        </AidpOntologyGapNote>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder={t("aidpKnowledge.ontologyDomainSearchPlaceholder")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {query.isLoading ? (
          <Skeleton active paragraph={{ rows: 5 }} />
        ) : (
          <Table<AidpOntologyDomain>
            rowKey="domain_id"
            size="middle"
            columns={columns}
            dataSource={domains}
            pagination={false}
            loading={query.isFetching}
            rowSelection={{
              type: "radio",
              selectedRowKeys: selectedId ? [selectedId] : [],
              onChange: (keys) => setSelectedId(String(keys[0])),
            }}
            onRow={(record) => ({
              onClick: () => setSelectedId(record.domain_id),
            })}
            locale={{
              emptyText: query.isError
                ? getAidpErrorMessage(
                    query.error,
                    t,
                    t("aidpKnowledge.ontologyListLoadFailed")
                  )
                : t("aidpKnowledge.ontologySearchEmpty"),
            }}
          />
        )}
        {domains.length > 0 && (
          <AidpPagination
            currentPage={page}
            pageSize={20}
            pageSizeOptions={[20]}
            total={total}
            totalReliable={query.data?.total_reliable !== false}
            hasMore={query.data?.has_more ?? false}
            showTotal={false}
            onPageChange={setPage}
            onPageSizeChange={() => undefined}
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

export default AidpKnowledgeOntologyPicker;
