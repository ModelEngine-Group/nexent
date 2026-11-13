// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App, Button, Form, Input, Select, Steps } from "antd";
import { FileUp, SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import {
  createSkill,
  createSkillFromFile,
  updateSkillById,
} from "@/services/agentConfigService";
import { tagManagementApi } from "@/services/tagManagementService";
import { parseSkillCreationFile } from "@/lib/skillCreationDraft";
import { getTenantResourceLimitMessage } from "@/const/errorMessageI18n";
import type { SkillFileContent } from "@/types/skill";
import SkillCreationFiles from "./SkillCreationFiles";
import SkillGroupSelection from "./SkillGroupSelection";
import log from "@/lib/logger";

interface CreationValues {
  name: string;
  description: string;
  source: string;
  group_ids: number[];
  ingroup_permission: "EDIT" | "READ_ONLY" | "PRIVATE";
  tag_value_ids: number[];
}

export default function SkillCreateModal({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void | Promise<void>;
}) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const [form] = Form.useForm<CreationValues>();
  const { user, getAccessibleGroupIds } = useAuthorizationContext();
  const accessible = getAccessibleGroupIds();
  const accessibleKey = accessible.join(",");
  const {
    data: groupData,
    isLoading: groupsLoading,
    isError: groupsError,
    refetch: refreshGroups,
  } = useGroupList(user?.tenantId ?? null);
  const { data: libraries } = useTagLibraries();
  const bucket = libraries?.find(
    (library) => library.bucket_key === "default_resource"
  );
  const { data: definitions, loading: tagsLoading } = useTagDefinitions(
    bucket?.bucket_id ?? null
  );
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<"manual" | "import">("manual");
  const [files, setFiles] = useState<SkillFileContent[]>([
    { path: "SKILL.md", content: "" },
  ]);
  const [file, setFile] = useState<File | null>(null);
  const [parsed, setParsed] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createdId, setCreatedId] = useState<number | null>(null);
  const [creationUnconfirmed, setCreationUnconfirmed] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [unmatchedTags, setUnmatchedTags] = useState<string[]>([]);
  const opened = useRef(false);
  const savingRef = useRef(false);
  const parseGeneration = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const previousTags = useRef<number[]>([]);
  const tagsAttempted = useRef(false);
  const activeDefinitions = useMemo(
    () =>
      (definitions ?? []).filter(
        (definition) => definition.status === "active"
      ),
    [definitions]
  );
  useEffect(() => {
    if (open && !opened.current) {
      form.resetFields();
      form.setFieldsValue({
        name: "",
        description: "",
        source: "custom",
        group_ids: accessibleKey ? accessibleKey.split(",").map(Number) : [],
        ingroup_permission: "READ_ONLY",
        tag_value_ids: [],
      });
      setStep(0);
      setMode("manual");
      setFiles([{ path: "SKILL.md", content: "" }]);
      setFile(null);
      setParsed(false);
      setParsing(false);
      setCreatedId(null);
      setCreationUnconfirmed(false);
      setSaveError(null);
      setUnmatchedTags([]);
      previousTags.current = [];
      tagsAttempted.current = false;
    }
    if (!open) parseGeneration.current += 1;
    opened.current = open;
  }, [open, form, accessibleKey]);
  const changeMode = (value: "manual" | "import") => {
    if (value === mode || savingRef.current || createdId || creationUnconfirmed)
      return;
    const apply = () => {
      parseGeneration.current += 1;
      setParsing(false);
      setParsed(false);
      setFile(null);
      setFiles([{ path: "SKILL.md", content: "" }]);
      form.setFieldsValue({ name: "", description: "", tag_value_ids: [] });
      previousTags.current = [];
      setUnmatchedTags([]);
      setMode(value);
      setSaveError(null);
    };
    if (
      parsed ||
      form.getFieldValue("name") ||
      form.getFieldValue("description") ||
      files.some((entry) => entry.content || entry.status === "unsupported")
    ) {
      modal.confirm({
        title: t("skillCreation.switchMode"),
        content: t("skillCreation.discardDraft"),
        centered: true,
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: apply,
      });
    } else apply();
  };
  const selectFile = (next: File | undefined) => {
    if (!next) return;
    parseGeneration.current += 1;
    setParsing(false);
    setParsed(false);
    setFile(next);
    setSaveError(null);
  };
  const parse = async () => {
    if (!file || savingRef.current) return;
    const generation = ++parseGeneration.current;
    setParsing(true);
    setParsed(false);
    setSaveError(null);
    try {
      const draft = await parseSkillCreationFile(file);
      if (generation !== parseGeneration.current) return;
      form.setFieldsValue({
        name: draft.name,
        description: draft.description,
        source: "custom",
      });
      let matched = activeDefinitions.flatMap((definition) =>
        (definition.values ?? [])
          .filter(
            (value) =>
              value.status === "active" &&
              draft.tags.some(
                (tag) =>
                  tag.trim().toLowerCase() ===
                  value.display_value.trim().toLowerCase()
              )
          )
          .map((value) => value.value_id)
      );
      for (const definition of activeDefinitions.filter(
        (item) => item.selection_mode === "single_select"
      )) {
        const selected = matched.filter((id) =>
          definition.values?.some((value) => value.value_id === id)
        );
        if (selected.length > 1)
          matched = matched.filter(
            (id) =>
              !selected.includes(id) || id === selected[selected.length - 1]
          );
      }
      previousTags.current = matched;
      form.setFieldValue("tag_value_ids", matched);
      setUnmatchedTags(
        draft.tags.filter(
          (tag) =>
            !activeDefinitions.some((definition) =>
              definition.values?.some(
                (value) =>
                  value.status === "active" &&
                  value.display_value.trim().toLowerCase() ===
                    tag.trim().toLowerCase()
              )
            )
        )
      );
      setFiles(draft.files);
      setParsed(true);
    } catch (error) {
      log.error("Failed to parse skill import", error);
      if (generation === parseGeneration.current)
        setSaveError(t("skillCreation.parseFailed"));
    } finally {
      if (generation === parseGeneration.current) setParsing(false);
    }
  };
  const next = async () => {
    if (mode === "import" && !parsed) {
      setSaveError(t("skillCreation.parseFirst"));
      return;
    }
    try {
      await form.validateFields(["name", "description"]);
      setStep(1);
    } catch {
      /* Ant Design displays validation errors beside the fields. */
    }
  };
  const save = async () => {
    if (
      savingRef.current ||
      creationUnconfirmed ||
      groupsLoading ||
      groupsError
    )
      return;
    savingRef.current = true;
    setSaving(true);
    setSaveError(null);
    try {
      const values = await form.validateFields();
      const primary = files.find((entry) => entry.path === "SKILL.md");
      if (!primary) throw new Error(t("skillCreation.missingPrimary"));
      const data = {
        name: values.name.trim(),
        description: values.description.trim(),
        source: "custom",
        content: primary.content,
        group_ids: values.group_ids ?? [],
        ingroup_permission: values.ingroup_permission,
        files: files
          .filter(
            (entry) =>
              entry.path !== "SKILL.md" &&
              entry.status !== "unsupported" &&
              entry.status !== "read_error"
          )
          .map(({ path, content }) => ({ path, content })),
      };
      let id = createdId;
      if (!id) {
        const result =
          mode === "import" && file && /\.zip$/i.test(file.name)
            ? await createSkillFromFile(data.name, file, false)
            : await createSkill({ ...data, tags: [] });
        if (!result.success) throw result.error || new Error(result.message);
        id = Number(result.data?.skill_id);
        if (!Number.isSafeInteger(id) || id <= 0) {
          setCreationUnconfirmed(true);
          throw new Error(t("skillCreation.missingCreatedId"));
        }
        setCreatedId(id);
      }
      // Imported archives keep their binary assets; update only metadata and readable draft files.
      if (
        (mode === "import" && file && /\.zip$/i.test(file.name)) ||
        createdId
      ) {
        const updated = await updateSkillById(id, data);
        if (!updated.success) throw new Error(updated.message);
      }
      if (values.tag_value_ids?.length || tagsAttempted.current) {
        tagsAttempted.current = true;
        await tagManagementApi.replaceAssignments("skill", String(id), {
          value_ids: values.tag_value_ids ?? [],
        });
      }
      await onSuccess();
      message.success(t("skillManagement.message.createSuccess"));
      onClose();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error)
        setStep(0);
      else {
        log.error("Failed to create repository skill", error);
        setSaveError(
          getTenantResourceLimitMessage(error, t) ||
            (error instanceof Error
              ? error.message
              : t("skillManagement.message.submitFailed"))
        );
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };
  const close = () => {
    parseGeneration.current += 1;
    if (createdId || creationUnconfirmed) void onSuccess();
    onClose();
  };
  return (
    <Modal
      centered
      open={open}
      closable={{ "aria-label": t("common.close") }}
      onCancel={() => {
        if (!savingRef.current) close();
      }}
      width={860}
      styles={{
        body: { maxHeight: "calc(100dvh - 200px)", overflowY: "auto" },
      }}
      title={t("skillCreation.title")}
      cancelText={t("common.cancel")}
      okText={t("common.confirm")}
      footer={
        <div className="flex justify-end gap-2">
          <Button disabled={saving} onClick={close}>
            {t("common.cancel")}
          </Button>
          {step === 1 && (
            <Button disabled={saving} onClick={() => setStep(0)}>
              {t("skillCreation.previous")}
            </Button>
          )}
          <Button
            type="primary"
            loading={saving}
            disabled={
              creationUnconfirmed ||
              parsing ||
              (mode === "import" && !parsed) ||
              (step === 1 && (groupsLoading || groupsError))
            }
            onClick={step === 0 ? next : save}
          >
            {t(step === 0 ? "skillCreation.next" : "common.confirm")}
          </Button>
        </div>
      }
    >
      <Steps
        current={step}
        size="small"
        titlePlacement="vertical"
        className="mb-6"
        items={[
          { title: t("skillCreation.parameters") },
          { title: t("skillCreation.groups") },
        ]}
      />
      {saveError && (
        <Alert type="error" showIcon title={saveError} className="mb-4" />
      )}
      {createdId && (
        <Alert
          type="info"
          showIcon
          title={t("skillCreation.partialCreated")}
          className="mb-4"
        />
      )}
      <Form form={form} layout="vertical" disabled={saving}>
        <div hidden={step !== 0}>
          <div className="mb-6 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(["manual", "import"] as const).map((value) => {
              const Icon = value === "manual" ? SquarePen : FileUp;
              return (
                <button
                  key={value}
                  type="button"
                  disabled={saving || Boolean(createdId) || creationUnconfirmed}
                  aria-pressed={mode === value}
                  onClick={() => changeMode(value)}
                  className={`flex min-h-[72px] items-center gap-4 rounded border bg-white p-4 text-left disabled:opacity-60 ${mode === value ? "border-[#0067D1]" : "border-[#D9D9D9]"}`}
                >
                  <Icon
                    className="size-8 shrink-0 text-violet-500"
                    aria-hidden
                  />
                  <span>
                    <strong className="block text-sm font-medium">
                      {t(`skillCreation.${value}`)}
                    </strong>
                    <span className="text-xs text-[#777777]">
                      {t(`skillCreation.${value}Hint`)}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
          {mode === "import" && (
            <div className="mb-6 space-y-2">
              <label className="block text-sm">
                {t("skillCreation.uploadFile")}
              </label>
              <div className="flex gap-2">
                <Input
                  readOnly
                  value={file?.name ?? ""}
                  placeholder={t("skillManagement.form.uploadHint")}
                />
                <Button
                  disabled={saving || Boolean(createdId) || creationUnconfirmed}
                  onClick={() => input.current?.click()}
                >
                  {t("skillCreation.addFile")}
                </Button>
                <Button
                  type="primary"
                  disabled={!file || saving || Boolean(createdId)}
                  loading={parsing}
                  onClick={parse}
                >
                  {t("skillCreation.parseFile")}
                </Button>
              </div>
              <input
                ref={input}
                type="file"
                accept=".md,.zip"
                className="hidden"
                aria-label={t("skillCreation.uploadFile")}
                onChange={(event) => {
                  selectFile(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
              <p className="text-xs text-[#777777]">
                {t("skillCreation.uploadOnConfirm")}
              </p>
              {parsed && (
                <h3 className="text-sm font-medium">
                  {t("skillCreation.parseResult")}
                </h3>
              )}
            </div>
          )}
          <div hidden={mode === "import" && !parsed}>
            <Form.Item
              name="name"
              label={t("skillManagement.form.name")}
              rules={[
                {
                  required: true,
                  whitespace: true,
                  message: t("skillManagement.form.nameRequired"),
                },
              ]}
            >
              <Input
                disabled={saving || Boolean(createdId) || creationUnconfirmed}
                placeholder={t("skillManagement.form.namePlaceholder")}
              />
            </Form.Item>
            <Form.Item name="source" label={t("skillManagement.form.source")}>
              <Select
                options={[
                  { value: "custom", label: t("skillPool.group.custom") },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="tag_value_ids"
              label={t("skillManagement.form.tags")}
            >
              <Select
                mode="multiple"
                allowClear
                loading={tagsLoading}
                options={activeDefinitions.map((definition) => ({
                  label: definition.definition_name,
                  options: (definition.values ?? [])
                    .filter((value) => value.status === "active")
                    .map((value) => ({
                      value: value.value_id,
                      label: value.display_value || definition.definition_name,
                    })),
                }))}
                onChange={(nextValues: number[]) => {
                  const added = nextValues.find(
                    (id) => !previousTags.current.includes(id)
                  );
                  const single = activeDefinitions.find(
                    (definition) =>
                      definition.selection_mode === "single_select" &&
                      definition.values?.some(
                        (value) => value.value_id === added
                      )
                  );
                  const ids = single
                    ? nextValues.filter(
                        (id) =>
                          id === added ||
                          !single.values?.some((value) => value.value_id === id)
                      )
                    : nextValues;
                  previousTags.current = ids;
                  form.setFieldValue("tag_value_ids", ids);
                }}
              />
            </Form.Item>
            <Form.Item
              name="description"
              label={t("skillManagement.form.description")}
              rules={[
                {
                  required: true,
                  whitespace: true,
                  message: t("skillManagement.form.descriptionRequired"),
                },
                { max: 1000 },
              ]}
            >
              <Input.TextArea
                showCount
                maxLength={1000}
                rows={4}
                placeholder={t("skillManagement.form.descriptionPlaceholder")}
              />
            </Form.Item>
            {unmatchedTags.length > 0 && (
              <Alert
                type="info"
                title={t("skillCreation.unmatchedTags", {
                  tags: unmatchedTags.join(", "),
                })}
                className="mb-4"
              />
            )}
            <section className="space-y-2">
              <h3 className="text-sm font-normal">
                {t("skillRepository.detail.skillFiles")}
              </h3>
              <SkillCreationFiles
                key={`${open}:${file?.name ?? "manual"}:${parsed}`}
                files={files}
                onChange={setFiles}
                disabled={saving}
              />
            </section>
          </div>
        </div>
        <div hidden={step !== 1}>
          <Form.Item
            name="ingroup_permission"
            label={t("skillCreation.groupPermission")}
          >
            <Select
              options={(["EDIT", "READ_ONLY", "PRIVATE"] as const).map(
                (value) => ({
                  value,
                  label: t(`tenantResources.knowledgeBase.permission.${value}`),
                })
              )}
            />
          </Form.Item>
          <Form.Item name="group_ids" label={t("skillCreation.selectGroups")}>
            <SkillGroupSelection
              key={open ? "open" : "closed"}
              groups={(groupData?.groups ?? []).filter((group) =>
                accessible.includes(group.group_id)
              )}
              loading={groupsLoading}
              disabled={saving}
              isError={groupsError}
              onRetry={() => {
                void refreshGroups();
              }}
            />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
