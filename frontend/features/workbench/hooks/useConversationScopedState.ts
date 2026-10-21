// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useState, type SetStateAction } from "react";

/** Reset local UI state before children observe a different conversation. */
export function useConversationScopedState<T>(key: string, initialValue: T) {
  const [state, setState] = useState({ key, value: initialValue });
  if (state.key !== key) {
    setState({ key, value: initialValue });
  }

  const setValue = useCallback(
    (update: SetStateAction<T>) => {
      setState((current) => {
        // An asynchronous callback still belongs to the session that created it.
        if (current.key !== key) return current;
        const value =
          typeof update === "function"
            ? (update as (previous: T) => T)(current.value)
            : update;
        return Object.is(value, current.value) ? current : { key, value };
      });
    },
    [key]
  );

  return [state.key === key ? state.value : initialValue, setValue] as const;
}
