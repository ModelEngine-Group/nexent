// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  App,
  Button,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Segmented,
  Select,
} from "antd";
import {
  DeleteOutlined,
  DownOutlined,
  PlusOutlined,
  UpOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { aidpRelationName, aidpRelationId } from "@/ext_components/aidp/shared/utils/aidpRelationDisplay";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  ENTITY_API_NAME_MAX_CHARS,
  ENTITY_DESCRIPTION_MAX_BYTES,
  ENTITY_DESCRIPTION_MAX_CHARS,
  ENTITY_NAME_MAX_BYTES,
  byteCountText,
  validateEntityDescription,
  validateEntityName,
} from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import type {
  AidpOntologyEntity,
  AidpOntologyEntityProperty,
} from "@/ext_components/aidp/shared/types/ontology";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import AidpOntologyFieldLabel from "@/ext_components/aidp/shared/components/AidpOntologyFieldLabel";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyEntityDrawer.module.css";

interface AidpOntologyEntityDrawerProps {
  open: boolean;
  domainId: string;
  entity: AidpOntologyEntity | null;
  onClose: () => void;
  onSaved: () => void;
}

type PropertyDataType = "str" | "string" | "float" | "datetime" | "list[str]";

interface PropertyFormValue {
  /** Visible property label; for existing rows this is display_name. */
  name: string;
  /** Existing AIDP identifier, kept verbatim when the label is edited. */
  api_name?: string;
  data_type: PropertyDataType;
  value?: string | string[] | number | Dayjs | null;
  /** AIDP persists any string here and returns it verbatim. */
  range?: string;
}

interface EntityFormValues {
  kind: "entity" | "type";
  display_name: string;
  api_name: string;
  description?: string;
  properties?: PropertyFormValue[];
  demo_parents?: string[];
  demo_synonyms?: string[];
  demo_children?: string[];
}

const PROPERTY_LIMIT = 32;
const RELATION_LIMIT = { parent: 9, synonym: 9, child: 100 } as const;

/** AIDP api_name rule: letter first, then letters/digits/underscores, no trailing underscore. */
const API_NAME_PATTERN = /^[A-Za-z](?:[A-Za-z0-9_]*[A-Za-z0-9])?$/;

const DATA_TYPE_OPTIONS: PropertyDataType[] = [
  "str",
  "string",
  "float",
  "datetime",
  "list[str]",
];

const DATA_TYPE_LABEL_KEYS: Record<PropertyDataType, string> = {
  str: "aidpKnowledge.ontologyMetadataTypeText",
  string: "aidpKnowledge.ontologyMetadataTypeText",
  float: "aidpKnowledge.ontologyMetadataTypeNumber",
  datetime: "aidpKnowledge.ontologyMetadataTypeDate",
  "list[str]": "aidpKnowledge.ontologyEntityPropertyTypeMultiText",
};

const propertyValueToText = (
  value: string | string[] | number | Dayjs | null | undefined
): string => {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object" && "format" in value) {
    return value.format("YYYY-MM-DD HH:mm");
  }
  return String(value);
};

const toDataType = (value: unknown): PropertyDataType =>
  DATA_TYPE_OPTIONS.includes(value as PropertyDataType)
    ? (value as PropertyDataType)
    : "string";

interface PropertyValueInputProps {
  name: number;
  value?: unknown;
  onChange?: (value: unknown) => void;
  id?: string;
  disabled?: boolean;
}

