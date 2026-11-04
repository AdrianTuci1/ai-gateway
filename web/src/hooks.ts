import { useCallback, useEffect, useRef, useState } from "react";

type AsyncState<T> = {
  data: T | null;
  error: Error | null;
  loading: boolean;
};

export function useAsync<T>(
  loader: () => Promise<T>,
  deps: unknown[],
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: true,
  });
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    loaderRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((error: Error) => {
        if (!cancelled) setState({ data: null, error, loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { ...state, reload };
}

type PagedState<T> = {
  items: T[];
  total: number;
  page: number;
  error: Error | null;
  loading: boolean;
};

export function usePage<T>(
  loader: (
    page: number,
    snapshot: string | null,
  ) => Promise<{ items: T[]; total: number; snapshot: string | null }>,
  deps: unknown[],
): PagedState<T> & { reload: () => void; goTo: (page: number) => void } {
  const depsKey = JSON.stringify(deps);
  const [request, setRequest] = useState({
    page: 1,
    snapshot: null as string | null,
    key: depsKey,
    nonce: 0,
  });
  const [state, setState] = useState<PagedState<T>>({
    items: [],
    total: 0,
    page: 1,
    error: null,
    loading: true,
  });
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const snapshotRef = useRef<{ key: string; value: string | null }>({
    key: depsKey,
    value: null,
  });

  useEffect(() => {
    if (request.key !== depsKey) {
      setRequest({ page: 1, snapshot: null, key: depsKey, nonce: 0 });
      return;
    }
    let cancelled = false;
    setState((previous) => ({
      ...previous,
      page: request.page,
      error: null,
      loading: true,
    }));
    loaderRef
      .current(request.page, request.snapshot)
      .then((result) => {
        if (cancelled) return;
        snapshotRef.current = {
          key: depsKey,
          value: result.snapshot ?? request.snapshot,
        };
        setState({
          items: result.items,
          total: result.total,
          page: request.page,
          error: null,
          loading: false,
        });
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setState((previous) => ({
          ...previous,
          page: request.page,
          error,
          loading: false,
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [depsKey, request]);

  const reload = useCallback(() => {
    snapshotRef.current = { key: depsKey, value: null };
    setRequest((previous) => ({
      page: 1,
      snapshot: null,
      key: depsKey,
      nonce: previous.nonce + 1,
    }));
  }, [depsKey]);

  const goTo = useCallback(
    (page: number) => {
      if (page < 1) return;
      const snapshot =
        snapshotRef.current.key === depsKey ? snapshotRef.current.value : null;
      setRequest({ page, snapshot, key: depsKey, nonce: 0 });
    },
    [depsKey],
  );

  const pending = request.key !== depsKey || state.page !== request.page;
  return {
    ...state,
    page: request.key === depsKey ? request.page : 1,
    loading: state.loading || pending,
    reload,
    goTo,
  };
}

export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
