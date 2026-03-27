"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Table,
  Tag,
  App,
  Modal,
  Input,
  Tooltip,
  Form,
  Switch,
  InputNumber,
} from "antd";
import { ColumnsType } from "antd/es/table";
import { Settings } from "lucide-react";

import {
  fetchSkillsList,
  updateSkill,
  type SkillListItem,
} from "@/services/skillService";
import log from "@/lib/logger";

function pathToKey(path: (string | number)[]): string {
  return path.map(String).join(".");
}

/**
 * YAML documentation keys (e.g. `_comment`) are not shown in the form.
 * Tooltips for human-readable notes use only the inline `value # comment` string pattern.
 * These keys are still preserved on save via `deepMergePreserveUnderscore` (underscore merge).
 */
const YAML_DOC_KEYS_HIDDEN_FROM_FORM = new Set<string>(["_comment"]);

/** True when the field key (last path segment) is internal, e.g. `_schema_version`. */
function isLockedKeyPath(namePath: (string | number)[]): boolean {
  if (namePath.length === 0) return false;
  const last = namePath[namePath.length - 1];
  if (typeof last !== "string" || !last.startsWith("_")) return false;
  if (YAML_DOC_KEYS_HIDDEN_FROM_FORM.has(last)) return false;
  return true;
}

/** Editable keys first, then `_` keys, alphabetical within each group. */
function sortParamObjectEntries(entries: [string, unknown][]): [string, unknown][] {
  return [...entries].sort(([a], [b]) => {
    const au = a.startsWith("_");
    const bu = b.startsWith("_");
    if (au !== bu) return au ? 1 : -1;
    return a.localeCompare(b);
  });
}

/** Arrays of only strings, numbers, booleans, or null — shown as one comma/newline input. */
function isPrimitiveArray(arr: unknown[]): boolean {
  if (arr.length === 0) return true;
  return arr.every(
    (x) =>
      x === null ||
      typeof x === "string" ||
      typeof x === "number" ||
      typeof x === "boolean"
  );
}

function primitiveArrayToListInput(arr: unknown[]): string {
  return arr
    .map((v) => {
      if (v === null) return "null";
      return String(v);
    })
    .join(", ");
}

function coercePrimitiveToken(token: string, hint?: unknown): unknown {
  if (hint !== undefined) {
    if (hint === null && token === "null") return null;
    if (typeof hint === "number") {
      const n = Number(token);
      return Number.isNaN(n) ? token : n;
    }
    if (typeof hint === "boolean") {
      if (/^true$/i.test(token)) return true;
      if (/^false$/i.test(token)) return false;
      return token;
    }
    if (typeof hint === "string") return token;
  }
  if (token === "null") return null;
  if (/^true$/i.test(token)) return true;
  if (/^false$/i.test(token)) return false;
  if (/^-?\d+(?:\.\d+)?$/.test(token)) {
    const n = Number(token);
    if (!Number.isNaN(n)) return n;
  }
  return token;
}

