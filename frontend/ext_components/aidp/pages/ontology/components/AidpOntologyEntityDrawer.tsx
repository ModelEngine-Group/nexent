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
  Select,
} from "antd";
import {
  DeleteOutlined,
  DownOutlined,
  PlusOutlined,
  UpOutlined,
} from "@ant-design/icons";
import type { Dayjs } from "dayjs";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import AidpOntologyGapNote from "@/ext_components/aidp/shared/components/AidpOntologyGapNote";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  ENTITY_API_NAME_MAX_CHARS,
  ENTITY_DESCRIPTION_MAX_CHARS,
} from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";
import type {
  AidpOntologyEntity,
  AidpOntologyEntityProperty,
} from "@/ext_components/aidp/shared/types/ontology";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyEntityDrawer.module.css";

interface AidpOntologyEntityDrawerProps {
  open: boolean;
  domainId: string;
  entity: AidpOntologyEntity | null;
  onClose: () => void;
  onSaved: () => void;
}

type PropertyValueType = "text" | "multitext" | "date" | "number";

interface PropertyFormValue {
  name: string;
  value_type: PropertyValueType;
  value?: string | string[] | number | Dayjs | null;
}

interface EntityFormValues {
  entity_name: string;
  description?: string;
  properties?: PropertyFormValue[];
  demo_parents?: string[];
  demo_synonyms?: string[];
  demo_children?: string[];
}

const PROPERTY_LIMIT = 32;
const RELATION_LIMIT = { parent: 9, synonym: 9, child: 100 } as const;

const relationName = (value: unknown): string => {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(
      record.display_name ??
        record.displayName ??
        record.api_name ??
        record.name ??
        record.id ??
        ""
    );
  }
  return "";
};

/** AIDP relations and first-class entities are addressed by numeric id. */
const relationId = (value: unknown): string => {
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(record.entity_id ?? record.id ?? "");
  }
  return "";
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

