// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";

import { FileTextOutlined } from "@ant-design/icons";

import styles from "./UploadFileIcon.module.css";

/** Shared file badge used by the import drawer and the upload center. */
const UploadFileIcon: React.FC = () => (
  <span className={styles.icon} aria-hidden="true">
    <FileTextOutlined />
  </span>
);

export default UploadFileIcon;
