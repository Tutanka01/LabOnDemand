import { AlertTriangle, RefreshCw, RotateCcw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { useI18n } from "../lib/i18n";

const CHUNK_RELOAD_KEY = "labondemand.chunk-reload-at";

/** A lazily loaded chunk could not be fetched (typically: a new version was deployed). */
export function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return /dynamically imported module|module script failed|Unable to preload CSS|ChunkLoadError/i.test(
    `${error.name} ${error.message}`,
  );
}

/**
 * Reloads the page to fetch the new index.html after a deployment, at most once
 * per minute so a genuinely missing chunk cannot cause a reload loop.
 * Returns false when a reload was already attempted recently.
 */
export function reloadForNewVersion(): boolean {
  try {
    const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || 0);
    if (Date.now() - last < 60_000) return false;
    sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()));
  } catch {
    // Without storage we cannot guard against loops: let the user reload.
    return false;
  }
  window.location.reload();
  return true;
}

interface ErrorBoundaryProps {
  children: ReactNode;
  /** The boundary resets when this value changes (e.g. the current pathname). */
  resetKey?: unknown;
  fullPage?: boolean;
}

interface ErrorBoundaryState {
  error: Error | null;
  resetKey: unknown;
}

/** Catches render errors so a crash in one page shows a recoverable screen instead of a blank app. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error };
  }

  static getDerivedStateFromProps(props: ErrorBoundaryProps, state: ErrorBoundaryState): Partial<ErrorBoundaryState> | null {
    if (props.resetKey !== state.resetKey) return { error: null, resetKey: props.resetKey };
    return null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info.componentStack);
    if (isChunkLoadError(error)) reloadForNewVersion();
  }

  private reset = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;
    return <ErrorFallback error={this.state.error} onRetry={this.reset} fullPage={this.props.fullPage} />;
  }
}

// Plain markup on purpose: this file is part of the entry chunk and must not
// import components/ui.tsx (Radix, TanStack Table).
function ErrorFallback({ error, onRetry, fullPage }: { error: Error; onRetry: () => void; fullPage?: boolean }) {
  const { t } = useI18n();
  const chunkError = isChunkLoadError(error);

  return (
    <div className={fullPage ? "grid min-h-screen place-items-center p-6" : "grid place-items-center py-10"}>
      <div className="error-state max-w-md" role="alert">
        <AlertTriangle size={22} aria-hidden="true" />
        <strong>{chunkError ? t("shell.error.update_title") : t("shell.error.title")}</strong>
        <span>{chunkError ? t("shell.error.update_body") : t("shell.error.body")}</span>
        <div className="actions-row justify-center">
          {chunkError ? null : (
            <button type="button" className="btn" onClick={onRetry}>
              <RotateCcw size={16} aria-hidden="true" />
              {t("shell.error.retry")}
            </button>
          )}
          <button type="button" className="btn primary" onClick={() => window.location.reload()}>
            <RefreshCw size={16} aria-hidden="true" />
            {t("shell.error.reload")}
          </button>
        </div>
      </div>
    </div>
  );
}
