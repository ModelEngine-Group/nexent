// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
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
  Radio,
  Select,
  Skeleton,
  Switch,
  Tooltip,
} from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";

import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import { useAidpOntologyDemoMode } from "@/ext_components/aidp/shared/hooks/useAidpOntologyDemoMode";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import AidpOntologyFieldLabel from "@/ext_components/aidp/shared/components/AidpOntologyFieldLabel";
import type {
  AidpOntologyRuleActionValue,
  AidpOntologyRuleCondition,
  AidpOntologyRuleConditionGroup,
  AidpOntologyRulePayload,
  AidpRuleEffectMode,
  AidpRuleFieldTransform,
  AidpRuleLogicalOperator,
} from "@/ext_components/aidp/shared/types/ontology";
import drawerStyles from "@/ext_components/aidp/shared/styles/AidpOntologyDrawer.module.css";
import styles from "./AidpOntologyRuleDrawer.module.css";

interface AidpOntologyRuleDrawerProps {
  open: boolean;
  domainId: string;
  ruleId: string | null;
  onClose: () => void;
  onSaved: () => void;
}

type FieldType = "string" | "number" | "date";
type ConditionValue = string | number | Dayjs | null | undefined;

interface ConditionFormValue {
  field: string;
  field_type: FieldType;
  operator: string;
  value?: ConditionValue;
}

interface RuleFormValues {
  name: string;
  description?: string;
  enabled: boolean;
  logical_operator: AidpRuleLogicalOperator;
  conditions: ConditionFormValue[];
  action_source: "coefficient" | "field";
  effect_mode: AidpRuleEffectMode;
  coefficient?: number;
  field?: string;
  field_scale?: number;
  field_transform?: AidpRuleFieldTransform;
  range_start?: number | Dayjs;
  range_end?: number | Dayjs;
}

const CONDITION_LIMIT = 10;

const OPERATOR_LABELS: Record<string, string> = {
  is: "等于",
  is_not: "不等于",
  contains: "包含",
  not_contains: "不包含",
  starts_with: "开头是",
  ends_with: "结尾是",
  in: "包含",
  not_in: "不包含",
  gt: "大于",
  gte: "大于等于",
  lt: "小于",
  lte: "小于等于",
  before: "早于",
  after: "晚于",
  exists: "存在",
  not_exists: "不存在",
  empty: "为空",
  not_empty: "不为空",
  "not empty": "不为空",
};

const NO_VALUE_OPERATORS = new Set([
  "exists",
  "not_exists",
  "empty",
  "not_empty",
  "not empty",
]);

const OPERATORS_BY_TYPE: Record<FieldType, string[]> = {
  string: [
    "is",
    "is_not",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "exists",
    "not_exists",
    "empty",
    "not_empty",
  ],
  number: [
    "is",
    "is_not",
    "gt",
    "gte",
    "lt",
    "lte",
    "exists",
    "not_exists",
    "empty",
    "not_empty",
  ],
  date: [
    "is",
    "is_not",
    "before",
    "after",
    "exists",
    "not_exists",
    "empty",
    "not_empty",
  ],
};

const toBoundaryNumber = (value: number | Dayjs | undefined): number | null => {
  if (value === undefined || value === null) return null;
  return dayjs.isDayjs(value) ? value.valueOf() : Number(value);
};

const buildPayload = (values: RuleFormValues): AidpOntologyRulePayload => {
  const conditions: AidpOntologyRuleCondition[] = values.conditions.map(
    (condition) => ({
      field: condition.field.trim(),
      operator: condition.operator,
      value: NO_VALUE_OPERATORS.has(condition.operator)
        ? ""
        : condition.value === undefined || condition.value === null
          ? ""
          : dayjs.isDayjs(condition.value)
            ? condition.value.format("YYYY-MM-DD HH:mm")
            : condition.value,
    })
  );
  const group: AidpOntologyRuleConditionGroup = {
    logical_operator: values.logical_operator,
    conditions,
  };
  const actionValue: AidpOntologyRuleActionValue =
    values.action_source === "field"
      ? {
          effect_mode: values.effect_mode,
          field: values.field?.trim() || null,
          field_scale: values.field_scale ?? null,
          field_transform: values.field_transform ?? "none",
          field_range:
            values.field_transform === "linear"
              ? [
                  toBoundaryNumber(values.range_start) ?? 0,
                  toBoundaryNumber(values.range_end) ?? 0,
                ]
              : null,
        }
      : {
          effect_mode: values.effect_mode,
          coefficient: values.coefficient ?? 0,
        };
  return {
    name: values.name.trim(),
    description: (values.description ?? "").trim(),
    enabled: values.enabled,
    condition: { type: "json", value: group },
    action: { type: "json", value: actionValue },
  };
};

