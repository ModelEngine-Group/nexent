// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { FileText, Folder } from "lucide-react";

export default function SkillFileTreeTitle({
  name,
  isFile,
}: {
  name: string;
  isFile: boolean;
}) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      {isFile ? (
        <FileText size={15} className="shrink-0 text-primary" aria-hidden />
      ) : (
        <Folder size={15} className="shrink-0" aria-hidden />
      )}
      <span className="min-w-0 truncate" title={name}>
        {name}
      </span>
    </span>
  );
}
