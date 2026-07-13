import { Button } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

interface OffsetPaginationProps {
  mode: "offset";
  current: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}

interface CursorPaginationProps {
  mode: "cursor";
  page: number;
  resultCount: number;
  hasPrevPage: boolean;
  hasNextPage: boolean;
  onPrevPage: () => void;
  onNextPage: () => void;
}

type McpToolsPaginationProps = OffsetPaginationProps | CursorPaginationProps;

export default function McpToolsPagination(props: McpToolsPaginationProps) {
  const { t } = useTranslation("common");

  if (props.mode === "offset") {
    if (props.total <= props.pageSize) return null;
    const totalPages = Math.ceil(props.total / props.pageSize);
    return (
      <div className="flex items-center justify-center gap-1.5 pt-4">
        <Button
          type="default"
          className="flex size-9 items-center justify-center rounded-lg p-0"
          disabled={props.current <= 1}
          onClick={() => props.onChange(Math.max(1, props.current - 1))}
          aria-label="Previous page"
        >
          <ChevronLeft className="size-4" />
        </Button>
        {Array.from({ length: totalPages }, (_, index) => index + 1).map(
          (pageNumber) => (
            <Button
              key={pageNumber}
              type={pageNumber === props.current ? "primary" : "default"}
              className="flex size-9 items-center justify-center rounded-lg p-0"
              onClick={() => props.onChange(pageNumber)}
              aria-current={pageNumber === props.current ? "page" : undefined}
            >
              {pageNumber}
            </Button>
          )
        )}
        <Button
          type="default"
          className="flex size-9 items-center justify-center rounded-lg p-0"
          disabled={props.current >= totalPages}
          onClick={() => props.onChange(Math.min(totalPages, props.current + 1))}
          aria-label="Next page"
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center gap-2 pt-2">
      <span className="text-sm text-slate-600">
        {t("mcpTools.community.pageResult", {
          page: props.page,
          count: props.resultCount,
        })}
      </span>
      <Button
        type="default"
        className="flex size-9 items-center justify-center rounded-lg p-0"
        disabled={!props.hasPrevPage}
        onClick={props.onPrevPage}
        aria-label={t("mcpTools.community.prevPage")}
      >
        <ChevronLeft className="size-4" />
      </Button>
      <Button
        type="default"
        className="flex size-9 items-center justify-center rounded-lg p-0"
        disabled={!props.hasNextPage}
        onClick={props.onNextPage}
        aria-label={t("mcpTools.community.nextPage")}
      >
        <ChevronRight className="size-4" />
      </Button>
    </div>
  );
}
