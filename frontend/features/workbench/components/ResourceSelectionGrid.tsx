import { Children, type HTMLAttributes } from "react";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";

export function ResourceSelectionGrid({
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...props}>
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
