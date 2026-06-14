import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { Activity, Cpu, HardDrive, MemoryStick, Server } from "lucide-react";
import { PageHeader } from "../components/AppShell";
import { ErrorState, LoadingState, MetricCard } from "../components/ui";
import { getClusterStats } from "../lib/api";
import { cpuDisplay, memoryDisplay } from "../lib/format";
import { useI18n } from "../lib/i18n";

export default function AdminStatsPage() {
  const { locale } = useI18n();
  const stats = useQuery({
    queryKey: ["cluster-stats"],
    queryFn: getClusterStats,
    refetchInterval: 30_000,
  });

  const nodes = Array.isArray(stats.data?.nodes) ? stats.data!.nodes : [];

  // Agrégat de capacité cluster (construit à partir des nœuds)
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
        title={locale === "fr" ? "Stats cluster" : "Cluster stats"}
        subtitle={locale === "fr" ? "Vue détaillée de l'état du cluster Kubernetes — rafraîchissement automatique toutes les 30s." : "Detailed view of the Kubernetes cluster status — auto-refresh every 30s."}
      />

      {stats.isLoading ? <LoadingState label={locale === "fr" ? "Récupération des métriques cluster..." : "Retrieving cluster metrics..."} /> : null}
      {stats.error ? (
        <ErrorState>{locale === "fr" ? "Stats cluster indisponibles. Vérifiez la connexion à l'API Kubernetes." : "Cluster stats unavailable. Check the connection to the Kubernetes API."}</ErrorState>
      ) : null}

      {stats.data ? (
        <div className="grid gap-4">
          <section className="metric-grid">
            {[
              {
                label: locale === "fr" ? "Nœuds" : "Nodes",
                value: nodes.length,
                icon: <Server size={18} />,
                hint: locale === "fr" ? "Total cluster" : "Cluster total",
              },
              {
                label: "Deployments",
                value: (
                  <>
                    {stats.data.ready_deployments ?? "-"}
                    <span className="muted ml-1.5 text-[0.85rem]">/ {stats.data.total_deployments ?? "-"}</span>
                  </>
                ),
                icon: <Activity size={18} />,
                hint: "Ready / Total",
              },
              {
                label: "Pods",
                value: stats.data.total_pods ?? "-",
                icon: <Activity size={18} />,
                hint: locale === "fr" ? "Tous namespaces" : "All namespaces",
              },
              {
                label: "Namespaces",
                value: stats.data.total_namespaces ?? "-",
                icon: <HardDrive size={18} />,
                hint: "Total",
              },
            ].map((m, i) => (
              <motion.div
                key={m.label}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] }}
              >
                <MetricCard label={m.label} value={m.value} icon={m.icon} hint={m.hint} />
              </motion.div>
            ))}
          </section>

          {/* Capacité agrégée du cluster — barres construites à partir des tokens */}
          {capacity.cpuTotal > 0 || capacity.memTotal > 0 ? (
            <section className="grid gap-3.5 md:grid-cols-2">
              <CapacityCard
                icon={<Cpu size={18} />}
                label={locale === "fr" ? "CPU agrégé" : "Aggregate CPU"}
                percent={cpuPct}
                tone={cpuTone}
                detail={`${cpuDisplay(capacity.cpuUsed)} / ${cpuDisplay(capacity.cpuTotal)}`}
              />
              <CapacityCard
                icon={<MemoryStick size={18} />}
                label={locale === "fr" ? "Mémoire agrégée" : "Aggregate memory"}
                percent={memPct}
                tone={memTone}
                detail={`${memoryDisplay(capacity.memUsed)} / ${memoryDisplay(capacity.memTotal)}`}
              />
            </section>
          ) : null}

          <section className="panel">
            <div className="section-head">
              <h2>{locale === "fr" ? "Nœuds du cluster" : "Cluster nodes"}</h2>
              <span className="badge blue">
                {stats.isFetching
                  ? (locale === "fr" ? "Actualisation..." : "Refreshing...")
                  : stats.dataUpdatedAt
                    ? (locale === "fr"
                        ? `Mis à jour ${new Date(stats.dataUpdatedAt).toLocaleTimeString("fr-FR")}`
                        : `Updated at ${new Date(stats.dataUpdatedAt).toLocaleTimeString()}`)
                    : ""}
              </span>
            </div>

            {nodes.length > 0 ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{locale === "fr" ? "Nœud" : "Node"}</th>
                      <th>Roles</th>
                      <th>Version</th>
                      <th>Pods</th>
                      <th className="min-w-[200px]">CPU</th>
                      <th className="min-w-[200px]">{locale === "fr" ? "Mémoire" : "Memory"}</th>
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
                            <strong>{node.name || "N/A"}</strong>
                          </td>
                          <td>
                            <span className="badge">{node.roles || "worker"}</span>
                          </td>
                          <td>
                            <span className="badge">{node.kubelet_version || "N/A"}</span>
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
              <pre className="pre-wrap text-[0.8rem]">
                {JSON.stringify(stats.data, null, 2)}
              </pre>
            )}
          </section>
        </div>
      ) : null}
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
    <div className="card relative overflow-hidden p-[18px]">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[0.84rem] font-medium text-[var(--muted)]">
          <span className="text-[var(--primary)]">{icon}</span>
          {label}
        </span>
        <strong
          className="text-[1.6rem] leading-none"
          style={{ fontFamily: "var(--font-display)", letterSpacing: "-0.02em" }}
        >
          {percent}%
        </strong>
      </div>
      <div className="meter-track mt-3">
        <div className={`meter-fill ${tone}`} style={{ width: `${Math.min(100, percent)}%` }} />
      </div>
      <span className="muted mt-2 block text-[0.82rem]">{detail}</span>
    </div>
  );
}
