import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ApiError } from "./api";

/** True for errors the user or the server will not fix by retrying (4xx, except timeout/rate limit). */
export function isClientError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 408 &&
    error.status !== 429
  );
}

/** True when the session is missing, expired or not allowed to use the app. */
export function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

const MAX_RETRIES = 2;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Lab states change server-side: data is considered fresh briefly, then
      // refreshed when the user comes back to the tab or the network returns.
      staleTime: 15_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      // Network errors and 5xx/503 (cluster unreachable) are retried with
      // exponential backoff; 4xx answers are final.
      retry: (failureCount, error) => !isClientError(error) && failureCount < MAX_RETRIES,
      retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 10_000),
    },
    mutations: {
      retry: false,
    },
  },
});

export function QueryProvider({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
