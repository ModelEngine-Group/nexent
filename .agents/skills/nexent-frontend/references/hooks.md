# Hooks and state

- Use TypeScript and `useXxx` names under existing domain folders. Return objects with descriptive names and loading/error/success state.
- Use TanStack React Query `useQuery` for shared server data, `useMemo` for derived filtering/sorting, and `useMutation` with affected-query invalidation for mutations.
- Avoid duplicating shared-query fetching with `useEffect` state. Effects remain appropriate for subscriptions, timers, and local side effects; clean them up and declare correct dependencies.
- Use `useState` for local state, `useReducer` for coupled transitions, and Context for genuinely shared state. Preserve immutable updates and correct asynchronous transitions.
- Use `useCallback`, `useMemo`, and `useRef` when identity, computation, or mutable references justify them; do not mechanically wrap every function.
- Expose useful async errors. Retry transient failures through existing query/request policy, avoiding unbounded or duplicated retries.
- Use `frontend/lib/logger.ts`. Verify cleanup, state transitions, errors, and query invalidation.
