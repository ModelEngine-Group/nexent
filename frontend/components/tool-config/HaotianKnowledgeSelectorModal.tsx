"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Modal, Card, Checkbox, Input, Spin, Typography, Divider } from "antd";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

export interface HaotianKnowledgeBase {
  dify_dataset_id: string;
  name: string;
}

export interface HaotianKnowledgeSet {
  name: string;
  knowledge_bases: HaotianKnowledgeBase[];
}

export default function HaotianKnowledgeSelectorModal(props: {
  isOpen: boolean;
  title?: string;
  isLoading?: boolean;
  knowledgeSets: HaotianKnowledgeSet[];
  selectedDatasetIds: string[];
  onClose: () => void;
  onConfirm: (selected: { datasetIds: string[]; displayNames: string[] }) => void;
}) {
  const {
    isOpen,
    title,
    isLoading = false,
    knowledgeSets,
    selectedDatasetIds,
    onClose,
    onConfirm,
  } = props;
  const { t } = useTranslation("common");

  const [tempSelectedIds, setTempSelectedIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (isOpen) setTempSelectedIds(selectedDatasetIds || []);
  }, [isOpen, selectedDatasetIds]);

  const filteredSets = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return knowledgeSets;
    return knowledgeSets
      .map((set) => {
        const bases = (set.knowledge_bases || []).filter((kb) =>
          String(kb.name || "").toLowerCase().includes(keyword)
        );
        if (String(set.name || "").toLowerCase().includes(keyword)) {
          return set;
        }
        return { ...set, knowledge_bases: bases };
      })
      .filter((set) => (set.knowledge_bases || []).length > 0);
  }, [knowledgeSets, search]);

  const idToName = useMemo(() => {
    const m = new Map<string, string>();
    for (const ks of knowledgeSets) {
      for (const kb of ks.knowledge_bases || []) {
        m.set(String(kb.dify_dataset_id), String(kb.name));
      }
    }
    return m;
  }, [knowledgeSets]);

  return (
    <Modal
      title={title || t("toolConfig.knowledgeBaseSelector.title.datamate")}
      open={isOpen}
      onCancel={onClose}
      onOk={() => {
        const displayNames = tempSelectedIds
          .map((id) => idToName.get(String(id)) || String(id))
          .filter(Boolean);
        onConfirm({ datasetIds: tempSelectedIds, displayNames });
      }}
      width={900}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
    >
      <Input
        placeholder={t("knowledgeBase.search.placeholder") || "Search"}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: 12 }}
      />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <div style={{ maxHeight: 560, overflow: "auto" }}>
          {filteredSets.map((set) => (
            <Card
              key={set.name}
              title={<Text strong>{set.name}</Text>}
              style={{ marginBottom: 12 }}
              size="small"
            >
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                  {(set.knowledge_bases || []).map((kb) => (
                    <Checkbox
                      key={kb.dify_dataset_id}
                      checked={tempSelectedIds.includes(String(kb.dify_dataset_id))}
                      onChange={(e) => {
                        const id = String(kb.dify_dataset_id);
                        if (e.target.checked) {
                          setTempSelectedIds((prev) =>
                            prev.includes(id) ? prev : [...prev, id]
                          );
                        } else {
                          setTempSelectedIds((prev) => prev.filter((x) => x !== id));
                        }
                      }}
                    >
                      {kb.name}
                    </Checkbox>
                  ))}
                </div>
              <Divider style={{ margin: "12px 0 0" }} />
              <Text type="secondary">
                {t("knowledgeBase.total") || "Total"}:{" "}
                {(set.knowledge_bases || []).length}
              </Text>
            </Card>
          ))}
          {filteredSets.length === 0 && (
            <Text type="secondary">
              {t("knowledgeBase.empty") || "No knowledge bases found."}
            </Text>
          )}
        </div>
      )}
    </Modal>
  );
}

