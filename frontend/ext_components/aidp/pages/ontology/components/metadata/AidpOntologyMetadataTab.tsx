// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";

import AidpOntologyMetadataFields from "./AidpOntologyMetadataFields";
import styles from "./AidpOntologyMetadataTab.module.css";

interface AidpOntologyMetadataTabProps {
  domainId: string;
  autoOpenCreate?: boolean;
}

const AidpOntologyMetadataTab: React.FC<AidpOntologyMetadataTabProps> = ({
  domainId,
  autoOpenCreate = false,
}) => {
  return (
    <div className={styles.container}>
      <div className={styles.body}>
        <AidpOntologyMetadataFields
          domainId={domainId}
          autoOpenCreate={autoOpenCreate}
        />
      </div>
    </div>
  );
};

export default AidpOntologyMetadataTab;
