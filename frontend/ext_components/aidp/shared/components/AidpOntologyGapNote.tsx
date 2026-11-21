// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { WarningOutlined } from "@ant-design/icons";

import styles from "./AidpOntologyGapNote.module.css";

interface AidpOntologyGapNoteProps {
  /** Short label stating what is missing. */
  title?: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Always-visible note for an AIDP capability gap. It stays in the page at the
 * affected control instead of being hidden in a tooltip or a page-level banner,
 * so the missing contract and its user impact are visible on screen.
 */
const AidpOntologyGapNote: React.FC<AidpOntologyGapNoteProps> = ({
  title,
  children,
  className,
}) => (
  <div
    className={`${styles.note} ${className ?? ""}`}
    role="note"
    aria-label={title}
  >
    <WarningOutlined className={styles.icon} aria-hidden="true" />
    <div className={styles.content}>
      {title && <div className={styles.title}>{title}</div>}
      <div className={styles.body}>{children}</div>
    </div>
  </div>
);

export default AidpOntologyGapNote;