/** Parse one input string back to a primitive JSON array (for save). */
function parseListInputToPrimitiveArray(input: string, hint?: unknown[]): unknown[] {
  const s = input.trim();
  if (!s) return [];
  if (s.startsWith("[")) {
    try {
      const parsed = JSON.parse(s) as unknown;
      if (Array.isArray(parsed) && isPrimitiveArray(parsed)) {
        return parsed;
      }
    } catch {
      /* fall through to split */
    }
  }
  const tokens = s
    .split(/[,\n]/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  return tokens.map((t, i) => coercePrimitiveToken(t, hint?.[i]));
}

/**
 * Form stores primitive arrays as a single string; merge back to real arrays before save.
 */
function restorePrimitiveArraysFromForm(edited: unknown, snapshot: unknown): unknown {
  if (edited === null || edited === undefined) return edited;
  if (snapshot === null || snapshot === undefined) return edited;

  if (Array.isArray(snapshot) && isPrimitiveArray(snapshot)) {
    if (typeof edited === "string") {
      return parseListInputToPrimitiveArray(edited, snapshot);
    }
    return edited;
  }

  if (
    typeof snapshot === "object" &&
    !Array.isArray(snapshot) &&
    typeof edited === "object" &&
    edited !== null &&
    !Array.isArray(edited)
  ) {
    const snap = snapshot as Record<string, unknown>;
    const out = { ...(edited as Record<string, unknown>) };
    for (const k of Object.keys(out)) {
      if (Object.prototype.hasOwnProperty.call(snap, k)) {
        out[k] = restorePrimitiveArraysFromForm(out[k], snap[k]);
      }
    }
    return out;
  }

  if (Array.isArray(snapshot) && Array.isArray(edited) && !isPrimitiveArray(snapshot)) {
    return edited.map((e, i) => restorePrimitiveArraysFromForm(e, snapshot[i]));
  }

  return edited;
}

/** Split "value # comment" for tooltip (first ` # ` only). */
function parseStringWithComment(s: string): { display: string; comment?: string } {
  const idx = s.indexOf(" # ");
  if (idx === -1) return { display: s };
  return { display: s.slice(0, idx), comment: s.slice(idx + 3) };
}

function joinStringWithComment(display: string, comment?: string): string {
  if (comment === undefined || comment === "") return display;
  return `${display} # ${comment}`;
}

/**
 * Build form initial values (includes `_` prefixed keys for read-only display, except YAML doc keys)
 * and collect inline string comment tooltips via ` # ` (see `parseStringWithComment`).
 */
function buildFormStateFromParams(
  obj: unknown,
  path: (string | number)[] = [],
  meta: Map<string, string> = new Map()
): { initialValues: unknown } {
  if (obj === null || obj === undefined) {
    return { initialValues: obj };
  }
  if (typeof obj === "string") {
    const { display, comment } = parseStringWithComment(obj);
    if (comment !== undefined) {
      meta.set(pathToKey(path), comment);
    }
    return { initialValues: display };
  }
  if (typeof obj === "number" || typeof obj === "boolean") {
    return { initialValues: obj };
  }
  if (Array.isArray(obj)) {
    if (isPrimitiveArray(obj)) {
      return { initialValues: primitiveArrayToListInput(obj) };
    }
    return {
      initialValues: obj.map((item, i) => buildFormStateFromParams(item, [...path, i], meta).initialValues),
    };
  }
  if (typeof obj === "object" && !Array.isArray(obj)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      if (YAML_DOC_KEYS_HIDDEN_FROM_FORM.has(k)) continue;
      out[k] = buildFormStateFromParams(v, [...path, k], meta).initialValues;
    }
    return { initialValues: out };
  }
  return { initialValues: obj };
}

function applyStringComments(
  obj: unknown,
  meta: Map<string, string>,
  path: (string | number)[] = []
): unknown {
  if (typeof obj === "string") {
    const key = pathToKey(path);
    const comment = meta.get(key);
    return joinStringWithComment(obj, comment);
  }
  if (Array.isArray(obj)) {
    return obj.map((item, i) => applyStringComments(item, meta, [...path, i]));
  }
  if (obj !== null && typeof obj === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      out[k] = applyStringComments(v, meta, [...path, k]);
    }
    return out;
  }
  return obj;
}

/**
 * Merge edited form values back into the original snapshot, preserving `_` keys and nested `_` keys.
 * When `edited` omits a nested object, still merges from snapshot so internal `_` keys are kept.
 */
function deepMergePreserveUnderscore(snapshot: unknown, edited: unknown): unknown {
  if (Array.isArray(snapshot) && Array.isArray(edited)) {
    const out = [...edited];
    for (let i = 0; i < snapshot.length; i++) {
      const sv = snapshot[i];
      const ev = out[i];
      if (ev === undefined) continue;
      if (
        typeof sv === "object" &&
        sv !== null &&
        !Array.isArray(sv) &&
        typeof ev === "object" &&
        ev !== null &&
        !Array.isArray(ev)
      ) {
        out[i] = deepMergePreserveUnderscore(sv, ev);
      } else if (Array.isArray(sv) && Array.isArray(ev)) {
        out[i] = deepMergePreserveUnderscore(sv, ev);
      }
    }
    return out;
  }
  if (
    typeof snapshot === "object" &&
    snapshot !== null &&
    !Array.isArray(snapshot) &&
    typeof edited === "object" &&
    edited !== null &&
    !Array.isArray(edited)
  ) {
    const snap = snapshot as Record<string, unknown>;
    const out = { ...(edited as Record<string, unknown>) };
    for (const [k, v] of Object.entries(snap)) {
      if (k.startsWith("_")) {
        out[k] = v;
      }
    }
    for (const [k, v] of Object.entries(snap)) {
      if (k.startsWith("_")) continue;
      if (v !== null && typeof v === "object" && !Array.isArray(v)) {
        const existing = out[k];
        if (existing !== undefined && typeof existing === "object" && existing !== null && !Array.isArray(existing)) {
          out[k] = deepMergePreserveUnderscore(v, existing);
        } else {
          out[k] = deepMergePreserveUnderscore(v, {});
        }
      } else if (Array.isArray(v) && Array.isArray(out[k])) {
        out[k] = deepMergePreserveUnderscore(v, out[k]);
      }
    }
    return out;
  }
  return edited;
}

