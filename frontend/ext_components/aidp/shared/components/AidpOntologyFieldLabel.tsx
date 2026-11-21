// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";

import { QuestionCircleOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";

import styles from "./AidpOntologyFieldLabel.module.css";

interface AidpOntologyFieldLabelProps {
  label: React.ReactNode;
  help?: React.ReactNode;
  /** Custom labels outside Form.Item need to render their own required mark. */
  required?: boolean;
}

/** Label with a user-facing help tooltip, shared by ontology forms. */
const AidpOntologyFieldLabel: React.FC<AidpOntologyFieldLabelProps> = ({
  label,
  help,
  required = false,
}) => (
  <span className={styles.label}>
    {required && (
      <span className={styles.required} aria-hidden="true">
        *
      </span>
    )}
    {label}
    {help ? (
      <Tooltip title={help}>
        <QuestionCircleOutlined
          className={styles.helpIcon}
          aria-label={typeof help === "string" ? help : undefined}
        />
      </Tooltip>
    ) : null}
  </span>
);

export default AidpOntologyFieldLabel;
