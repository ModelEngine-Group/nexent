// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { effectiveRoles } from "@/lib/roles";
import { ObservabilityAccess } from "../components/ObservabilityAccess";
import { ImportedTrajectories } from "../components/ImportedTrajectories";
import "../trajectory.css";

export default function ImportedTrajectoriesPage() {
  return (
    <ObservabilityAccess>
      {(user) => (
        <ImportedTrajectories
          key={JSON.stringify([user.id, user.tenantId, effectiveRoles(user)])}
          user={user}
        />
      )}
    </ObservabilityAccess>
  );
}
