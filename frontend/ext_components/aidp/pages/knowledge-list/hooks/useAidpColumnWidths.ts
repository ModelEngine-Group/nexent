import { useEffect, useRef, useState } from "react";
import type { AidpKbColumnKey } from "../types";
import {
  AIDP_KB_DEFAULT_COLUMNS,
  AIDP_KB_REQUIRED_COLUMNS,
  BASE_COLUMN_WEIGHTS,
} from "../constants";
import {
  fitAidpColumnWidths,
  resizeAidpColumnPair,
} from "../utils/aidpKnowledgeColumnWidths";

export const useAidpColumnWidths = (visibleColumns: AidpKbColumnKey[]) => {
  const [columnWeights, setColumnWeights] = useState(BASE_COLUMN_WEIGHTS);
  const tableContainer = useRef<HTMLElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  useEffect(() => {
    const element = tableContainer.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const activeKeys = AIDP_KB_DEFAULT_COLUMNS.filter(
    (key) =>
      AIDP_KB_REQUIRED_COLUMNS.includes(key) || visibleColumns.includes(key)
  );
  const columnWidths = fitAidpColumnWidths(
    activeKeys,
    columnWeights,
    containerWidth ||
      activeKeys.reduce((sum, key) => sum + columnWeights[key], 0)
  );

  const handleResize = (
    key: AidpKbColumnKey,
    nextKey: AidpKbColumnKey,
    delta: number,
    renderedWidths: Record<string, number>
  ) => {
    const resized = resizeAidpColumnPair(renderedWidths, key, nextKey, delta);
    if (
      Math.abs(resized[key] - columnWidths[key]) < 0.02 &&
      Math.abs(resized[nextKey] - columnWidths[nextKey]) < 0.02
    )
      return;
    // Preserve hidden-column preferences in the same weight scale.
    setColumnWeights((current) => {
      const totalWeight = activeKeys.reduce(
        (sum, item) => sum + current[item],
        0
      );
      const totalWidth = activeKeys.reduce(
        (sum, item) => sum + resized[item],
        0
      );
      const next = { ...current };
      activeKeys.forEach((item) => {
        next[item] = (resized[item] / totalWidth) * totalWeight;
      });
      return next;
    });
  };

  return { tableContainer, activeKeys, columnWidths, handleResize };
};
