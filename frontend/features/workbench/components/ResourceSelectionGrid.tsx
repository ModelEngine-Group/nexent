import { Children, type HTMLAttributes } from "react";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import { cn } from "@/lib/utils";

export const RESOURCE_SELECTION_AREA_CLASS = "min-h-[460px]";

export function ResourceSelectionGrid({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...props}
      className={cn(
        RESOURCE_SELECTION_AREA_CLASS,
        "[&_.grid]:auto-rows-[220px] [&_.grid]:gap-3",
        className
      )}
    >
      <ResourceCardGrid
        items={Children.toArray(children)}
        columns={2}
        paginateItems={false}
        showToolbar={false}
        showCreateCard={false}
        renderItem={(item) => item}
      />
    </div>
  );
}
