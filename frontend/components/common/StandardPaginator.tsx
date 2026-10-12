import { Pagination, type PaginationProps } from "antd";

import { cn } from "@/lib/utils";

export type StandardPaginatorProps = PaginationProps;

export function StandardPaginator({
  className,
  ...props
}: StandardPaginatorProps) {
  return (
    <Pagination
      {...props}
      className={cn(
        "text-[14px] ![letter-spacing:0px] text-[#191919]",
        className
      )}
    />
  );
}
