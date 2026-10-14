import { Children, type HTMLAttributes } from "react";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import { cn } from "@/lib/utils";

export const RESOURCE_SELECTION_AREA_CLASS = "min-h-[460px]";

export function ResourceSelectionGrid({
  children,
  className,
  columns = 3,
  fillAvailable = false,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  columns?: number;
  fillAvailable?: boolean;
}) {
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
