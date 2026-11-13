// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { App, Button } from "antd";
import { useTranslation } from "react-i18next";
import { StandardModal } from "@/components/common/StandardModal";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Nl2SkillChatPanel } from "@/app/newchat/assistant-ui/nl2skill-chat-panel";
import {
  applySkillCreationEvent,
  buildEditedSkillFiles,
  buildSkillSavePayload,
  initialSkillCreationDraft,
  type SkillCreationEvent,
  type SkillChatPayload,
} from "@/lib/skillChatDraft";
import SkillChatEditor from "./SkillChatEditor";
import SkillTypeIcon from "@/components/repository/skill/components/SkillTypeIcon";
import log from "@/lib/logger";

export default function SkillChatCreateModal({
  open,
  onClose,
  onSuccess,
  onOpenSkill,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void | Promise<void>;
  onOpenSkill: (name: string) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const { message, modal } = App.useApp();
  const { user } = useAuthorizationContext();
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [draft, setDraft] = useState(initialSkillCreationDraft);
  const draftRef = useRef(initialSkillCreationDraft);
  const [edited, setEdited] = useState<SkillChatPayload | null>(null);
  const [savedName, setSavedName] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [editorOpen, setEditorOpen] = useState(true);
  const [selectedPath, setSelectedPath] = useState("SKILL.md");
  const checkpoint = useRef(initialSkillCreationDraft);
  const scopeKey = `${user?.tenantId ?? ""}:${user?.id ?? ""}:repository-chat:${sessionId}`;
  const generated = useMemo(() => buildSkillSavePayload(draft), [draft]);
  const artifact = edited ?? generated;
  const getDraftSnapshot = useCallback(
    () => ({
      ...(buildSkillSavePayload(draftRef.current) ?? {}),
      files: Object.entries(draftRef.current.files).map(([path, content]) => ({
        path,
        content,
      })),
    }),
    []
  );
  const handleEvent = useCallback(
    (event: SkillCreationEvent) => {
      if (event.type === "agent_new_run") {
        checkpoint.current = draftRef.current;
        setRunning(true);
        setEdited(null);
      }
      if (["step_count", "skill_body", "file_content"].includes(event.type))
        setRunning(true);
      let next = applySkillCreationEvent(draftRef.current, event);
      if (
        event.type === "error" ||
        (event.type === "stream_closed" && !next.complete)
      ) {
        next = checkpoint.current;
      }
      draftRef.current = next;
      setDraft(next);
      if (["skill_body", "file_content"].includes(event.type)) {
        setDirty(true);
        setSavedName(null);
      }
      if (["done", "error", "stream_closed"].includes(event.type))
        setRunning(false);
      if (event.type === "error")
        message.error(t("skillManagement.message.chatError"));
    },
    [message, t]
  );
  const clearCache = () => {
    try {
      sessionStorage.removeItem(
        `nexent:repository:skill-editor:v1:${scopeKey}`
      );
    } catch {
      log.warn("Could not remove closed skill creation draft");
    }
  };
  const confirmDiscard = (action: () => void) => {
    if (running || saving) {
      message.warning(t("skillChat.waitForCompletion"));
      return;
    }
    if (dirty) {
      modal.confirm({
        title: t("skillChat.discardTitle"),
        content: t("skillChat.discardDescription"),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: action,
      });
    } else action();
  };
  const close = () =>
    confirmDiscard(() => {
      clearCache();
      onClose();
    });
  const newSession = () =>
    confirmDiscard(() => {
      clearCache();
      setSessionId(crypto.randomUUID());
      draftRef.current = initialSkillCreationDraft;
      checkpoint.current = initialSkillCreationDraft;
      setDraft(initialSkillCreationDraft);
      setEdited(null);
      setSavedName(null);
      setDirty(false);
      setSelectedPath("SKILL.md");
      setEditorOpen(true);
    });
  return (
    <StandardModal
      open={open}
      title={t("skillChat.title")}
      closeLabel={t("common.close")}
      cancelText={t("common.cancel")}
      confirmText={t("common.confirm")}
      onOpenChange={(next) => {
        if (!next) close();
      }}
      width="min(1800px, calc(100vw - 48px))"
      height="calc(100dvh - 64px)"
      bodyClassName="!max-h-none min-h-0 flex-1 !overflow-hidden !p-0"
      footer={null}
      closeOnEscape={!running && !saving}
    >
      <div className="flex h-full min-h-0 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
        <section
          inert={saving}
          className={`flex min-h-[460px] min-w-0 flex-col gap-3 p-3 lg:min-h-0 ${editorOpen ? "lg:w-1/2" : "flex-1"}`}
          aria-label={t("skillChat.conversation")}
        >
          {!editorOpen && (
            <Button onClick={() => setEditorOpen(true)}>
              {t("skillChat.open")}
            </Button>
          )}
          <div className="min-h-0 flex-1">
            <Nl2SkillChatPanel
              key={sessionId}
              getDraftSnapshot={getDraftSnapshot}
              onStreamEvent={handleEvent}
              language={i18n.language?.startsWith("en") ? "en" : "zh"}
              availableFiles={Object.entries(draft.files).map(
                ([path, content]) => ({ path, content })
              )}
              onSkillFileSelect={(path) => {
                setSelectedPath(path);
                setEditorOpen(true);
              }}
            />
          </div>
          {artifact && !running && (
            <div className="shrink-0 rounded-xl bg-[#F5F5F5] p-4">
              <h3 className="mb-3 text-sm font-semibold">
                {t("skillChat.summary")}
              </h3>
              <div className="flex items-start gap-3">
                <SkillTypeIcon name={artifact.name} tags={artifact.tags} />
                <div className="min-w-0 flex-1">
                  <h4 className="truncate font-medium">{artifact.name}</h4>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {artifact.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-[#EAEAEA] px-2 py-0.5 text-xs"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
                <Button
                  type="text"
                  size="small"
                  onClick={() => {
                    if (savedName === artifact.name)
                      confirmDiscard(() => {
                        clearCache();
                        onOpenSkill(artifact.name);
                      });
                    else setEditorOpen(true);
                  }}
                >
                  {t(
                    savedName === artifact.name
                      ? "skillChat.openRepository"
                      : "skillChat.open"
                  )}
                </Button>
              </div>
              <p className="mt-3 line-clamp-2 text-xs leading-5 text-[#777777]">
                {artifact.description}
              </p>
            </div>
          )}
        </section>
        <SkillChatEditor
          key={sessionId}
          scopeKey={scopeKey}
          payload={generated}
          rawFiles={draft.files}
          running={running}
          open={editorOpen}
          selectedPath={selectedPath}
          onClose={() => setEditorOpen(false)}
          onNew={newSession}
          onBusyChange={setSaving}
          onDraftChange={(payload) => {
            draftRef.current = {
              ...draftRef.current,
              files: buildEditedSkillFiles(payload),
              complete: true,
              started: true,
            };
            setEdited(payload);
            setDirty(true);
          }}
          onSaved={(payload) => {
            setEdited(payload);
            setSavedName(payload.name);
            setDirty(false);
            void Promise.resolve()
              .then(onSuccess)
              .catch((error) =>
                log.error("Failed to refresh saved skills", error)
              );
          }}
        />
      </div>
    </StandardModal>
  );
}
