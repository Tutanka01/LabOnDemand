import { AlertTriangle, CloudOff, RefreshCw } from "lucide-react";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, ErrorState } from "../ui";

/** The API answers 503 when Kubernetes cannot be reached. */
export function isClusterDown(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503;
}

export function problemDetail(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "";
}

function RetryButton({ onRetry, retrying }: { onRetry: () => void; retrying?: boolean }) {
  const { t } = useI18n();
  return (
    <Button onClick={onRetry} disabled={retrying}>
      <RefreshCw size={15} className={retrying ? "animate-spin" : undefined} aria-hidden="true" />
      {retrying ? t("labs.retrying") : t("labs.retry")}
    </Button>
  );
}

/**
 * Explains why a panel could not load. A cluster outage (HTTP 503) gets a calm explanation;
 * other failures show the server's message. With `stale`, the panel still shows the last
 * known data and this renders as a compact banner above it.
 */
export function QueryProblem({
  error,
  onRetry,
  retrying,
  stale = false,
  title,
}: {
  error: unknown;
  onRetry: () => void;
  retrying?: boolean;
  stale?: boolean;
  /** Title for generic errors, e.g. "Unable to load volumes". */
  title: string;
}) {
  const { t } = useI18n();
  const down = isClusterDown(error);
  const detail = problemDetail(error);

  if (stale) {
    return (
      <div
        role="status"
        className="mb-3 flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border px-3 py-2 text-[var(--text-sm)]"
        style={{
          borderColor: "color-mix(in srgb, var(--warning) 35%, var(--border))",
          background: "color-mix(in srgb, var(--warning) 6%, var(--surface))",
        }}
      >
        {down ? (
          <CloudOff size={16} className="shrink-0 text-[var(--warning)]" aria-hidden="true" />
        ) : (
          <AlertTriangle size={16} className="shrink-0 text-[var(--warning)]" aria-hidden="true" />
        )}
        <span className="min-w-0 flex-1">
          {down ? t("labs.stale_cluster_down") : t("labs.stale_error", { detail })}
        </span>
        <RetryButton onRetry={onRetry} retrying={retrying} />
      </div>
    );
  }

  if (down) {
    return (
      <div className="empty-state" role="status">
        <CloudOff size={22} className="text-[var(--warning)]" aria-hidden="true" />
        <strong>{t("labs.cluster_down_title")}</strong>
        <span>{t("labs.cluster_down_body")}</span>
        <RetryButton onRetry={onRetry} retrying={retrying} />
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      <ErrorState title={title}>{detail || t("labs.unknown_error")}</ErrorState>
      <div className="flex justify-center">
        <RetryButton onRetry={onRetry} retrying={retrying} />
      </div>
    </div>
  );
}
