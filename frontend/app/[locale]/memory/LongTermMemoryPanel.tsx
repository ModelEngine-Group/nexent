"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Card,
  Empty,
  Flex,
  Input,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { Can } from "@/components/permission/Can";
import {
  activateLongTermVersion,
  fetchLongTermActive,
  fetchLongTermVersion,
  fetchLongTermVersions,
  saveLongTermVersion,
  type LongTermMemoryVersion,
  type LongTermScope,
} from "@/services/memoryService";

const { Text, Title } = Typography;

export function LongTermMemoryPanel({ scope }: { scope: LongTermScope }) {
  const { message, modal } = App.useApp();
  const { t, i18n } = useTranslation("common");
  const [active, setActive] = useState<LongTermMemoryVersion | null>(null);
  const [selected, setSelected] = useState<LongTermMemoryVersion | null>(null);
  const [versions, setVersions] = useState<LongTermMemoryVersion[]>([]);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const dirty = editing && draft !== (active?.content ?? "");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [current, history] = await Promise.all([
        fetchLongTermActive(scope),
        fetchLongTermVersions(scope),
      ]);
      setActive(current.version);
      setSelected(current.version);
      setDraft(current.version?.content ?? "");
      setVersions(history.items);
    } catch {
      setLoadError(true);
      message.error(t("memory.longTerm.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [message, scope, t]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (scope !== "user") return;
    window.addEventListener("user-long-term-memory-updated", load);
    return () =>
      window.removeEventListener("user-long-term-memory-updated", load);
  }, [load, scope]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);

  const choose = async (id: number) => {
    if (dirty && !window.confirm(t("memory.longTerm.discardDraft"))) return;
    const value = await fetchLongTermVersion(scope, id);
    setSelected(value);
    setEditing(false);
    setPreview(false);
  };
  const save = async () => {
    try {
      await saveLongTermVersion(scope, draft, active?.version_id ?? null);
      message.success(t("memory.longTerm.saved"));
      await load();
    } catch {
      message.error(t("memory.longTerm.concurrentError"));
    }
  };
  const activate = async () => {
    if (!selected) return;
    modal.confirm({
      title: t("memory.longTerm.activateConfirm"),
      onOk: async () => {
        await activateLongTermVersion(
          scope,
          selected.version_id,
          active?.version_id ?? null
        );
        await load();
      },
    });
  };
  const controls = (
    <Space>
      {selected && !selected.is_active && (
        <Button onClick={activate}>{t("memory.longTerm.activate")}</Button>
      )}
      {!editing ? (
        <Button
          type="primary"
          onClick={() => {
            setDraft(active?.content ?? "");
            setSelected(active);
            setEditing(true);
          }}
        >
          {t("memory.longTerm.edit")}
        </Button>
      ) : (
        <>
          <Button onClick={() => setPreview((value) => !value)}>
            {preview ? t("memory.longTerm.edit") : t("memory.longTerm.preview")}
          </Button>
          <Button type="primary" onClick={save}>
            {t("memory.longTerm.save")}
          </Button>
          <Button
            onClick={() => {
              setDraft(active?.content ?? "");
              setEditing(false);
              setPreview(false);
              setSelected(active);
            }}
          >
            {t("memory.longTerm.cancel")}
          </Button>
        </>
      )}
    </Space>
  );

  return (
    <div className="panel-body long-term-memory-panel">
      <Flex justify="space-between" align="center">
        <div>
          <Title level={4}>{t(`memory.longTerm.${scope}.title`)}</Title>
          <Text type="secondary">
            {t(`memory.longTerm.${scope}.description`)}
          </Text>
        </div>
        {scope === "tenant" ? (
          <Can permission="mem.tenant:create">{controls}</Can>
        ) : (
          controls
        )}
      </Flex>
      <Flex
        className="long-term-version-row"
        align="center"
        justify="space-between"
        gap={16}
        wrap="wrap"
      >
        <Select
          style={{ width: 320 }}
          className="long-term-version-selector"
          placeholder={t("memory.longTerm.versionHistory")}
          value={selected?.version_id}
          onChange={choose}
          options={versions.map((v) => ({
            value: v.version_id,
            label: `V${v.version_no} · ${t(`memory.longTerm.source.${v.source}`)} · ${new Date(
              v.authored_at
            ).toLocaleString(i18n.resolvedLanguage)}`,
          }))}
        />
        {selected && (
          <Space wrap>
            <Tag color={selected.is_active ? "green" : "default"}>
              {selected.is_active
                ? t("memory.longTerm.active")
                : t("memory.longTerm.history")}
            </Tag>
            <Tag>{t(`memory.longTerm.source.${selected.source}`)}</Tag>
            {Boolean(selected.fallback_details?.used) && (
              <Tag color="orange">{t("memory.longTerm.fallback")}</Tag>
            )}
            <Text type="secondary">
              {new Date(selected.authored_at).toLocaleString(
                i18n.resolvedLanguage
              )}
            </Text>
          </Space>
        )}
      </Flex>
      <Card className="long-term-memory-card" loading={loading}>
        {editing ? (
          preview ? (
            <div className="long-term-memory-scroll">
              <MarkdownRenderer content={draft} />
            </div>
          ) : (
            <div className="long-term-memory-editor-shell">
              <Input.TextArea
                aria-label={t("memory.longTerm.editorLabel")}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="long-term-memory-editor"
                maxLength={10000}
                showCount
              />
            </div>
          )
        ) : loadError ? (
          <Empty
            description={t("memory.longTerm.loadFailed")}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button onClick={() => void load()}>
              {t("memory.longTerm.retry")}
            </Button>
          </Empty>
        ) : selected?.content ? (
          <div className="long-term-memory-scroll">
            <MarkdownRenderer content={selected.content} />
          </div>
        ) : (
          <Empty description={t("memory.longTerm.empty")} />
        )}
      </Card>
    </div>
  );
}