/** Value control follows the property data_type and forwards Form.Item props. */
const PropertyValueInput: React.FC<PropertyValueInputProps> = ({
  name,
  value,
  onChange,
  id,
  disabled,
}) => {
  const dataType = Form.useWatch(["properties", name, "data_type"]) as
    PropertyDataType | undefined;
  switch (dataType) {
    case "list[str]": {
      const listValue = Array.isArray(value)
        ? value
        : typeof value === "string" && value.trim()
          ? value
              .split(/[,，]/)
              .map((item) => item.trim())
              .filter(Boolean)
          : [];
      return (
        <Select
          id={id}
          disabled={disabled}
          mode="tags"
          tokenSeparators={[",", "，"]}
          value={listValue}
          onChange={onChange}
        />
      );
    }
    case "datetime":
      return (
        <DatePicker
          id={id}
          disabled={disabled}
          showTime
          className={styles.valueControl}
          value={
            value === null || value === undefined || value === ""
              ? null
              : dayjs.isDayjs(value)
                ? value
                : dayjs(String(value))
          }
          onChange={onChange}
        />
      );
    case "float": {
      const numberValue =
        value === null || value === undefined || value === ""
          ? undefined
          : typeof value === "number"
            ? value
            : Number(value);
      return (
        <InputNumber
          id={id}
          disabled={disabled}
          className={styles.valueControl}
          precision={3}
          value={Number.isFinite(numberValue) ? numberValue : undefined}
          onChange={onChange}
        />
      );
    }
    default:
      return (
        <Input
          id={id}
          disabled={disabled}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={onChange}
        />
      );
  }
};

