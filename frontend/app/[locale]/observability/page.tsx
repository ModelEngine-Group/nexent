// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { effectiveRoles } from "@/lib/roles";
import { ObservabilityAccess } from "./components/ObservabilityAccess";
import { ObservabilityCenter } from "./components/ObservabilityCenter";
import "./trajectory.css";

export default function ObservabilityPage() {
  return (
    <ObservabilityAccess>
      {(user) => (
        <ObservabilityCenter
          key={JSON.stringify([user.id, user.tenantId, effectiveRoles(user)])}
          user={user}
        />
      )}
    </ObservabilityAccess>
  );
}
