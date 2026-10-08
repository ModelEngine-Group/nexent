import type { CSSProperties } from "react";
import { Card as AntCard, type CardProps as AntCardProps } from "antd";

import { cn } from "@/lib/utils";

export interface StandardCardProps extends Omit<AntCardProps, "bordered"> {
  bordered?: boolean;
  borderRadius?: CSSProperties["borderRadius"];
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
}

export function StandardCard({
  bordered = false,
  borderRadius,
  className,
  height,
  style,
  width,
  ...props
}: StandardCardProps) {
  return (
    <AntCard
      {...props}
      variant={bordered ? "outlined" : "borderless"}
      className={cn(
        "rounded-[8px] bg-[#fff]",
        !bordered && "!border-0",
        className
      )}
      style={{
        ...style,
        ...(width === undefined ? {} : { width }),
        ...(height === undefined ? {} : { height }),
        ...(borderRadius === undefined ? {} : { borderRadius }),
      }}
    />
  );
}