const AidpOntologyEntityDrawer: React.FC<AidpOntologyEntityDrawerProps> = ({
  open,
  domainId,
  entity,
  onClose,
  onSaved,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [form] = Form.useForm<EntityFormValues>();
  const scope = useAidpQueryScope();
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [relationSearch, setRelationSearch] = useState("");
  const [relationKeyword, setRelationKeyword] = useState("");
  const [apiNameTouched, setApiNameTouched] = useState(!!entity);
  const editing = !!entity;

  const kind = (Form.useWatch("kind", form) as "entity" | "type") ?? "entity";
  const displayName = Form.useWatch("display_name", form) as string | undefined;
  const assignedTypeId = entity?.type_id ?? undefined;

  useEffect(() => {
    const timer = window.setTimeout(
      () => setRelationKeyword(relationSearch.trim()),
      300
    );
    return () => window.clearTimeout(timer);
  }, [relationSearch]);

  const handleClose = () => {
    setErrorMessage(null);
    setSaving(false);
    setPropertiesOpen(false);
    setApiNameTouched(false);
    onClose();
  };

  const allEntitiesQuery = useQuery({
    queryKey: [
      ...scope.key,
      "ontology-entity-options",
      domainId,
      relationKeyword,
    ],
    queryFn: () =>
      aidpOntologyService.listEntities(
        domainId,
        1,
        100,
        relationKeyword || undefined
      ),
    enabled: scope.enabled && open,
    staleTime: 30_000,
    retry: false,
  });

  const relationOptions = useMemo(
    () =>
      (allEntitiesQuery.data?.value ?? [])
        .filter(
          (item) =>
            item.kind !== "type" &&
            (item.api_name !== entity?.api_name || item.kind !== entity?.kind)
        )
        .map((item) => ({
          value: aidpRelationId(item.entity_id),
          label: item.display_name || item.api_name,
        }))
        .filter((item) => item.value),
    [allEntitiesQuery.data?.value, entity?.api_name, entity?.kind]
  );

  const parentOptions = useMemo(
    () => relationOptions.filter((option) => option.value !== assignedTypeId),
    [assignedTypeId, relationOptions]
  );

  const synonymOptions = useMemo(
    () =>
      (allEntitiesQuery.data?.value ?? [])
        .filter((item) => item.kind !== "type")
        .map((item) => ({
          value: item.display_name || item.api_name,
          label: item.display_name || item.api_name,
        }))
        .filter((item) => item.value),
    [allEntitiesQuery.data?.value]
  );

  const initialParentIds = useMemo(
    () =>
      (entity?.parent_entities ?? []).map((item) => aidpRelationId(item)).filter(Boolean).sort(),
    [entity?.parent_entities]
  );
  const initialChildIds = useMemo(
    () => (entity?.child_entities ?? []).map((item) => aidpRelationId(item)).filter(Boolean).sort(),
    [entity?.child_entities]
  );

  const relationConflictRule = (peer: "demo_parents" | "demo_children") => ({
    validator: async (_rule: unknown, value?: string[]) => {
      const selected = (value ?? []).filter(Boolean);
      const other = (form.getFieldValue(peer) ?? []) as string[];
      if (selected.some((item) => other.includes(item))) {
        throw new Error(t("aidpKnowledge.ontologyEntityRelationConflict"));
      }
    },
  });

  const initialProperties = useMemo<PropertyFormValue[]>(
    () =>
      (entity?.properties ?? [])
        // Synonyms live in their own control; keep them out of the extension
        // property rows so they are not edited twice.
        .filter((property) => property.api_name !== "synonym")
        .map((property) => ({
          name: property.display_name || property.api_name,
          api_name: property.api_name,
          data_type: toDataType(property.data_type),
          value: property.value ?? "",
          range: property.range ?? "",
        })),
    [entity?.properties]
  );

  // Reset the form on every open; the antd form store survives the Drawer remount.
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    form.setFieldsValue({
      kind: entity?.kind ?? "entity",
      display_name: entity?.display_name ?? "",
      api_name: entity?.api_name ?? "",
      description: entity?.description ?? "",
      properties: initialProperties,
      demo_parents: (entity?.parent_entities ?? [])
        .map((item) => aidpRelationId(item))
        .filter(Boolean),
      demo_synonyms: (entity?.synonym_entities ?? [])
        .map((item) => aidpRelationName(item))
        .filter(Boolean),
      demo_children: (entity?.child_entities ?? [])
        .map((item) => aidpRelationId(item))
        .filter(Boolean),
    });
  }, [entity, form, initialProperties, open]);

  // Fill the API name from the display name while the user has not edited it.
  // Chinese names cannot be transliterated here, so they stay manual.
  useEffect(() => {
    if (editing || apiNameTouched) return;
    const raw = (displayName ?? "").trim();
    if (!raw || /[^\x00-\x7F]/.test(raw)) return;
    let slug = raw
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    if (!/^[a-z]/.test(slug)) slug = `entity_${slug}`;
    slug = slug.slice(0, ENTITY_API_NAME_MAX_CHARS).replace(/_+$/g, "");
    if (slug) form.setFieldsValue({ api_name: slug });
  }, [apiNameTouched, displayName, editing, form]);

  const handleSubmit = async () => {
    let values: EntityFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const displayNameValue = values.display_name.trim();
    const apiNameValue = values.api_name.trim();
    const properties: AidpOntologyEntityProperty[] = (values.properties ?? [])
      .filter((property) => property?.name?.trim())
      .map((property) => ({
        api_name: property.api_name?.trim() || property.name.trim(),
        display_name: property.name.trim(),
        data_type: toDataType(property.data_type),
        value: propertyValueToText(property.value) || "",
        ...((property.range ?? "").trim()
          ? { range: (property.range ?? "").trim() }
          : {}),
      }));
    // Synonyms are a `synonym` property in the confirmed AIDP contract, not a
    // relation; keep the select but fold it into the property list on save.
    const synonyms = (values.demo_synonyms ?? [])
      .map((item) => String(item).trim())
      .filter(Boolean);
    if (synonyms.length) {
      properties.push({
        api_name: "synonym",
        display_name: "synonym",
        value: synonyms.join("、"),
      });
    }
    const parentIds = (values.demo_parents ?? []).filter(Boolean);
    const childIds = (values.demo_children ?? []).filter(Boolean);

    setSaving(true);
    setErrorMessage(null);
    try {
      if (entity?.entity_id) {
        const parentIdsChanged =
          JSON.stringify([...parentIds].sort()) !==
          JSON.stringify(initialParentIds);
        const childIdsChanged =
          JSON.stringify([...childIds].sort()) !==
          JSON.stringify(initialChildIds);
        await aidpOntologyService.updateEntity(domainId, entity.entity_id, {
          display_name: displayNameValue,
          description: values.description?.trim() ?? "",
          properties,
          // Only send relation fields that actually changed so a plain edit
          // does not trigger an extra Relations read/write round trip.
          ...(parentIdsChanged ? { parent_entities: parentIds } : {}),
          ...(childIdsChanged ? { child_entities: childIds } : {}),
        });
        message.success(t("aidpKnowledge.ontologyEntityUpdated"));
      } else {
        const created = await aidpOntologyService.createEntity(domainId, {
          api_name: apiNameValue,
          display_name: displayNameValue,
          description: values.description?.trim() ?? "",
          properties,
          ...(parentIds.length ? { parent_entities: parentIds } : {}),
          ...(childIds.length ? { child_entities: childIds } : {}),
        });
        if (created.relation_error) {
          const reason =
            created.relation_error === "ENTITY_RELATION_WRITEBACK_FAILED"
              ? t("aidpKnowledge.ontologyEntityRelationWritebackFailed")
              : created.relation_error;
          message.warning(
            t("aidpKnowledge.ontologyEntityRelationPartial", { reason })
          );
        } else {
          message.success(t("aidpKnowledge.ontologyEntityCreated"));
        }
      }
      onSaved();
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(
          error,
          t,
          editing
            ? t("aidpKnowledge.ontologyEntityUpdateFailed")
            : t("aidpKnowledge.ontologyEntityCreateFailed")
        )
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={720}
      onClose={handleClose}
      destroyOnHidden
      title={
        editing
          ? t("aidpKnowledge.ontologyEntityEditTitle")
          : t("aidpKnowledge.ontologyEntityCreateTitle")
      }
      footer={
        <div className={drawerStyles.footer}>
          <Button onClick={handleClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={saving}
            onClick={() => void handleSubmit()}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      <Form
        key={open ? `open-${entity?.entity_id ?? "new"}` : "closed"}
        form={form}
        layout="vertical"
        className={drawerStyles.form}
        initialValues={{
          kind: entity?.kind ?? "entity",
          display_name: entity?.display_name ?? "",
          api_name: entity?.api_name ?? "",
          description: entity?.description ?? "",
          properties: initialProperties,
          demo_parents: (entity?.parent_entities ?? [])
            .map((item) => aidpRelationId(item))
            .filter(Boolean),
          demo_synonyms: (entity?.synonym_entities ?? [])
            .map((item) => aidpRelationName(item))
            .filter(Boolean),
          demo_children: (entity?.child_entities ?? [])
            .map((item) => aidpRelationId(item))
            .filter(Boolean),
        }}
      >
        {editing && (
          <Form.Item
            name="kind"
            label={
              <AidpOntologyFieldLabel
                label={t("aidpKnowledge.ontologyEntityObjectKind")}
                help={t("aidpKnowledge.ontologyEntityKindHint")}
              />
            }
          >
            <Segmented
              block
              className={styles.kindControl}
              disabled
              options={[
                {
                  value: "entity",
                  label: t("aidpKnowledge.ontologyEntityKindEntity"),
                },
                {
                  value: "type",
                  label: t("aidpKnowledge.ontologyEntityKindType"),
                },
              ]}
            />
          </Form.Item>
        )}

        <Form.Item
          name="display_name"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyEntityNameLabel")}
              help={t("aidpKnowledge.ontologyEntityNameHelp")}
            />
          }
          rules={[
            { required: true, whitespace: true },
            {
              validator: async (_rule, value: string) => {
                const error = validateEntityName(value ?? "", t);
                if (error) throw new Error(error);
              },
            },
          ]}
        >
          <Input
            maxLength={ENTITY_API_NAME_MAX_CHARS}
            showCount={{
              formatter: ({ value }) =>
                byteCountText(
                  String(value ?? ""),
                  ENTITY_NAME_MAX_BYTES,
                  t("aidpKnowledge.ontologyBytesUnit")
                ),
            }}
          />
        </Form.Item>

        <Form.Item
          name="api_name"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyEntityApiName")}
              help={t("aidpKnowledge.ontologyEntityApiNameHint")}
            />
          }
          rules={[
            { required: true, whitespace: true },
            {
              validator: async (_rule, value: string) => {
                const apiName = (value ?? "").trim();
                if (apiName.length > ENTITY_API_NAME_MAX_CHARS) {
                  throw new Error(
                    t("aidpKnowledge.ontologyEntityNameTooLong", {
                      max: ENTITY_API_NAME_MAX_CHARS,
                    })
                  );
                }
                if (!API_NAME_PATTERN.test(apiName)) {
                  throw new Error(
                    t("aidpKnowledge.ontologyEntityApiNameInvalid")
                  );
                }
              },
            },
          ]}
        >
          <Input
            maxLength={ENTITY_API_NAME_MAX_CHARS}
            disabled={editing}
            onChange={() => setApiNameTouched(true)}
          />
        </Form.Item>

        <Form.Item
          name="description"
          label={
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyEntityDescription")}
              help={t("aidpKnowledge.ontologyEntityDescriptionHelp")}
            />
          }
          rules={[
            {
              validator: async (_rule, value: string) => {
                const error = validateEntityDescription(value ?? "", t);
                if (error) throw new Error(error);
              },
            },
          ]}
        >
          <Input.TextArea
            autoSize={{ minRows: 3, maxRows: 6 }}
            maxLength={ENTITY_DESCRIPTION_MAX_CHARS}
            showCount={{
              formatter: ({ value }) =>
                byteCountText(
                  String(value ?? ""),
                  ENTITY_DESCRIPTION_MAX_BYTES,
                  t("aidpKnowledge.ontologyBytesUnit")
                ),
            }}
          />
        </Form.Item>

        {kind === "entity" && (
          <section className={styles.relationPanel}>
            <div className={styles.sectionTitle}>
              {t("aidpKnowledge.ontologyEntityRelations")}
            </div>
            <Form.Item
              name="demo_parents"
              label={
                <AidpOntologyFieldLabel
                  label={t("aidpKnowledge.ontologyEntityParent")}
                  help={t("aidpKnowledge.ontologyEntityParentHelp")}
                />
              }
              rules={[relationConflictRule("demo_children")]}
            >
              <Select
                mode="multiple"
                allowClear
                maxCount={RELATION_LIMIT.parent}
                options={parentOptions}
                filterOption={false}
                loading={allEntitiesQuery.isLoading}
                notFoundContent={
                  allEntitiesQuery.isError
                    ? t("aidpKnowledge.ontologyEntityLoadFailed")
                    : undefined
                }
                onSearch={setRelationSearch}
              />
            </Form.Item>
            <Form.Item
              name="demo_synonyms"
              label={
                <AidpOntologyFieldLabel
                  label={t("aidpKnowledge.ontologyEntitySynonym")}
                  help={t("aidpKnowledge.ontologyEntitySynonymHelp")}
                />
              }
            >
              <Select
                mode="multiple"
                allowClear
                maxCount={RELATION_LIMIT.synonym}
                options={synonymOptions}
                filterOption={false}
                loading={allEntitiesQuery.isLoading}
                notFoundContent={
                  allEntitiesQuery.isError
                    ? t("aidpKnowledge.ontologyEntityLoadFailed")
                    : undefined
                }
                onSearch={setRelationSearch}
              />
            </Form.Item>
            <Form.Item
              name="demo_children"
              label={
                <AidpOntologyFieldLabel
                  label={t("aidpKnowledge.ontologyEntityChild")}
                  help={t("aidpKnowledge.ontologyEntityChildHelp")}
                />
              }
              rules={[relationConflictRule("demo_parents")]}
            >
              <Select
                mode="multiple"
                allowClear
                maxCount={RELATION_LIMIT.child}
                options={relationOptions}
                filterOption={false}
                loading={allEntitiesQuery.isLoading}
                notFoundContent={
                  allEntitiesQuery.isError
                    ? t("aidpKnowledge.ontologyEntityLoadFailed")
                    : undefined
                }
                onSearch={setRelationSearch}
              />
            </Form.Item>
          </section>
        )}

        <section className={styles.propertyPanel}>
          <button
            type="button"
            className={styles.propertyToggle}
            aria-expanded={propertiesOpen}
            onClick={() => setPropertiesOpen((previous) => !previous)}
          >
            <AidpOntologyFieldLabel
              label={t("aidpKnowledge.ontologyEntityPropertiesOptional")}
              help={t("aidpKnowledge.ontologyEntityPropertiesHelp")}
            />
            {propertiesOpen ? <UpOutlined /> : <DownOutlined />}
          </button>
          <Form.List name="properties">
            {(fields, { add, remove }) => (
              <div className={styles.propertyList} hidden={!propertiesOpen}>
                {fields.length > 0 && (
                  <div className={styles.propertyHeader}>
                    <span>
                      <AidpOntologyFieldLabel
                        required
                        label={t("aidpKnowledge.ontologyEntityPropertyName")}
                        help={t("aidpKnowledge.ontologyEntityPropertyNameHelp")}
                      />
                    </span>
                    <span>
                      <AidpOntologyFieldLabel
                        required
                        label={t("aidpKnowledge.ontologyEntityPropertyType")}
                        help={t("aidpKnowledge.ontologyEntityPropertyTypeHelp")}
                      />
                    </span>
                    <span>
                      {t("aidpKnowledge.ontologyEntityPropertyValue")}
                    </span>
                    <span>
                      <AidpOntologyFieldLabel
                        label={t("aidpKnowledge.ontologyEntityPropertyRange")}
                        help={t(
                          "aidpKnowledge.ontologyEntityPropertyRangeHelp"
                        )}
                      />
                    </span>
                    <span aria-hidden="true" />
                  </div>
                )}
                {fields.map((field) => (
                  <div key={field.key} className={styles.propertyRow}>
                    <Form.Item
                      {...field}
                      name={[field.name, "api_name"]}
                      hidden
                    >
                      <Input />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, "name"]}
                      rules={[
                        {
                          validator: async (_rule, value: string) => {
                            if (!(value ?? "").trim()) {
                              throw new Error(
                                t(
                                  "aidpKnowledge.ontologyEntityPropertyNameRequired"
                                )
                              );
                            }
                          },
                        },
                      ]}
                      className={styles.propertyDense}
                    >
                      <Input />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, "data_type"]}
                      className={styles.propertyDense}
                    >
                      <Select
                        options={DATA_TYPE_OPTIONS.map((value) => ({
                          value,
                          label: t(DATA_TYPE_LABEL_KEYS[value]),
                        }))}
                      />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, "value"]}
                      className={styles.propertyDense}
                    >
                      <PropertyValueInput name={field.name} />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, "range"]}
                      className={styles.propertyDense}
                    >
                      <Input />
                    </Form.Item>
                    <Button
                      type="text"
                      aria-label={t("aidpKnowledge.ontologyRemoveProperty")}
                      icon={<DeleteOutlined />}
                      onClick={() => remove(field.name)}
                    />
                  </div>
                ))}
                <Button
                  type="link"
                  className={styles.addProperty}
                  icon={<PlusOutlined />}
                  disabled={fields.length >= PROPERTY_LIMIT}
                  onClick={() =>
                    add({
                      name: "",
                      data_type: "string",
                      value: "",
                      range: "",
                    })
                  }
                >
                  {t("aidpKnowledge.ontologyEntityAddProperty")} (
                  {fields.length}/{PROPERTY_LIMIT})
                </Button>
              </div>
            )}
          </Form.List>
        </section>
        {errorMessage && (
          <div className={drawerStyles.error} role="alert">
            {errorMessage}
          </div>
        )}
      </Form>
    </Drawer>
  );
};

export default AidpOntologyEntityDrawer;