/** Value control follows the property type; the type itself is UI-only. */
const PropertyValueInput: React.FC<{ name: number }> = ({ name }) => {
  const { t } = useTranslation();
  const valueType = Form.useWatch(["properties", name, "value_type"]) as
    PropertyValueType | undefined;
  switch (valueType) {
    case "multitext":
      return (
        <Select
          mode="tags"
          tokenSeparators={[",", "，"]}
          placeholder={t(
            "aidpKnowledge.ontologyEntityPropertyMultiPlaceholder"
          )}
        />
      );
    case "date":
      return (
        <DatePicker
          showTime
          className={styles.valueControl}
          placeholder={t("aidpKnowledge.ontologyEntityPropertyDatePlaceholder")}
        />
      );
    case "number":
      return (
        <InputNumber
          className={styles.valueControl}
          precision={3}
          placeholder={t(
            "aidpKnowledge.ontologyEntityPropertyNumberPlaceholder"
          )}
        />
      );
    default:
      return (
        <Input placeholder={t("aidpKnowledge.ontologyEntityPropertyInput")} />
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
  const editing = !!entity;

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
            item.api_name !== entity?.api_name || item.kind !== entity?.kind
        )
        .map((item) => ({
          value: relationId(item.entity_id),
          label: item.display_name || item.api_name,
        }))
        .filter((item) => item.value),
    [allEntitiesQuery.data?.value, entity?.api_name, entity?.kind]
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
      (entity?.parent_entities ?? []).map(relationId).filter(Boolean).sort(),
    [entity?.parent_entities]
  );
  const initialChildIds = useMemo(
    () => (entity?.child_entities ?? []).map(relationId).filter(Boolean).sort(),
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
          value_type: "text",
          value: property.value ?? "",
        })),
    [entity?.properties]
  );

  const handleSubmit = async () => {
    let values: EntityFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const name = values.entity_name.trim();
    const properties: AidpOntologyEntityProperty[] = (values.properties ?? [])
      .filter((property) => property?.name?.trim())
      .map((property) => ({
        api_name: property.name.trim(),
        display_name: property.name.trim(),
        value: propertyValueToText(property.value) || "",
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
          display_name: name,
          description: values.description?.trim() ?? "",
          properties,
          primary_properties: properties.map((item) => item.api_name),
          // Only send relation fields that actually changed so a plain edit
          // does not trigger an extra Relations read/write round trip.
          ...(parentIdsChanged ? { parent_entities: parentIds } : {}),
          ...(childIdsChanged ? { child_entities: childIds } : {}),
        });
        message.success(t("aidpKnowledge.ontologyEntityUpdated"));
      } else {
        await aidpOntologyService.createEntity(domainId, {
          // AIDP requires api_name and kind but the new UCD only draws one
          // entity name. Use the entered name for both and create a plain
          // entity; the red note explains that AIDP validation may reject it.
          kind: "entity",
          api_name: name,
          display_name: name,
          description: values.description?.trim() ?? "",
          properties,
          primary_properties: properties.map((item) => item.api_name),
          parent_entities: parentIds,
          child_entities: childIds,
        });
        message.success(t("aidpKnowledge.ontologyEntityCreated"));
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
          entity_name: entity?.display_name ?? "",
          description: entity?.description ?? "",
          properties: initialProperties,
          demo_parents: (entity?.parent_entities ?? [])
            .map(relationId)
            .filter(Boolean),
          demo_synonyms: (entity?.synonym_entities ?? [])
            .map(relationName)
            .filter(Boolean),
          demo_children: (entity?.child_entities ?? [])
            .map(relationId)
            .filter(Boolean),
        }}
      >
        <Form.Item
          name="entity_name"
          label={t("aidpKnowledge.ontologyEntityNameLabel")}
          rules={[
            { required: true, whitespace: true },
            {
              validator: async (_rule, value: string) => {
                if ((value ?? "").trim().length > ENTITY_API_NAME_MAX_CHARS) {
                  throw new Error(
                    t("aidpKnowledge.ontologyEntityNameTooLong", {
                      max: ENTITY_API_NAME_MAX_CHARS,
                    })
                  );
                }
              },
            },
          ]}
        >
          <Input
            maxLength={ENTITY_API_NAME_MAX_CHARS}
            showCount
            placeholder={t("aidpKnowledge.ontologyEntityNamePlaceholder")}
          />
        </Form.Item>
        <AidpOntologyGapNote>
          {t("aidpKnowledge.ontologyEntityNameMappingGap")}
        </AidpOntologyGapNote>

        <Form.Item
          name="description"
          label={t("aidpKnowledge.ontologyEntityDescription")}
          rules={[
            {
              validator: async (_rule, value: string) => {
                if (
                  (value ?? "").trim().length > ENTITY_DESCRIPTION_MAX_CHARS
                ) {
                  throw new Error(
                    t("aidpKnowledge.ontologyEntityDescriptionTooLong", {
                      max: ENTITY_DESCRIPTION_MAX_CHARS,
                    })
                  );
                }
              },
            },
          ]}
        >
          <Input.TextArea
            autoSize={{ minRows: 3, maxRows: 6 }}
            maxLength={ENTITY_DESCRIPTION_MAX_CHARS}
            showCount
            placeholder={t(
              "aidpKnowledge.ontologyEntityDescriptionPlaceholder"
            )}
          />
        </Form.Item>

        <section className={styles.relationPanel}>
          <div className={styles.sectionTitle}>
            {t("aidpKnowledge.ontologyEntityRelations")}
          </div>
          <AidpOntologyGapNote>
            {t("aidpKnowledge.ontologyEntityRelationGap")}
          </AidpOntologyGapNote>
          <Form.Item
            name="demo_parents"
            label={t("aidpKnowledge.ontologyEntityParent")}
            rules={[relationConflictRule("demo_children")]}
          >
            <Select
              mode="multiple"
              allowClear
              maxCount={RELATION_LIMIT.parent}
              options={relationOptions}
              placeholder={t("aidpKnowledge.ontologyEntityRelationPlaceholder")}
              filterOption={false}
              onSearch={setRelationSearch}
            />
          </Form.Item>
          <Form.Item
            name="demo_synonyms"
            label={t("aidpKnowledge.ontologyEntitySynonym")}
          >
            <Select
              mode="multiple"
              allowClear
              maxCount={RELATION_LIMIT.synonym}
              options={synonymOptions}
              placeholder={t("aidpKnowledge.ontologyEntityRelationPlaceholder")}
              filterOption={false}
              onSearch={setRelationSearch}
            />
          </Form.Item>
          <Form.Item
            name="demo_children"
            label={t("aidpKnowledge.ontologyEntityChild")}
            rules={[relationConflictRule("demo_parents")]}
          >
            <Select
              mode="multiple"
              allowClear
              maxCount={RELATION_LIMIT.child}
              options={relationOptions}
              placeholder={t("aidpKnowledge.ontologyEntityRelationPlaceholder")}
              filterOption={false}
              onSearch={setRelationSearch}
            />
          </Form.Item>
        </section>

        <section className={styles.propertyPanel}>
          <button
            type="button"
            className={styles.propertyToggle}
            aria-expanded={propertiesOpen}
            onClick={() => setPropertiesOpen((previous) => !previous)}
          >
            <span>{t("aidpKnowledge.ontologyEntityPropertiesOptional")}</span>
            {propertiesOpen ? <UpOutlined /> : <DownOutlined />}
          </button>
          <AidpOntologyGapNote>
            {t("aidpKnowledge.ontologyEntityPropertyTypeGap")}
          </AidpOntologyGapNote>
          <Form.List name="properties">
            {(fields, { add, remove }) => (
              <div className={styles.propertyList} hidden={!propertiesOpen}>
                {fields.length > 0 && (
                  <div className={styles.propertyHeader}>
                    <span>
                      {t("aidpKnowledge.ontologyEntityPropertyName")}
                      <em>*</em>
                    </span>
                    <span>
                      {t("aidpKnowledge.ontologyEntityPropertyType")}
                      <em>*</em>
                    </span>
                    <span>
                      {t("aidpKnowledge.ontologyEntityPropertyValue")}
                      <em>*</em>
                    </span>
                    <span aria-hidden="true" />
                  </div>
                )}
                {fields.map((field) => (
                  <div key={field.key} className={styles.propertyRow}>
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
                      <Input
                        placeholder={t(
                          "aidpKnowledge.ontologyEntityPropertyNamePlaceholder"
                        )}
                      />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, "value_type"]}
                      className={styles.propertyDense}
                    >
                      <Select
                        options={[
                          {
                            value: "text",
                            label: t("aidpKnowledge.ontologyMetadataTypeText"),
                          },
                          {
                            value: "multitext",
                            label: t(
                              "aidpKnowledge.ontologyEntityPropertyTypeMultiText"
                            ),
                          },
                          {
                            value: "date",
                            label: t("aidpKnowledge.ontologyMetadataTypeDate"),
                          },
                          {
                            value: "number",
                            label: t(
                              "aidpKnowledge.ontologyMetadataTypeNumber"
                            ),
                          },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item
                      {...field}
                      name={[field.name, "value"]}
                      className={styles.propertyDense}
                    >
                      <PropertyValueInput name={field.name} />
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
                      value_type: "text",
                      value: "",
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
