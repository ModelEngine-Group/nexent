// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useEffect, useState } from "react";

import {
  AIDP_MIN_COLUMN_WIDTH,
  fitAidpColumnWidths,
  resizeAidpColumnPair,
} from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";

/**
 * Shared draggable column widths for ontology tables.
 * `reservedWidth` leaves room for columns outside `keys` (e.g. row selection).
 */
export const useAidpOntologyColumnWidths = <K extends string>(
  keys: readonly K[],
  weights: Record<K, number>,
  reservedWidth = 0
) => {
  // A callback ref keeps observing when the container appears only after async
  // loading; a one-shot effect would miss it and leave every column at the
  // minimum width.
  const [tableNode, setTableNode] = useState<HTMLDivElement | null>(null);
  const tableContainer = useCallback((node: HTMLDivElement | null) => {
    setTableNode(node);
  }, []);
  const [containerWidth, setContainerWidth] = useState(0);
  const [columnWeights, setColumnWeights] =
    useState<Record<K, number>>(weights);

  useEffect(() => {
    if (!tableNode) return;
    const measure = (width?: number) => {
      setContainerWidth(width ?? tableNode.clientWidth);
    };
    measure();
    const observer = new ResizeObserver(([entry]) => {
      measure(entry.contentRect.width);
    });
    observer.observe(tableNode);
    return () => observer.disconnect();
  }, [tableNode]);

  const usableWidth = containerWidth
    ? Math.max(
        containerWidth - reservedWidth,
        keys.length * AIDP_MIN_COLUMN_WIDTH
      )
    : keys.reduce((sum, key) => sum + columnWeights[key], 0);
  const columnWidths = fitAidpColumnWidths(keys, columnWeights, usableWidth);
  const totalWidth = keys.reduce((sum, key) => sum + columnWidths[key], 0);

  const handleResize = (
    key: K,
    nextKey: K,
    delta: number,
    renderedWidths: Record<string, number>
  ) => {
    const resized = resizeAidpColumnPair(renderedWidths, key, nextKey, delta);
    setColumnWeights((current) => {
      const totalWeight = keys.reduce((sum, item) => sum + current[item], 0);
      const total = keys.reduce((sum, item) => sum + resized[item], 0) || 1;
      const next = { ...current };
      keys.forEach((item) => {
        next[item] = (resized[item] / total) * totalWeight;
      });
      return next;
    });
  };

  return { tableContainer, columnWidths, totalWidth, handleResize };
};
