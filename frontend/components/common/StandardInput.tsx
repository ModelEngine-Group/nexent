import { Input as AntInput, type InputProps } from "antd";

import { cn } from "@/lib/utils";

export type StandardInputProps = InputProps;

export function StandardInput({ className, ...props }: StandardInputProps) {
  return (
    <AntInput
      {...props}
      className={cn(
        "!h-7 !rounded-[4px] !border !border-solid !border-[#c9c9c9]",
        className
      )}
    />
  );
}
