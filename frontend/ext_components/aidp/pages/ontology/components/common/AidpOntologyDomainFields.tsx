// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Form, Input } from "antd";

import AidpOntologyFieldLabel from "@/ext_components/aidp/shared/components/AidpOntologyFieldLabel";
import {
  ONTOLOGY_DESCRIPTION_MAX_BYTES,
  ONTOLOGY_NAME_MAX_BYTES,
  ONTOLOGY_NAME_MAX_CHARS,
  byteCountText,
  validateOntologyDescription,
  validateOntologyName,
} from "@/ext_components/aidp/shared/utils/aidpOntologyValidation";

/** Shared name/description fields for creating or editing an ontology domain. */
const AidpOntologyDomainFields: React.FC<{
  nameValue: string;
  descriptionValue: string;
  descriptionMinRows?: number;
  descriptionMaxRows?: number;
}> = ({
  nameValue,
  descriptionValue,
  descriptionMinRows = 3,
  descriptionMaxRows = 6,
}) => {
  const { t } = useTranslation();
  return (
    <>
      <Form.Item
        name="name"
        required
        label={
          <AidpOntologyFieldLabel
            label={t("aidpKnowledge.ontologyDomainName")}
            help={t("aidpKnowledge.ontologyDomainNameHint")}
          />
        }
        extra={byteCountText(
          nameValue,
          ONTOLOGY_NAME_MAX_BYTES,
          t("aidpKnowledge.ontologyBytesUnit")
        )}
        rules={[
          {
            validator: async (_rule, value: string) => {
              const error = validateOntologyName(value ?? "", t);
              if (error) throw new Error(error);
            },
          },
        ]}
      >
        <Input maxLength={ONTOLOGY_NAME_MAX_CHARS} />
      </Form.Item>
      <Form.Item
        name="description"
        label={
          <AidpOntologyFieldLabel
            label={t("aidpKnowledge.ontologyDomainDescription")}
            help={t("aidpKnowledge.ontologyDomainDescriptionHint")}
          />
        }
        extra={byteCountText(
          descriptionValue,
          ONTOLOGY_DESCRIPTION_MAX_BYTES,
          t("aidpKnowledge.ontologyBytesUnit")
        )}
        rules={[
          {
            validator: async (_rule, value: string) => {
              const error = validateOntologyDescription(value ?? "", t);
              if (error) throw new Error(error);
            },
          },
        ]}
      >
        <Input.TextArea
          autoSize={{ minRows: descriptionMinRows, maxRows: descriptionMaxRows }}
        />
      </Form.Item>
    </>
  );
};

export default AidpOntologyDomainFields;