/** Value control depends on both the field type and the operator. */
const ConditionValueInput: React.FC<{ name: number; fieldType: FieldType }> = ({
  name,
  fieldType,
}) => {
  const operator = Form.useWatch(["conditions", name, "operator"]) as
    string | undefined;
  if (operator && NO_VALUE_OPERATORS.has(operator)) return null;
  if (fieldType === "number") {
    return <InputNumber className={styles.fullWidth} precision={3} />;
  }
  if (fieldType === "date") {
    return <DatePicker showTime className={styles.fullWidth} />;
  }
  return <Input />;
};

const question = (text: string) => (
  <Tooltip title={text}>
    <QuestionCircleOutlined className={styles.questionIcon} />
  </Tooltip>
);

const AidpOntologyRuleDrawer: React.FC<AidpOntologyRuleDrawerProps> = ({
  open,
  domainId,
  ruleId,
  onClose,
  onSaved,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const scope = useAidpQueryScope();
  const demo = useAidpOntologyDemoMode();
  const [form] = Form.useForm<RuleFormValues>();
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const actionSource = Form.useWatch("action_source", form);
  const transform = Form.useWatch("field_transform", form);
  const scaleField = Form.useWatch("field", form);

  const detailQuery = useQuery({
    queryKey: [...scope.key, "ontology-rule", domainId, ruleId],
    queryFn: () => aidpOntologyService.getRule(domainId, ruleId as string),
    enabled: scope.enabled && open && !!ruleId,
    staleTime: 0,
    retry: false,
  });
  const metadataQuery = useQuery({
    queryKey: [...scope.key, "ontology-metadata-fields", domainId],
    queryFn: () => aidpOntologyService.listMetadataFields(domainId),
    enabled: scope.enabled && open,
    staleTime: 30_000,
    retry: false,
  });

  const metadataFields = useMemo(
    () => metadataQuery.data?.value ?? [],
    [metadataQuery.data?.value]
  );
  const fieldTypeByName = useMemo(() => {
    const map = new Map<string, FieldType>();
    metadataFields.forEach((field) => {
      map.set(`metadata_json.${field.field_name}`, field.field_type);
    });
    map.set("title", "string");
    map.set("chunk_type", "string");
    return map;
  }, [metadataFields]);

  const fieldOptions = useMemo(
    () => [
      { value: "title", label: t("aidpKnowledge.ontologyRulesFieldTitle") },
      {
        value: "chunk_type",
        label: t("aidpKnowledge.ontologyRulesFieldChunkType"),
      },
      ...metadataFields.map((field) => ({
        value: `metadata_json.${field.field_name}`,
        label: field.field_name,
      })),
    ],
    [metadataFields, t]
  );

  const scaleFieldOptions = useMemo(
    () =>
      metadataFields
        .filter(
          (field) =>
            field.field_type === "number" || field.field_type === "date"
        )
        .map((field) => ({
          value: `metadata_json.${field.field_name}`,
          label: field.field_name,
          fieldType: field.field_type,
        })),
    [metadataFields]
  );

  const rule = detailQuery.data;
  const editing = !!ruleId;

  const initialValues = useMemo<RuleFormValues>(() => {
    if (!rule) {
      return {
        name: "",
        description: "",
        enabled: true,
        logical_operator: "and",
        conditions: [
          {
            field: "metadata_json.doc_type",
            field_type: "string",
            operator: "is",
            value: "",
          },
        ],
        action_source: "coefficient",
        effect_mode: "add",
        coefficient: 0.1,
        field_transform: "linear",
      };
    }
    const action = rule.action?.value;
    const derived = !!action?.field;
    return {
      name: rule.name,
      description: rule.description,
      enabled: rule.enabled,
      logical_operator: rule.condition?.value?.logical_operator ?? "and",
      conditions: (rule.condition?.value?.conditions ?? []).map(
        (condition) => ({
          field: condition.field,
          field_type: fieldTypeByName.get(condition.field) ?? "string",
          operator: condition.operator,
          value:
            condition.value === null || condition.value === undefined
              ? ""
              : String(condition.value),
        })
      ),
      action_source: derived ? "field" : "coefficient",
      effect_mode: action?.effect_mode ?? "add",
      coefficient: action?.coefficient ?? 0.1,
      field: action?.field ?? undefined,
      field_scale: action?.field_scale ?? undefined,
      field_transform: action?.field_transform ?? "linear",
      range_start: action?.field_range?.[0],
      range_end: action?.field_range?.[1],
    };
  }, [fieldTypeByName, rule]);

  const close = () => {
    setErrorMessage(null);
    setSaving(false);
    onClose();
  };

  const handleSubmit = async () => {
    let values: RuleFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    try {
      const payload = buildPayload(values);
      if (ruleId) {
        await aidpOntologyService.updateRule(domainId, ruleId, payload);
        message.success(
          demo
            ? t("aidpKnowledge.ontologyRulesSavedDemo")
            : t("aidpKnowledge.ontologyRulesSaved")
        );
      } else {
        await aidpOntologyService.createRule(domainId, payload);
        message.success(
          demo
            ? t("aidpKnowledge.ontologyRulesCreatedDemo")
            : t("aidpKnowledge.ontologyRulesCreated")
        );
      }
      onSaved();
    } catch (error) {
      setErrorMessage(
        getAidpErrorMessage(
          error,
          t,
          editing
            ? t("aidpKnowledge.ontologyRulesUpdateFailed")
            : t("aidpKnowledge.ontologyRulesCreateFailed")
        )
      );
    } finally {
      setSaving(false);
    }
  };

  const scaleFieldType =
    scaleFieldOptions.find((option) => option.value === scaleField)
      ?.fieldType ?? "number";

  return (
    <Drawer
      rootClassName={drawerStyles.drawer}
      open={open}
      width={720}
      onClose={close}
      afterOpenChange={(visible) => {
        if (visible) setErrorMessage(null);
      }}
      destroyOnHidden
      title={
        <span className={styles.drawerTitle}>
          {editing
            ? t("aidpKnowledge.ontologyRulesEditTitle")
            : t("aidpKnowledge.ontologyRulesCreateTitle")}
          {question(t("aidpKnowledge.ontologyRulesTitleHint"))}
        </span>
      }
      footer={
        <div className={drawerStyles.footer}>
          <Button onClick={close}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={saving}
            disabled={editing && detailQuery.isLoading}
            onClick={() => void handleSubmit()}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
    >
      {editing && detailQuery.isLoading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : editing && detailQuery.isError ? (
        <div className={drawerStyles.error} role="alert">
          {getAidpErrorMessage(
            detailQuery.error,
            t,
            t("aidpKnowledge.ontologyRulesLoadFailed")
          )}
        </div>
      ) : (
        <Form<RuleFormValues>
          key={open ? `${ruleId ?? "new"}-${rule?.updated_at ?? ""}` : "closed"}
          form={form}
          layout="vertical"
          className={drawerStyles.form}
          initialValues={initialValues}
        >
          <Form.Item
            name="name"
            label={
              <span className={styles.labelWithQuestion}>
                {t("aidpKnowledge.ontologyRulesName")}
                {question(t("aidpKnowledge.ontologyRulesNameHint"))}
              </span>
            }
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item
            name="description"
            label={
              <AidpOntologyFieldLabel
                label={t("aidpKnowledge.ontologyRulesDescription")}
                help={t("aidpKnowledge.ontologyRulesDescriptionHint")}
              />
            }
          >
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 6 }}
              maxLength={512}
              showCount
            />
          </Form.Item>
          <Form.Item
            name="enabled"
            label={
              <span className={styles.labelWithQuestion}>
                {t("aidpKnowledge.ontologyRulesEnabled")}
                {question(t("aidpKnowledge.ontologyRulesEnabledHint"))}
              </span>
            }
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          <section className={styles.section}>
            <div className={styles.sectionTitle}>
              {t("aidpKnowledge.ontologyRulesFilterRules")}
              {question(t("aidpKnowledge.ontologyRulesFilterHint"))}
            </div>
            <div className={styles.conditionHeader}>
              <span>
                {t("aidpKnowledge.ontologyRulesMetadataName")}
                <em className={styles.requiredMark}>*</em>
                {question(t("aidpKnowledge.ontologyRulesConditionFieldHelp"))}
              </span>
              <span>
                {t("aidpKnowledge.ontologyRulesOperatorColumn")}
                <em className={styles.requiredMark}>*</em>
                {question(t("aidpKnowledge.ontologyRulesOperatorHelp"))}
              </span>
              <span>
                {t("aidpKnowledge.ontologyRulesValueColumn")}
                {question(t("aidpKnowledge.ontologyRulesConditionValueHelp"))}
              </span>
              <span aria-hidden="true" />
            </div>
            <Form.List name="conditions">
              {(fields, { add, remove }) => (
                <Form.Item noStyle shouldUpdate>
                  {() => (
                    <div className={styles.conditionList}>
                      {fields.map((field) => {
                        const fieldType =
                          (form.getFieldValue([
                            "conditions",
                            field.name,
                            "field_type",
                          ]) as FieldType | undefined) ?? "string";
                        return (
                          <div key={field.key} className={styles.conditionRow}>
                            <Form.Item
                              {...field}
                              name={[field.name, "field"]}
                              rules={[{ required: true, whitespace: true }]}
                              className={styles.conditionField}
                            >
                              <Select
                                showSearch
                                optionFilterProp="label"
                                options={fieldOptions}
                                onChange={(value: string) => {
                                  form.setFieldValue(
                                    ["conditions", field.name, "field_type"],
                                    fieldTypeByName.get(value) ?? "string"
                                  );
                                  form.setFieldValue(
                                    ["conditions", field.name, "value"],
                                    undefined
                                  );
                                }}
                              />
                            </Form.Item>
                            <Form.Item
                              {...field}
                              name={[field.name, "field_type"]}
                              hidden
                            >
                              <Input />
                            </Form.Item>
                            <Form.Item
                              {...field}
                              name={[field.name, "operator"]}
                              rules={[{ required: true }]}
                              className={styles.conditionOperator}
                            >
                              <Select
                                options={OPERATORS_BY_TYPE[fieldType].map(
                                  (operator) => ({
                                    value: operator,
                                    label:
                                      OPERATOR_LABELS[operator] ?? operator,
                                  })
                                )}
                              />
                            </Form.Item>
                            <Form.Item
                              {...field}
                              name={[field.name, "value"]}
                              className={styles.conditionValue}
                            >
                              <ConditionValueInput
                                name={field.name}
                                fieldType={fieldType}
                              />
                            </Form.Item>
                            <Button
                              type="text"
                              aria-label={t(
                                "aidpKnowledge.ontologyRulesRemoveCondition"
                              )}
                              icon={<DeleteOutlined />}
                              disabled={fields.length <= 1}
                              onClick={() => remove(field.name)}
                            />
                          </div>
                        );
                      })}
                      <Button
                        type="link"
                        className={styles.addCondition}
                        icon={<PlusOutlined />}
                        disabled={fields.length >= CONDITION_LIMIT}
                        onClick={() =>
                          add({
                            field: "title",
                            field_type: "string",
                            operator: "is",
                            value: "",
                          })
                        }
                      >
                        {t("aidpKnowledge.ontologyRulesAddCondition")} (
                        {fields.length}/{CONDITION_LIMIT})
                      </Button>
                    </div>
                  )}
                </Form.Item>
              )}
            </Form.List>
            <Form.Item
              name="logical_operator"
              required
              label={
                <AidpOntologyFieldLabel
                  label={t("aidpKnowledge.ontologyRulesLogicalOperator")}
                  help={t("aidpKnowledge.ontologyRulesLogicalOperatorHint")}
                />
              }
              className={styles.logicalOperator}
            >
              <Radio.Group>
                <Radio value="and">
                  {t("aidpKnowledge.ontologyRulesAndShort")}
                </Radio>
                <Radio value="or">
                  {t("aidpKnowledge.ontologyRulesOrShort")}
                </Radio>
              </Radio.Group>
            </Form.Item>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionTitle}>
              {t("aidpKnowledge.ontologyRulesScoringTitle")}
              {question(t("aidpKnowledge.ontologyRulesScoringHint"))}
            </div>
            <Form.Item
              name="action_source"
              required
              label={
                <AidpOntologyFieldLabel
                  label={t("aidpKnowledge.ontologyRulesActionCoefficient")}
                  help={t("aidpKnowledge.ontologyRulesActionCoefficientHint")}
                />
              }
            >
              <Radio.Group>
                <Radio value="coefficient">
                  {t("aidpKnowledge.ontologyRulesFixedValue")}
                </Radio>
                <Radio value="field">
                  {t("aidpKnowledge.ontologyRulesDynamicScale")}
                </Radio>
              </Radio.Group>
            </Form.Item>
            <Form.Item
              name="effect_mode"
              required
              label={
                <AidpOntologyFieldLabel
                  label={t("aidpKnowledge.ontologyRulesAggregation")}
                  help={t("aidpKnowledge.ontologyRulesAggregationHint")}
                />
              }
            >
              <Radio.Group>
                <Radio value="add">
                  {t("aidpKnowledge.ontologyRulesAddShort")}
                </Radio>
                <Radio value="multiply">
                  {t("aidpKnowledge.ontologyRulesMultiplyShort")}
                </Radio>
              </Radio.Group>
            </Form.Item>

            {actionSource === "field" ? (
              <>
                <Form.Item
                  name="field"
                  label={
                    <AidpOntologyFieldLabel
                      label={t("aidpKnowledge.ontologyRulesScaleMetadata")}
                      help={t("aidpKnowledge.ontologyRulesScaleMetadataHint")}
                    />
                  }
                  rules={[{ required: true }]}
                >
                  <Select options={scaleFieldOptions} />
                </Form.Item>
                <Form.Item
                  name="field_transform"
                  label={
                    <AidpOntologyFieldLabel
                      label={t("aidpKnowledge.ontologyRulesScaleMethod")}
                      help={t("aidpKnowledge.ontologyRulesScaleMethodHint")}
                    />
                  }
                  rules={[{ required: true }]}
                >
                  <Radio.Group>
                    <Radio value="linear">
                      {t("aidpKnowledge.ontologyRulesLinear")}
                    </Radio>
                    <Radio value="log">
                      {t("aidpKnowledge.ontologyRulesLog")}
                    </Radio>
                  </Radio.Group>
                </Form.Item>
                <Form.Item
                  name="field_scale"
                  label={
                    <AidpOntologyFieldLabel
                      label={t("aidpKnowledge.ontologyRulesScaleCoefficient")}
                      help={t(
                        "aidpKnowledge.ontologyRulesScaleCoefficientHint"
                      )}
                    />
                  }
                  rules={[{ required: true }]}
                >
                  <InputNumber className={styles.fullWidth} precision={2} />
                </Form.Item>
                {transform === "linear" && (
                  <div className={styles.rangeBlock}>
                    <AidpOntologyFieldLabel
                      label={t("aidpKnowledge.ontologyRulesLinearRange")}
                      help={t("aidpKnowledge.ontologyRulesLinearRangeHint")}
                    />
                    <div className={styles.rangeRow}>
                      <Form.Item
                        name="range_start"
                        label={t("aidpKnowledge.ontologyRulesRangeMin")}
                        className={styles.rangeItem}
                      >
                        {scaleFieldType === "date" ? (
                          <DatePicker className={styles.fullWidth} />
                        ) : (
                          <InputNumber className={styles.fullWidth} />
                        )}
                      </Form.Item>
                      <Form.Item
                        name="range_end"
                        label={t("aidpKnowledge.ontologyRulesRangeMax")}
                        className={styles.rangeItem}
                      >
                        {scaleFieldType === "date" ? (
                          <DatePicker className={styles.fullWidth} />
                        ) : (
                          <InputNumber className={styles.fullWidth} />
                        )}
                      </Form.Item>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <Form.Item
                name="coefficient"
                label={
                  <AidpOntologyFieldLabel
                    label={t("aidpKnowledge.ontologyRulesCoefficient")}
                    help={t("aidpKnowledge.ontologyRulesCoefficientHint")}
                  />
                }
                rules={[{ required: true }]}
              >
                <InputNumber className={styles.fullWidth} precision={2} />
              </Form.Item>
            )}
          </section>

          {errorMessage && (
            <div className={drawerStyles.error} role="alert">
              {errorMessage}
            </div>
          )}
        </Form>
      )}
    </Drawer>
  );
};

export default AidpOntologyRuleDrawer;