/** Normalize API `params` to a plain object (handles JSON string and null). */
function normalizeSkillParams(raw: unknown): Record<string, unknown> {
  if (raw === null || raw === undefined) {
    return {};
  }
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
        return { ...(parsed as Record<string, unknown>) };
      }
    } catch {
      /* not JSON object */
    }
    return {};
  }
  if (typeof raw === "object" && !Array.isArray(raw)) {
    return { ...(raw as Record<string, unknown>) };
  }
  return {};
}

function ParamsDynamicFields({
  sample,
  shapeSample,
  namePath,
  meta,
  lockedFieldTooltip,
}: {
  sample: unknown;
  /** Original value from `params` (before list fields were flattened to strings). */
  shapeSample?: unknown;
  namePath: (string | number)[];
  meta: Map<string, string>;
  lockedFieldTooltip?: string;
}) {
  const { t } = useTranslation("common");
  const label = namePath.length ? String(namePath[namePath.length - 1]) : "";
  const locked = isLockedKeyPath(namePath);
  const lockTip = locked && lockedFieldTooltip ? { title: lockedFieldTooltip } : undefined;

  if (shapeSample !== undefined && Array.isArray(shapeSample) && isPrimitiveArray(shapeSample)) {
    const inlineCommentTip = typeof sample === "string" ? meta.get(pathToKey(namePath)) : undefined;
    const listTooltip = locked
      ? lockTip
      : inlineCommentTip
        ? { title: inlineCommentTip }
        : { title: t("tenantResources.skills.configModal.listFieldTooltip") };
    return (
      <Form.Item name={namePath} label={label} tooltip={listTooltip}>
        <Input
          placeholder={t("tenantResources.skills.configModal.listFieldPlaceholder")}
          readOnly={locked}
          className={`font-mono text-sm${locked ? " bg-neutral-100 dark:bg-neutral-800" : ""}`}
        />
      </Form.Item>
    );
  }

  if (sample === null || sample === undefined) {
    return (
      <Form.Item name={namePath} label={label} tooltip={lockTip}>
        <Input
          placeholder="null"
          readOnly={locked}
          className={locked ? "bg-neutral-100 dark:bg-neutral-800" : undefined}
        />
      </Form.Item>
    );
  }

  if (typeof sample === "string") {
    const inlineCommentTip = meta.get(pathToKey(namePath));
    const tooltip =
      locked ? lockTip : inlineCommentTip ? { title: inlineCommentTip } : undefined;
    return (
      <Form.Item name={namePath} label={label} tooltip={tooltip}>
        <Input
          readOnly={locked}
          className={locked ? "bg-neutral-100 dark:bg-neutral-800" : undefined}
        />
      </Form.Item>
    );
  }

  if (typeof sample === "number") {
    return (
      <Form.Item name={namePath} label={label} tooltip={lockTip}>
        <InputNumber
          className={`w-full${locked ? " bg-neutral-100 dark:bg-neutral-800" : ""}`}
          readOnly={locked}
        />
      </Form.Item>
    );
  }

  if (typeof sample === "boolean") {
    return (
      <Form.Item name={namePath} label={label} valuePropName="checked" tooltip={lockTip}>
        <Switch disabled={locked} />
      </Form.Item>
    );
  }

  if (Array.isArray(sample)) {
    if (sample.length === 0) {
      if (namePath.length === 0) {
        return null;
      }
      return (
        <Form.Item name={namePath} label={label} tooltip={lockTip}>
          <Input className="font-mono text-sm" readOnly placeholder="[]" />
        </Form.Item>
      );
    }
    return (
      <div className="mb-3 pl-3 border-l border-neutral-200 dark:border-neutral-600">
        {namePath.length > 0 && (
          <div className="mb-2 text-sm font-medium text-neutral-600 dark:text-neutral-400">{label}</div>
        )}
        {sample.map((item, i) => (
          <ParamsDynamicFields
            key={pathToKey([...namePath, i])}
            sample={item}
            shapeSample={Array.isArray(shapeSample) ? shapeSample[i] : undefined}
            namePath={[...namePath, i]}
            meta={meta}
            lockedFieldTooltip={lockedFieldTooltip}
          />
        ))}
      </div>
    );
  }

  if (typeof sample === "object" && !Array.isArray(sample)) {
    const entries = sortParamObjectEntries(
      Object.entries(sample as Record<string, unknown>).filter(
        ([k]) => !YAML_DOC_KEYS_HIDDEN_FROM_FORM.has(k)
      )
    );
    if (entries.length === 0) {
      if (namePath.length === 0) {
        return null;
      }
      return (
        <Form.Item name={namePath} label={label}>
          <Input className="font-mono text-sm" readOnly placeholder="{}" />
        </Form.Item>
      );
    }
    return (
      <div className="flex flex-col">
        {namePath.length > 0 && (
          <div className="mb-1 text-sm font-medium text-neutral-600 dark:text-neutral-400">{label}</div>
        )}
        <div
          className={
            namePath.length > 0
              ? "pl-4 border-l border-neutral-200 dark:border-neutral-600"
              : undefined
          }
        >
          {entries.map(([k, v]) => (
            <ParamsDynamicFields
              key={k}
              sample={v}
              shapeSample={
                shapeSample !== undefined &&
                typeof shapeSample === "object" &&
                shapeSample !== null &&
                !Array.isArray(shapeSample)
                  ? (shapeSample as Record<string, unknown>)[k]
                  : undefined
              }
              namePath={[...namePath, k]}
              meta={meta}
              lockedFieldTooltip={lockedFieldTooltip}
            />
          ))}
        </div>
      </div>
    );
  }

  return null;
}

