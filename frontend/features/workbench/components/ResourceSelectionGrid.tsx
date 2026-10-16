import { Children, type HTMLAttributes } from "react";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import { cn } from "@/lib/utils";
import { Empty } from "antd";

export const RESOURCE_SELECTION_AREA_CLASS = "min-h-[460px]";

export function ResourceSelectionGrid({
  children,
  className,
  columns = 3,
  fillAvailable = false,
  layout = "grid",
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  columns?: number;
  fillAvailable?: boolean;
  layout?: "grid" | "list";
}) {
  if (layout === "list") {
    return (
      <div
        role="listbox"
        {...props}
        className={cn(
          fillAvailable ? "min-h-full" : RESOURCE_SELECTION_AREA_CLASS,
          className
        )}
      >
        {Children.count(children) > 0 ? (
          children
        ) : (
          <Empty className="py-12" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </div>
    );
  }
  return (
    <div
      {...props}
      className={cn(
        fillAvailable ? "min-h-full" : RESOURCE_SELECTION_AREA_CLASS,
        "[&_.grid]:auto-rows-[220px] [&_.grid]:gap-3",
        className
      )}
    >
      <ResourceCardGrid
        items={Children.toArray(children)}
        columns={columns}
        rows={Math.ceil(6 / columns)}
        paginateItems={false}
        showToolbar={false}
        showCreateCard={false}
        renderItem={(item) => item}
      />
    </div>
  );
}
