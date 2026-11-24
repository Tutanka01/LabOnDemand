import { useQuery } from "@tanstack/react-query";
import { getQuotas } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { ResourceMeter, Skeleton } from "../ui";
import { QueryProblem } from "./QueryProblem";

/** Resource usage of the current user against their quota. */
export function QuotaPanel() {
  const { t } = useI18n();
  const quotas = useQuery({ queryKey: ["quotas"], queryFn: getQuotas });

  return (
    <section className="panel min-w-0" aria-labelledby="quota-title">
      <div className="section-head">
        <h2 id="quota-title">{t("labs.quota_title")}</h2>
      </div>
      {quotas.isLoading ? (
        <div className="grid gap-3.5" aria-busy="true">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="grid gap-2">
              <Skeleton className="h-3.5 w-1/3" />
              <Skeleton className="h-2 w-full rounded-full" />
            </div>
          ))}
        </div>
      ) : null}
      {quotas.error ? (
        <QueryProblem
          error={quotas.error}
          title={t("labs.quota_load_error")}
          onRetry={() => void quotas.refetch()}
          retrying={quotas.isFetching}
          stale={Boolean(quotas.data)}
        />
      ) : null}
      {quotas.data ? (
        <div className="grid gap-3.5">
          <ResourceMeter label={t("labs.quota_apps")} used={quotas.data.usage.apps_used} max={quotas.data.limits.max_apps} />
          <ResourceMeter label={t("launch.cpu")} used={quotas.data.usage.cpu_m_used} max={quotas.data.limits.max_requests_cpu_m} unit="m" />
          <ResourceMeter
            label={t("launch.memory")}
            used={quotas.data.usage.mem_mi_used}
            max={quotas.data.limits.max_requests_mem_mi}
            unit="Mi"
          />
          {quotas.data.limits.max_storage_gi != null ? (
            <ResourceMeter
              label={t("labs.quota_storage")}
              used={quotas.data.usage.storage_gi_used || 0}
              max={quotas.data.limits.max_storage_gi}
              unit="Gi"
            />
          ) : null}
          <p className="muted m-0 text-[var(--text-xs)]">{t("labs.quota_hint")}</p>
        </div>
      ) : null}
    </section>
  );
}
