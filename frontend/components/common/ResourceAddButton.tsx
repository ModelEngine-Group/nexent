"use client";

import { Button, type ButtonProps } from "antd";
import { Plus } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface ResourceAddButtonProps extends Omit<
  ButtonProps,
  "children" | "icon" | "type" | "variant" | "autoInsertSpace"
> {
  children: ReactNode;
  icon?: ReactNode;
}

export function ResourceAddButton({
  children,
  className,
  icon = <Plus size={24} />,
  ...props
}: ResourceAddButtonProps) {
  return (
    <Button
      {...props}
      autoInsertSpace={false}
      type="default"
      className={cn(
        "!h-12 !w-full !rounded-lg !border-0 !bg-[rgba(25,25,25,0.03)] !px-3 !py-2 !text-sm !font-normal !leading-[22px] !tracking-[0px] !text-[#191919] !shadow-none",
        className
      )}
    >
      <span className="inline-flex h-8 items-center justify-center gap-3">
        <span className="flex size-6 shrink-0 items-center justify-center">
          {icon}
        </span>
        <span className="leading-[22px] tracking-[0px]">{children}</span>
      </span>
    </Button>
  );
}
