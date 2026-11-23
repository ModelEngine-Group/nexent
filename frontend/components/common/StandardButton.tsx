import { Button as AntButton, type ButtonProps as AntButtonProps } from "antd";

import { cn } from "@/lib/utils";

export interface StandardButtonProps extends Omit<
  AntButtonProps,
  "autoInsertSpace" | "type" | "variant"
> {
  variant?: "default" | "primary";
}

const BASE_CLASSES =
  "!h-8 !w-fit !cursor-pointer !rounded-[4px] !px-4 !py-[5px] !text-[14px] !leading-[22px] ![letter-spacing:0px] [&>span]:![letter-spacing:0px] !shadow-none";

const VARIANT_CLASSES: Record<
  NonNullable<StandardButtonProps["variant"]>,
  string
> = {
  default:
    "!border !border-solid !border-[#c9c9c9] !bg-transparent !text-[#191919]",
  primary: "!border-0 !bg-[#0067d1] !text-white",
};

export function StandardButton({
  className,
  variant = "default",
  ...props
}: StandardButtonProps) {
  return (
    <AntButton
      {...props}
      autoInsertSpace={false}
      type="default"
      className={cn(BASE_CLASSES, VARIANT_CLASSES[variant], className)}
    />
  );
}
