"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  RotateCcwIcon,
  ShieldCheckIcon,
} from "lucide-react";

import type { VerificationPresentation } from "../adapter/remote-chat-model-adapter";
import { cn } from "@/lib/utils";

const presentationByPhase = {
  pass: {
    icon: CheckCircle2Icon,
    className: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  final_pass: {
    icon: CheckCircle2Icon,
    className: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  warning: {
    icon: AlertTriangleIcon,
    className: "border-amber-200 bg-amber-50 text-amber-700",
  },
  repair: {
    icon: RotateCcwIcon,
    className: "border-amber-200 bg-amber-50 text-amber-700",
  },
  blocked: {
    icon: AlertTriangleIcon,
    className: "border-red-200 bg-red-50 text-red-700",
  },
  final_fail: {
    icon: AlertTriangleIcon,
    className: "border-red-200 bg-red-50 text-red-700",
  },
} as const;

export const VerificationStatus = ({
  verification,
}: {
  verification: VerificationPresentation;
}) => {
  const presentation =
    presentationByPhase[verification.phase as keyof typeof presentationByPhase];
  const Icon = presentation?.icon ?? ShieldCheckIcon;
  const score =
    typeof verification.score === "number"
      ? `${Math.round(verification.score * 100)}%`
      : undefined;

  return (
    <div
      className={cn(
        "mt-2 flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium",
        presentation?.className ?? "border-blue-200 bg-blue-50 text-blue-700"
      )}
      role="status"
      data-verification-phase={verification.phase}
    >
      <Icon className="size-4 shrink-0" />
      <span>{verification.message}</span>
      {score && <span className="ml-auto opacity-70">{score}</span>}
    </div>
  );
};
