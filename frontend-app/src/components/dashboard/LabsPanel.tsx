import { Plus, RefreshCw } from "lucide-react";
import { type useDeployments, openLabViaDetails } from "../../hooks/useDeployments";
import { useI18n } from "../../lib/i18n";
import type { Deployment } from "../../types/api";
import { LabCard } from "../LabCard";
import { Button, EmptyState, SkeletonCards } from "../ui";
import { QueryProblem } from "./QueryProblem";

/** "Your labs" panel: live lab cards with their loading, empty and error states. */
export function LabsPanel({
  labsState,
  onDetails,
  onBrowseCatalog,
}: {
  labsState: ReturnType<typeof useDeployments>;
  onDetails: (deployment: Deployment) => void;
  onBrowseCatalog: () => void;
}) {
  const { t } = useI18n();
  const { query, labs, justReady, transitional, runAction } = labsState;
  const hasData = query.data !== undefined;

  return (
    <section className="panel min-w-0" aria-labelledby="labs-title">
      <div className="section-head flex-wrap">
        <div className="flex items-center gap-2.5">
          <h2 id="labs-title">{t("labs.title")}</h2>
          {labs.length ? <span className="badge">{labs.length}</span> : null}
        </div>
        {transitional && hasData && !query.error ? (
          <span className="muted inline-flex items-center gap-1.5 text-[var(--text-xs)]" role="status">
            <RefreshCw size={13} className={query.isFetching ? "animate-spin" : undefined} aria-hidden="true" />
            {t("labs.auto_refresh")}
          </span>
        ) : null}
      </div>

      {query.isLoading ? <SkeletonCards count={2} lines={2} /> : null}

      {query.error ? (
        <QueryProblem
          error={query.error}
          title={t("labs.load_error")}
          onRetry={() => void query.refetch()}
          retrying={query.isFetching}
          stale={hasData}
        />
      ) : null}

      {hasData && labs.length === 0 && !query.error ? (
        <EmptyState title={t("dashboard.no_labs")}>
          <span className="grid justify-items-center gap-3">
            {t("labs.empty_hint")}
            <Button variant="primary" onClick={onBrowseCatalog}>
              <Plus size={16} aria-hidden="true" />
              {t("labs.empty_cta")}
            </Button>
          </span>
        </EmptyState>
      ) : null}

      {labs.length ? (
        <div className="lab-list">
          {labs.map((lab) => (
            <LabCard
              key={lab.key}
              lab={lab}
              highlight={justReady.has(lab.key)}
              onOpenFallback={(deployment) => void openLabViaDetails(deployment, t)}
              onDetails={onDetails}
              onAction={runAction}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
