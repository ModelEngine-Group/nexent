"use client";

import * as React from "react";
import { Tooltip as AntdTooltip, ConfigProvider } from "antd";
import type { TooltipProps as AntdTooltipProps } from "antd";

import { cn } from "@/lib/utils";

export const TooltipProvider: React.FC<{
  children: React.ReactNode;
}> = ({ children }) => {
  return (
    <ConfigProvider
      theme={{
        components: {
          Tooltip: {
            zIndexPopup: 1050,
          },
        },
      }}
    >
      {children}
    </ConfigProvider>
  );
};

// Tooltip component - wrapper around antd Tooltip with default smooth transition and no arrow
export const Tooltip: React.FC<AntdTooltipProps> = ({
  children,
  arrow = false,
  mouseEnterDelay = 0.1,
  mouseLeaveDelay = 0.1,
  className,
  ...props
}) => {
  // Merge provided classNames with our default root class to replace deprecated overlayClassName
  const mergedClassNames = {
    ...(props.classNames || {}),
    root: cn("ant-tooltip-no-arrow", (props.classNames as any)?.root),
  };
  return (
    <AntdTooltip
      arrow={arrow}
      mouseEnterDelay={mouseEnterDelay}
      mouseLeaveDelay={mouseLeaveDelay}
      classNames={mergedClassNames}
      className={className}
      {...props}
    >
      {children}
    </AntdTooltip>
  );
};

// Re-export for convenience
export { Tooltip as default };
