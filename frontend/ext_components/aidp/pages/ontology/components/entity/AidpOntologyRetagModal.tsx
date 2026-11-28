// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Empty, Modal, Skeleton } from "antd";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import type { AidpOntologyBinding } from "@/ext_components/aidp/shared/types/ontology";
import styles from "./AidpOntologyRetagModal.module.css";

const PAGE_STEP = 50;

interface AidpOntologyRetagModalProps {
  open: boolean;
  domainId: string;
  onClose: () => void;
  onSubmitted: () => void;
}

/**
 * Retag the knowledge bases bound to one ontology domain.
 *
 * The backend binding list only contains KBs the caller can edit, so selecting
 * every row by default is safe. The list is rendered incrementally because a
 * domain may be bound to many KBs.
 */
const AidpOntologyRetagModal: React.FC<AidpOntologyRetagModalProps> = ({
  open,
  domainId,
  onClose,
  onSubmitted,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const scope = useAidpQueryScope();
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState(PAGE_STEP);
  const [saving, setSaving] = useState(false);
  const initialized = useRef(false);

  const bindingsQuery = useQuery({
    queryKey: [...scope.key, "ontology-bindings", domainId],
    queryFn: () => aidpOntologyService.listBindings(domainId),
    enabled: scope.enabled && open,
    staleTime: 0,
    retry: false,
  });

  const bindings = useMemo(
    () => bindingsQuery.data?.value ?? [],
    [bindingsQuery.data]
  );

  useEffect(() => {
    if (!open) {
      initialized.current = false;
      return;
    }
    if (bindingsQuery.data && !initialized.current) {
      setSelectedKeys(
        new Set(bindingsQuery.data.value.map((item) => item.kds_id))
      );
      setVisibleCount(PAGE_STEP);
      initialized.current = true;
    }
  }, [bindingsQuery.data, open]);

  const allSelected =
    bindings.length > 0 && selectedKeys.size === bindings.length;
  const someSelected = selectedKeys.size > 0 && !allSelected;

  const toggleAll = (checked: boolean) => {
    setSelectedKeys(
      checked ? new Set(bindings.map((item) => item.kds_id)) : new Set()
    );
  };

  const toggleOne = (binding: AidpOntologyBinding, checked: boolean) => {
    setSelectedKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(binding.kds_id);
      else next.delete(binding.kds_id);
      return next;
    });
  };

  const handleSubmit = async () => {
    const kbIds = Array.from(selectedKeys).map(Number);
    if (kbIds.length === 0) return;
    setSaving(true);
    try {
      await aidpOntologyService.syncOntologyTags(kbIds);
      message.success(t("aidpKnowledge.chunkRetagSubmitted"));
      onSubmitted();
      onClose();
    } catch (error) {
      message.error(
        getAidpErrorMessage(error, t, t("aidpKnowledge.chunkRetagFailed"))
      );
    } finally {
      setSaving(false);
    }
  };

  const handleScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    if (
      visibleCount < bindings.length &&
      element.scrollTop + element.clientHeight >= element.scrollHeight - 24
    ) {
      setVisibleCount((current) =>
        Math.min(current + PAGE_STEP, bindings.length)
      );
    }
  };

  const renderBody = () => {
    if (bindingsQuery.isLoading) {
      return <Skeleton active paragraph={{ rows: 5 }} />;
    }
    if (bindingsQuery.isError) {
      return (
        <Alert
          type="error"
          showIcon
          title={getAidpErrorMessage(
            bindingsQuery.error,
            t,
            t("aidpKnowledge.ontologyBindingLoadFailed")
          )}
        />
      );
    }
    if (bindings.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("aidpKnowledge.ontologyRetagEmpty")}
        />
      );
    }
    return (
      <>
        <div className={styles.summary}>
          <Checkbox
            checked={allSelected}
            indeterminate={someSelected}
            onChange={(event) => toggleAll(event.target.checked)}
          >
            {t("aidpKnowledge.chunksSelectAll")}
          </Checkbox>
          <span>
            {t("aidpKnowledge.ontologyRetagSelected", {
              selected: selectedKeys.size,
              total: bindings.length,
            })}
          </span>
        </div>
        <div className={styles.list} onScroll={handleScroll}>
          {bindings.slice(0, visibleCount).map((binding) => (
            <label className={styles.row} key={binding.kds_id}>
              <Checkbox
                checked={selectedKeys.has(binding.kds_id)}
                onChange={(event) =>
                  toggleOne(binding, event.target.checked)
                }
              />
              <span className={styles.name}>
                {binding.kds_name || binding.kds_id}
              </span>
            </label>
          ))}
        </div>
      </>
    );
  };

  return (
    <Modal
      open={open}
      title={t("aidpKnowledge.ontologyRetagTitle")}
      centered
      width={640}
      destroyOnHidden
      mask={{ closable: !saving }}
      onCancel={() => {
        if (!saving) onClose();
      }}
      footer={
        <div className={styles.footer}>
          <Button onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            loading={saving}
            disabled={selectedKeys.size === 0}
            onClick={() => void handleSubmit()}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <Alert
        type="info"
        showIcon
        title={t("aidpKnowledge.ontologyRetagHint", {
          count: selectedKeys.size,
        })}
      />
      {renderBody()}
    </Modal>
  );
};

export default AidpOntologyRetagModal;