/** Short display for ISO datetimes from the API (e.g. 2026/03/24 18:43). */
function formatSkillUpdateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${y}/${m}/${day} ${h}:${min}`;
}

export default function SkillList({
  tenantId,
}: {
  tenantId: string | null;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();

  const [paramsModalOpen, setParamsModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillListItem | null>(null);
  const [savingParams, setSavingParams] = useState(false);

  const snapshotRef = useRef<Record<string, unknown>>({});
  const metaRef = useRef<Map<string, string>>(new Map());

  const paramsEditorState = useMemo(() => {
    if (!paramsModalOpen || !editingSkill) return null;
    const parsed = normalizeSkillParams(editingSkill.params);
    const meta = new Map<string, string>();
    const { initialValues } = buildFormStateFromParams(parsed, [], meta);
    return { parsed, initialValues, meta };
  }, [paramsModalOpen, editingSkill]);

  const resetParamsForm = useCallback(() => {
    form.resetFields();
    snapshotRef.current = {};
    metaRef.current = new Map();
  }, [form]);

  const {
    data: skills = [],
    isLoading,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["skills", "list", tenantId],
    queryFn: async () => {
      try {
        return await fetchSkillsList();
      } catch (e) {
        log.error("Failed to fetch skills list", e);
        throw e;
      }
    },
    enabled: Boolean(tenantId),
    retry: 1,
  });

  useEffect(() => {
    if (!paramsEditorState) return;
    try {
      snapshotRef.current = JSON.parse(JSON.stringify(paramsEditorState.parsed)) as Record<string, unknown>;
    } catch {
      snapshotRef.current = paramsEditorState.parsed;
    }
    metaRef.current = new Map(paramsEditorState.meta);
  }, [paramsEditorState]);

  const openParamsEditor = (skill: SkillListItem) => {
    setEditingSkill(skill);
    setParamsModalOpen(true);
  };

  const closeParamsModal = () => {
    setParamsModalOpen(false);
    setEditingSkill(null);
    resetParamsForm();
  };

  const handleSaveParams = async () => {
    if (!editingSkill) return;

    setSavingParams(true);
    try {
      await form.validateFields();
      const values = form.getFieldsValue(true) as Record<string, unknown>;
      const restored = restorePrimitiveArraysFromForm(values, snapshotRef.current) as Record<string, unknown>;
      const withComments = applyStringComments(restored, metaRef.current) as Record<string, unknown>;
      const merged = deepMergePreserveUnderscore(snapshotRef.current, withComments) as Record<string, unknown>;

      if (merged === null || typeof merged !== "object" || Array.isArray(merged)) {
        message.error(t("tenantResources.skills.configModal.invalidJson"));
        return;
      }

      await updateSkill(editingSkill.name, { params: merged });
      message.success(t("tenantResources.skills.updateSuccess"));
      await queryClient.invalidateQueries({
        queryKey: ["skills", "list", tenantId],
      });
      closeParamsModal();
    } catch (e) {
      if (e && typeof e === "object" && "errorFields" in e) {
        return;
      }
      log.error("Failed to update skill params", e);
      message.error(t("tenantResources.skills.updateFailed"));
    } finally {
      setSavingParams(false);
    }
  };

  const columns: ColumnsType<SkillListItem> = [
    {
      title: t("tenantResources.skills.column.name"),
      dataIndex: "name",
      key: "name",
      ellipsis: true,
    },
    {
      title: t("tenantResources.skills.column.source"),
      dataIndex: "source",
      key: "source",
      width: 110,
      render: (source: string) => (
        <Tag color={source === "official" ? "blue" : "default"}>{source}</Tag>
      ),
    },
    {
      title: t("tenantResources.skills.column.tags"),
      dataIndex: "tags",
      key: "tags",
      width: 200,
      render: (tags: string[]) =>
        tags?.length ? (
          <span className="flex flex-wrap gap-1">
            {tags.map((tag) => (
              <Tag key={tag}>{tag}</Tag>
            ))}
          </span>
        ) : (
          "—"
        ),
    },
    {
      title: t("tenantResources.skills.column.config"),
      key: "params",
      width: 72,
      align: "center",
      render: (_: unknown, record: SkillListItem) => (
        <Tooltip title={t("tenantResources.skills.editParams")}>
          <Button
            type="text"
            size="small"
            icon={<Settings className="h-4 w-4" />}
            onClick={() => openParamsEditor(record)}
            aria-label={t("tenantResources.skills.editParams")}
          />
        </Tooltip>
      ),
    },
    {
      title: t("tenantResources.skills.column.updatedAt"),
      dataIndex: "update_time",
      key: "update_time",
      width: 148,
      render: (v: string | null | undefined) =>
        v ? (
          <Tooltip title={v}>
            <span className="tabular-nums">{formatSkillUpdateTime(v)}</span>
          </Tooltip>
        ) : (
          "—"
        ),
    },
  ];

  const formKey = editingSkill ? `skill-params-${editingSkill.skill_id}` : "closed";

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <Table<SkillListItem>
        columns={columns}
        dataSource={skills}
        rowKey={(row) => String(row.skill_id)}
        loading={isLoading}
        size="small"
        pagination={{ pageSize: 10 }}
        locale={{ emptyText: t("tenantResources.skills.empty") }}
        scroll={{ x: true }}
      />

      <Modal
        title={
          editingSkill
            ? t("tenantResources.skills.configModal.title", {
                name: editingSkill.name,
              })
            : t("tenantResources.skills.configModal.titleFallback")
        }
        open={paramsModalOpen}
        onCancel={closeParamsModal}
        onOk={handleSaveParams}
        confirmLoading={savingParams}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        width={660}
        centered
        destroyOnClose
        styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
      >
        <Form
          key={formKey}
          form={form}
          layout="horizontal"
          size="small"
          labelCol={{ flex: "0 0 160px" }}
          wrapperCol={{ flex: "1 1 auto" }}
          labelAlign="left"
          labelWrap
          preserve={false}
          rootClassName="[&_.ant-form-item]:!mb-1"
          initialValues={
            paramsEditorState?.initialValues !== undefined
              ? (paramsEditorState.initialValues as Record<string, unknown>)
              : undefined
          }
        >
          {paramsEditorState &&
            paramsEditorState.initialValues !== null &&
            paramsEditorState.initialValues !== undefined &&
            typeof paramsEditorState.initialValues === "object" &&
            !Array.isArray(paramsEditorState.initialValues) &&
            Object.keys(paramsEditorState.initialValues as object).length === 0 && (
              <p className="text-sm text-neutral-500 mb-0">{t("tenantResources.skills.configModal.emptyParams")}</p>
            )}
          {paramsEditorState && (
            <ParamsDynamicFields
              sample={paramsEditorState.initialValues}
              shapeSample={paramsEditorState.parsed}
              namePath={[]}
              meta={paramsEditorState.meta}
              lockedFieldTooltip={t("tenantResources.skills.configModal.lockedField")}
            />
          )}
        </Form>
      </Modal>
    </div>
  );
}
