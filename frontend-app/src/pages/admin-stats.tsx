import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Activity, Cpu, HardDrive, MemoryStick, Server } from "lucide-react";
import { PageHeader } from "../components/AppShell";
import { EmptyState, LoadingState, MetricCard, QueryState } from "../components/ui";
import { getClusterStats } from "../lib/api";
import { cpuDisplay, memoryDisplay } from "../lib/format";
import { useI18n } from "../lib/i18n";

export default function AdminStatsPage() {
  const { locale, t } = useI18n();
  const stats = useQuery({
    queryKey: ["cluster-stats"],
    queryFn: getClusterStats,
    // Node usage changes continuously; TanStack Query pauses this poll while the tab is hidden.
    refetchInterval: 30_000,
  });

  const nodes = Array.isArray(stats.data?.nodes) ? stats.data!.nodes : [];

  // Aggregate cluster capacity, summed over the nodes
  const capacity = nodes.reduce(
    (acc, node) => {
      acc.cpuUsed += node.cpu_usage_m || 0;
      acc.cpuTotal += node.cpu_allocatable_m || 0;
      acc.memUsed += node.mem_usage_mi || 0;
      acc.memTotal += node.mem_allocatable_mi || 0;
      return acc;
    },
    { cpuUsed: 0, cpuTotal: 0, memUsed: 0, memTotal: 0 },
  );
  const cpuPct = capacity.cpuTotal ? Math.round((capacity.cpuUsed / capacity.cpuTotal) * 100) : 0;
  const memPct = capacity.memTotal ? Math.round((capacity.memUsed / capacity.memTotal) * 100) : 0;
  const cpuTone = cpuPct >= 90 ? "danger" : cpuPct >= 75 ? "warn" : "";
  const memTone = memPct >= 90 ? "danger" : memPct >= 75 ? "warn" : "";

  return (
    <>
      <PageHeader
        title={t("admin.stats_title")}
        subtitle={t("admin.stats_subtitle")}
      />

      <QueryState
        query={stats}
        skeleton={<LoadingState label={t("admin.stats_loading")} />}
        errorTitle={t("admin.stats_error")}
      >
      {stats.data ? (
        <div className="grid gap-4">
          <section className="metric-grid">
            {[
              {
                label: t("admin.stats_nodes"),
                value: nodes.length,
                icon: <Server size={18} />,
                hint: t("admin.stats_cluster_total"),
              },
              {
                label: t("admin.stats_deployments"),
                value: (
                  <>
                    {stats.data.ready_deployments ?? "-"}
                    <span className="muted ml-1.5 text-sm">/ {stats.data.total_deployments ?? "-"}</span>
                  </>
                ),
                icon: <Activity size={18} />,
                hint: t("admin.stats_ready_total"),
              },
              {
                label: t("admin.stats_pods"),
                value: stats.data.total_pods ?? "-",
                icon: <Activity size={18} />,
                hint: t("admin.stats_all_namespaces"),
              },
              {
                label: t("admin.col_namespace"),
                value: stats.data.total_namespaces ?? "-",
                icon: <HardDrive size={18} />,
                hint: t("admin.metric_total"),
              },
            ].map((m) => (
              <MetricCard key={m.label} label={m.label} value={m.value} icon={m.icon} hint={m.hint} />
            ))}
          </section>

          {/* Aggregate cluster capacity, bars built from the CSS tokens */}
          {capacity.cpuTotal > 0 || capacity.memTotal > 0 ? (
            <section className="grid gap-3.5 md:grid-cols-2">
              <CapacityCard
                icon={<Cpu size={18} />}
                label={t("admin.stats_aggregate_cpu")}
                percent={cpuPct}
                tone={cpuTone}
                detail={`${cpuDisplay(capacity.cpuUsed)} / ${cpuDisplay(capacity.cpuTotal)}`}
              />
              <CapacityCard
                icon={<MemoryStick size={18} />}
                label={t("admin.stats_aggregate_memory")}
                percent={memPct}
                tone={memTone}
                detail={`${memoryDisplay(capacity.memUsed)} / ${memoryDisplay(capacity.memTotal)}`}
              />
            </section>
          ) : null}

          <section className="panel">
            <div className="section-head">
              <h2>{t("admin.stats_cluster_nodes")}</h2>
              <span className="badge blue" aria-live="polite">
                {stats.isFetching
                  ? t("admin.stats_refreshing")
                  : stats.dataUpdatedAt
                    ? t("admin.stats_updated_at", {
                        time: new Date(stats.dataUpdatedAt).toLocaleTimeString(locale),
                      })
                    : ""}
              </span>
            </div>

            {nodes.length > 0 ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("admin.stats_node")}</th>
                      <th>{t("admin.stats_roles")}</th>
                      <th>{t("admin.stats_version")}</th>
                      <th>{t("admin.stats_pods")}</th>
                      <th className="min-w-[200px]">CPU</th>
                      <th className="min-w-[200px]">{t("admin.stats_memory")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodes.map((node, i) => {
                      const nodeCpuPercent =
                        node.cpu_usage_m != null && node.cpu_allocatable_m
                          ? Math.round((node.cpu_usage_m / node.cpu_allocatable_m) * 100)
                          : 0;
                      const nodeMemPercent =
                        node.mem_usage_mi != null && node.mem_allocatable_mi
                          ? Math.round((node.mem_usage_mi / node.mem_allocatable_mi) * 100)
                          : 0;
                      const nodeCpuTone = nodeCpuPercent >= 90 ? "danger" : nodeCpuPercent >= 75 ? "warn" : "";
                      const nodeMemTone = nodeMemPercent >= 90 ? "danger" : nodeMemPercent >= 75 ? "warn" : "";

                      return (
                        <tr key={node.name || i}>
                          <td>
                            <strong>{node.name || "—"}</strong>
                          </td>
                          <td>
                            <span className="badge">{node.roles || "worker"}</span>
                          </td>
                          <td>
                            <span className="badge">{node.kubelet_version || "—"}</span>
                          </td>
                          <td>{node.pods ?? "-"}</td>
                          <td>
                            <div className="resource-meter min-w-[180px]">
                              <div className="meter-head">
                                <span>
                                  {cpuDisplay(node.cpu_usage_m || 0)} /{" "}
                                  {cpuDisplay(node.cpu_allocatable_m || 0)}
                                </span>
                                <strong>{nodeCpuPercent}%</strong>
                              </div>
                              <div className="meter-track">
                                <div
                                  className={`meter-fill ${nodeCpuTone}`}
                                  style={{ width: `${nodeCpuPercent}%` }}
                                />
                              </div>
                            </div>
                          </td>
                          <td>
                            <div className="resource-meter min-w-[180px]">
                              <div className="meter-head">
                                <span>
                                  {memoryDisplay(node.mem_usage_mi || 0)} /{" "}
                                  {memoryDisplay(node.mem_allocatable_mi || 0)}
                                </span>
                                <strong>{nodeMemPercent}%</strong>
                              </div>
                              <div className="meter-track">
                                <div
                                  className={`meter-fill ${nodeMemTone}`}
                                  style={{ width: `${nodeMemPercent}%` }}
                                />
                              </div>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title={t("admin.stats_no_nodes")}>{t("admin.stats_no_nodes_hint")}</EmptyState>
            )}
          </section>
        </div>
      ) : null}
      </QueryState>
    </>
  );
}

function CapacityCard({
  icon,
  label,
  percent,
  tone,
  detail,
}: {
  icon: ReactNode;
  label: string;
  percent: number;
  tone: string;
  detail: string;
}) {
  return (
    <div className="card metric-card">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-xs font-medium text-[var(--muted)]">
          <span className="text-[var(--muted)]">{icon}</span>
          {label}
        </span>
        <strong className="text-2xl">{percent}%</strong>
      </div>
      <div className="meter-track mt-3">
        <div className={`meter-fill ${tone}`} style={{ width: `${Math.min(100, percent)}%` }} />
      </div>
      <span className="muted mt-2 block text-xs">{detail}</span>
    </div>
  );
}
