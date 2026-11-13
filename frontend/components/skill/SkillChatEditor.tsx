// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App, Button, Form, Input, Segmented, Select } from "antd";
import { Maximize2, Minimize2, PanelRightClose, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import {
  createSkill,
  fetchSkillById,
  updateSkillById,
} from "@/services/agentConfigService";
import { fetchMyEditableSkills } from "@/services/skillRepositoryService";
import { tagManagementApi } from "@/services/tagManagementService";
import SkillCreationFiles from "@/components/skill/SkillCreationFiles";
import SkillGroupSelection from "@/components/skill/SkillGroupSelection";
import SkillTypeIcon from "@/components/repository/skill/components/SkillTypeIcon";
import { isValidSkillDraftPath } from "@/lib/skillCreationDraft";
import type { SkillChatPayload } from "@/lib/skillChatDraft";
import type { SkillFileContent } from "@/types/skill";
import log from "@/lib/logger";

interface EditorDraft {
  name: string;
  description: string;
  files: SkillFileContent[];
  group_ids: number[];
  ingroup_permission: "EDIT" | "READ_ONLY" | "PRIVATE";
  tag_value_ids: number[];
  sourceTags: string[];
  skillId: number | null;
  fingerprint: string;
  dirty: boolean;
  aclTouched: boolean;
  tagsTouched: boolean;
}

export default function SkillChatEditor({
  scopeKey,
  payload,
  rawFiles,
  running,
  open,
  selectedPath,
  onClose,
  onNew,
  onDraftChange,
  onSaved,
  onBusyChange,
}: {
  scopeKey: string;
  payload: SkillChatPayload | null;
  rawFiles: Record<string, string>;
  running: boolean;
  open: boolean;
  selectedPath?: string;
  onClose: () => void;
  onNew: () => void;
  onDraftChange: (payload: SkillChatPayload) => void;
  onSaved: (payload: SkillChatPayload) => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const { user, hasPermission, getAccessibleGroupIds } =
    useAuthorizationContext();
  const accessible = getAccessibleGroupIds();
  const {
    data: groups,
    isLoading: groupsLoading,
    isError: groupsError,
    refetch: refreshGroups,
  } = useGroupList(user?.tenantId ?? null);
  const {
    data: libraries,
    loading: librariesLoading,
    error: librariesError,
    refresh: refreshLibraries,
  } = useTagLibraries();
  const bucket = libraries?.find(
    (item) => item.bucket_key === "default_resource"
  );
  const {
    data: definitions,
    loading: tagsLoading,
    error: tagsError,
    refresh: refreshTags,
  } = useTagDefinitions(bucket?.bucket_id ?? null);
  const values = useMemo(
    () =>
      (definitions ?? [])
        .filter((definition) => definition.status === "active")
        .flatMap((definition) =>
          (definition.values ?? [])
            .filter((value) => value.status === "active")
            .map((value) => ({ ...value, definition }))
        ),
    [definitions]
  );
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<EditorDraft | null>(null);
  const draftRef = useRef<EditorDraft | null>(null);
  const [tab, setTab] = useState("configure");
  const [maximized, setMaximized] = useState(false);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [cacheError, setCacheError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lookup, setLookup] = useState<"checking" | "ready" | "error">(
    "checking"
  );
  const [lookupVersion, setLookupVersion] = useState(0);
  const [hydrated, setHydrated] = useState(false);
  const fingerprint = payload ? JSON.stringify(payload) : "";
  const incoming = useRef({ payload, fingerprint, accessible });
  incoming.current = { payload, fingerprint, accessible };
  const valuesRef = useRef(values);
  valuesRef.current = values;
  const wasRunning = useRef(running);
  const storageKey = `nexent:repository:skill-editor:v1:${scopeKey}`;
  const setCurrent = (next: EditorDraft | null) => {
    draftRef.current = next;
    setDraft(next);
  };
  const asPayload = (current: EditorDraft): SkillChatPayload => ({
    name: current.name,
    description: current.description,
    source: "custom",
    tags: current.tagsTouched
      ? valuesRef.current
          .filter((value) => current.tag_value_ids.includes(value.value_id))
          .map((value) => value.display_value)
      : current.sourceTags,
    content:
      current.files.find((file) => file.path === "SKILL.md")?.content ?? "",
    files: current.files
      .filter((file) => file.path !== "SKILL.md")
      .map(({ path, content }) => ({ path, content })),
  });
  const seed = (source: SkillChatPayload, key: string): EditorDraft => ({
    name: source.name,
    description: source.description,
    files: [{ path: "SKILL.md", content: source.content }, ...source.files],
    group_ids: incoming.current.accessible,
    ingroup_permission: "READ_ONLY",
    tag_value_ids: [],
    sourceTags: source.tags,
    skillId: null,
    fingerprint: key,
    dirty: false,
    aclTouched: false,
    tagsTouched: false,
  });
  useEffect(() => {
    let restored: EditorDraft | null = null;
    try {
      const cached = sessionStorage.getItem(storageKey);
      const parsed = cached ? JSON.parse(cached) : null;
      const value = parsed?.draft;
      if (
        value &&
        typeof value.name === "string" &&
        typeof value.description === "string" &&
        typeof value.fingerprint === "string" &&
        typeof value.dirty === "boolean" &&
        typeof value.aclTouched === "boolean" &&
        typeof value.tagsTouched === "boolean" &&
        Array.isArray(value.files) &&
        value.files.every(
          (file: SkillFileContent) =>
            file &&
            typeof file.path === "string" &&
            typeof file.content === "string" &&
            isValidSkillDraftPath(file.path)
        ) &&
        Array.isArray(value.group_ids) &&
        value.group_ids.every(Number.isSafeInteger) &&
        Array.isArray(value.tag_value_ids) &&
        value.tag_value_ids.every(Number.isSafeInteger) &&
        Array.isArray(value.sourceTags) &&
        value.sourceTags.every((tag: unknown) => typeof tag === "string") &&
        ["EDIT", "READ_ONLY", "PRIVATE"].includes(value.ingroup_permission) &&
        (value.skillId === null ||
          (Number.isSafeInteger(value.skillId) && value.skillId > 0))
      ) {
        restored = value;
        setSavedAt(typeof parsed.savedAt === "string" ? parsed.savedAt : null);
      }
    } catch {
      setCacheError(true);
    }
    const source = incoming.current;
    const next =
      restored ??
      (source.payload ? seed(source.payload, source.fingerprint) : null);
    setCurrent(next);
    if (next) form.setFieldsValue(next);
    if (restored?.dirty && !running) onDraftChange(asPayload(restored));
    setHydrated(true);
    // The component is keyed by user, tenant and thread; initialize once per mounted scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, form]);
  useEffect(() => {
    if (!hydrated) return;
    const current = draftRef.current;
    const finished = wasRunning.current && !running;
    wasRunning.current = running;
    const source = incoming.current;
    if (
      !source.payload ||
      running ||
      current?.fingerprint === source.fingerprint
    )
      return;
    if (current?.dirty && !finished) return;
    const next = seed(source.payload, source.fingerprint);
    if (current?.name === next.name) {
      next.skillId = current.skillId;
      next.group_ids = current.group_ids;
      next.ingroup_permission = current.ingroup_permission;
      next.aclTouched = current.aclTouched;
      if (current.tagsTouched) {
        next.tag_value_ids = current.tag_value_ids;
        next.tagsTouched = true;
      }
    }
    setCurrent(next);
    form.setFieldsValue(next);
    // Stream updates must not replace a dirty local draft unless that generation just finished.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint, running, hydrated, form]);
  useEffect(() => {
    const current = draftRef.current;
    if (!current || current.tagsTouched || tagsLoading) return;
    const seen = new Set<number>();
    const ids = values
      .filter((value) => {
        if (
          !current.sourceTags.some(
            (tag) => tag.toLowerCase() === value.display_value.toLowerCase()
          )
        )
          return false;
        if (
          value.definition.selection_mode === "single_select" &&
          seen.has(value.definition.definition_id)
        )
          return false;
        seen.add(value.definition.definition_id);
        return true;
      })
      .map((value) => value.value_id);
    if (JSON.stringify(ids) === JSON.stringify(current.tag_value_ids)) return;
    const next = { ...current, tag_value_ids: ids };
    setCurrent(next);
    form.setFieldValue("tag_value_ids", ids);
  }, [values, tagsLoading, fingerprint, hydrated, form]);
  useEffect(() => {
    if (!hydrated || !draft) return;
    const persist = (notify: boolean) => {
      try {
        const time = new Date().toISOString();
        sessionStorage.setItem(
          storageKey,
          JSON.stringify({ draft, savedAt: time })
        );
        if (notify) {
          setSavedAt(time);
          setCacheError(false);
        }
      } catch {
        if (notify) setCacheError(true);
      }
    };
    const timer = setTimeout(() => persist(true), 400);
    return () => {
      clearTimeout(timer);
      persist(false);
    };
  }, [draft, hydrated, storageKey]);
  useEffect(() => {
    if (!hydrated || !incoming.current.payload || running) return;
    let cancelled = false;
    setLookup("checking");
    void (async () => {
      try {
        const cachedId = draftRef.current?.skillId;
        let found: {
          skill_id: number;
          group_ids?: number[];
          ingroup_permission?: string | null;
        } | null = null;
        if (cachedId) {
          const response = await fetchSkillById(cachedId);
          if (!response.success || !response.data)
            throw new Error(response.message);
          found = response.data;
        } else {
          for (let page = 1; ; page += 1) {
            const result = await fetchMyEditableSkills({
              ownership: "created",
              search: incoming.current.payload!.name,
              page,
              page_size: 100,
              new_skill_padding: false,
            });
            const item = result.items.find(
              (item) =>
                "skill_id" in item &&
                item.name === incoming.current.payload?.name
            );
            if (item && "skill_id" in item) {
              found = item;
              break;
            }
            if (page >= result.pagination.total_pages) break;
          }
        }
        if (cancelled) return;
        const current = draftRef.current;
        if (current && found) {
          const next = { ...current, skillId: found.skill_id };
          if (!current.aclTouched) {
            next.group_ids = found.group_ids ?? current.group_ids;
            next.ingroup_permission = ["EDIT", "READ_ONLY", "PRIVATE"].includes(
              found.ingroup_permission ?? ""
            )
              ? (found.ingroup_permission as EditorDraft["ingroup_permission"])
              : current.ingroup_permission;
          }
          setCurrent(next);
          form.setFieldsValue({
            group_ids: next.group_ids,
            ingroup_permission: next.ingroup_permission,
          });
        }
        setLookup("ready");
      } catch {
        if (!cancelled) setLookup("error");
      }
    })();
    return () => {
      cancelled = true;
    };
    // Resolve persisted resources for this generated version without rerunning on each local edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, fingerprint, running, lookupVersion, form]);
  const change = (fields: Partial<EditorDraft>) => {
    const current = draftRef.current;
    if (!current) return;
    const next = { ...current, ...fields, dirty: true };
    setCurrent(next);
    onDraftChange(asPayload(next));
  };
  const save = async () => {
    const current = draftRef.current;
    if (!current || busy.current || running || lookup !== "ready") return;
    busy.current = true;
    onBusyChange?.(true);
    setSaving(true);
    setError(null);
    try {
      await form.validateFields();
      if (current.files.some((file) => !isValidSkillDraftPath(file.path)))
        throw new Error(t("skillCreation.invalidPath"));
      const data = asPayload({ ...current, tagsTouched: true });
      const acl = {
        group_ids: current.group_ids,
        ingroup_permission: current.ingroup_permission,
      };
      let id = current.skillId;
      if (id) {
        const result = await updateSkillById(id, {
          ...data,
          tags: undefined,
          ...(current.aclTouched ? acl : {}),
        });
        if (!result.success) throw new Error(result.message);
      } else {
        const result = await createSkill({ ...data, tags: [], ...acl });
        if (!result.success) throw new Error(result.message);
        id = Number(result.data?.skill_id);
        if (!Number.isSafeInteger(id) || id <= 0) {
          setLookup("error");
          throw new Error(t("skillCreation.missingCreatedId"));
        }
        setCurrent({ ...current, skillId: id, tagsTouched: true });
      }
      if (!current.skillId || current.tagsTouched)
        await tagManagementApi.replaceAssignments("skill", String(id), {
          value_ids: current.tag_value_ids,
        });
      setCurrent({
        ...current,
        sourceTags: data.tags,
        skillId: id,
        dirty: false,
        aclTouched: false,
      });
      onSaved(data);
      message.success(t("ui.localization.skillSaved"));
    } catch (caught) {
      if (caught && typeof caught === "object" && "errorFields" in caught)
        setTab("configure");
      else {
        log.error("Failed to save skill creation draft", caught);
        setError(
          caught instanceof Error
            ? caught.message
            : t("ui.localization.skillSaveFailed")
        );
      }
    } finally {
      busy.current = false;
      onBusyChange?.(false);
      setSaving(false);
    }
  };
  const unavailable = running || saving || !hasPermission("skill:create");
  const visibleFiles =
    draft?.files ??
    Object.entries(rawFiles).map(([path, content]) => ({ path, content }));
  const unmatchedTags = (draft?.sourceTags ?? []).filter(
    (tag) =>
      !values.some(
        (value) => value.display_value.toLowerCase() === tag.toLowerCase()
      )
  );
  return (
    <section
      aria-label={t("skillChat.title")}
      className={`${open ? "flex" : "hidden"} ${maximized ? "fixed inset-4 z-50 rounded-lg border shadow-xl" : "min-h-[600px] w-full border-t lg:min-h-0 lg:w-1/2 lg:border-t-0 lg:border-l"} min-w-0 flex-col bg-[#FAFAFA]`}
    >
      <div className="flex h-14 shrink-0 items-center gap-2 border-b bg-white px-4">
        <span className="flex min-w-0 items-center gap-2 rounded bg-[#F3F3F3] px-3 py-2 text-sm">
          <span className="truncate">
            {draft?.name || payload?.name || t("skillChat.untitled")}
          </span>
          <Button
            type="text"
            size="small"
            aria-label={t("common.close")}
            icon={<X size={14} />}
            onClick={() => {
              setMaximized(false);
              onClose();
            }}
          />
        </span>
        <Button
          type="text"
          disabled={unavailable}
          icon={<Plus size={16} />}
          aria-label={t("skillChat.newSkill")}
          onClick={onNew}
        />
        <div className="ml-auto flex items-center gap-1">
          <Button
            type="text"
            aria-label={t("skillChat.expand")}
            icon={maximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            onClick={() => setMaximized(!maximized)}
          />
          <Button
            type="text"
            aria-label={t("skillChat.collapse")}
            icon={<PanelRightClose size={16} />}
            onClick={() => {
              setMaximized(false);
              onClose();
            }}
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 p-4">
        <SkillTypeIcon
          name={draft?.name || payload?.name || ""}
          tags={payload?.tags}
        />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-medium">
            {draft?.name || t("skillChat.untitled")}
          </h2>
          <p className="text-xs text-[#777777]">
            {cacheError
              ? t("skillChat.localSaveFailed")
              : savedAt
                ? t("skillChat.localSavedAt", {
                    time: new Date(savedAt).toLocaleTimeString(),
                  })
                : t("skillChat.localDraft")}
          </p>
        </div>
        <Segmented
          value={tab}
          onChange={(value) => setTab(String(value))}
          options={[
            { value: "configure", label: t("skillCreation.parameters") },
            { value: "groups", label: t("skillCreation.groups") },
          ]}
        />
        <Button
          type="primary"
          className="!border-[#191919] !bg-[#191919]"
          loading={saving}
          disabled={
            unavailable ||
            !draft ||
            lookup !== "ready" ||
            groupsLoading ||
            groupsError ||
            tagsLoading ||
            librariesLoading ||
            Boolean(tagsError || librariesError)
          }
          onClick={save}
        >
          {t("common.confirm")}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
        {running && (
          <Alert
            type="info"
            title={t("skillChat.generating")}
            className="mb-3"
          />
        )}
        {!draft && (
          <Alert
            type="info"
            title={t("skillChat.waitDraft")}
            className="mb-3"
          />
        )}
        {error && <Alert type="error" title={error} className="mb-3" />}
        {(tagsError || librariesError) && (
          <Alert
            type="error"
            title={t("skillChat.tagsFailed")}
            action={
              <Button
                onClick={() => {
                  void refreshLibraries();
                  void refreshTags();
                }}
              >
                {t("repository.common.retry")}
              </Button>
            }
            className="mb-3"
          />
        )}
        {lookup === "error" && (
          <Alert
            type="warning"
            title={t("skillChat.lookupFailed")}
            action={
              <Button onClick={() => setLookupVersion((value) => value + 1)}>
                {t("repository.common.retry")}
              </Button>
            }
            className="mb-3"
          />
        )}
        {draft?.dirty &&
          payload &&
          draft.fingerprint !== fingerprint &&
          !running && (
            <Alert
              type="info"
              title={t("skillChat.newVersion")}
              action={
                <Button
                  onClick={() =>
                    modal.confirm({
                      title: t("skillChat.useGenerated"),
                      content: t("skillCreation.discardDraft"),
                      onOk: () => {
                        const next = seed(payload, fingerprint);
                        if (next.name === draftRef.current?.name)
                          next.skillId = draftRef.current.skillId;
                        setCurrent(next);
                        setLookupVersion((value) => value + 1);
                        form.setFieldsValue(next);
                        onDraftChange(asPayload(next));
                      },
                    })
                  }
                >
                  {t("skillChat.useGenerated")}
                </Button>
              }
              className="mb-3"
            />
          )}
        <Form
          form={form}
          layout="vertical"
          disabled={unavailable || !draft}
          onValuesChange={(changed, all) =>
            change({
              ...all,
              aclTouched: Boolean(
                draft?.aclTouched ||
                "group_ids" in changed ||
                "ingroup_permission" in changed
              ),
              tagsTouched: Boolean(
                draft?.tagsTouched || "tag_value_ids" in changed
              ),
            })
          }
        >
          <div
            hidden={tab !== "configure"}
            className="space-y-4 rounded-lg bg-white p-4"
          >
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
              <Input />
            </Form.Item>
            <Form.Item label={t("skillManagement.form.source")}>
              <Select
                value="custom"
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
                options={values.map((value) => ({
                  value: value.value_id,
                  label:
                    value.display_value || value.definition.definition_name,
                }))}
                onChange={(ids: number[]) => {
                  const added = ids.find(
                    (id) => !draft?.tag_value_ids.includes(id)
                  );
                  const single = values.find(
                    (value) =>
                      value.value_id === added &&
                      value.definition.selection_mode === "single_select"
                  )?.definition;
                  if (single) {
                    const nextIds = ids.filter(
                      (id) =>
                        id === added ||
                        !single.values?.some((value) => value.value_id === id)
                    );
                    form.setFieldValue("tag_value_ids", nextIds);
                    change({ tag_value_ids: nextIds, tagsTouched: true });
                  }
                }}
              />
            </Form.Item>
            {!!unmatchedTags.length &&
              !draft?.tagsTouched &&
              !tagsLoading &&
              !librariesLoading && (
                <Alert
                  type="warning"
                  title={t("skillCreation.unmatchedTags", {
                    tags: unmatchedTags.join(", "),
                  })}
                />
              )}
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
              <Input.TextArea rows={4} maxLength={1000} showCount />
            </Form.Item>
            <h3 className="mb-2 text-sm">
              {t("skillRepository.detail.skillFiles")}
            </h3>
            <SkillCreationFiles
              files={visibleFiles}
              selectedPath={selectedPath}
              onChange={(files) => change({ files })}
              disabled={unavailable || !draft}
            />
          </div>
          <div hidden={tab !== "groups"} className="rounded-lg bg-white p-4">
            <Form.Item
              name="ingroup_permission"
              label={t("skillCreation.groupPermission")}
            >
              <Select
                options={(["EDIT", "READ_ONLY", "PRIVATE"] as const).map(
                  (value) => ({
                    value,
                    label: t(
                      `tenantResources.knowledgeBase.permission.${value}`
                    ),
                  })
                )}
              />
            </Form.Item>
            <Form.Item name="group_ids" label={t("skillCreation.selectGroups")}>
              <SkillGroupSelection
                groups={(groups?.groups ?? []).filter((group) =>
                  accessible.includes(group.group_id)
                )}
                loading={groupsLoading}
                isError={groupsError}
                disabled={unavailable || !draft}
                onRetry={() => {
                  void refreshGroups();
                }}
              />
            </Form.Item>
          </div>
        </Form>
      </div>
    </section>
  );
}
