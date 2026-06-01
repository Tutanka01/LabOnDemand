import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import { Activity, HardDrive, Server } from "lucide-react";
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
        <>
          <section className="metric-grid">
            <MetricCard
              label={locale === "fr" ? "Nœuds" : "Nodes"}
              value={nodes.length}
              icon={<Server size={18} />}
              hint="Total"
            />
            <MetricCard
              label="Deployments"
              value={
                <>
                  {stats.data.ready_deployments ?? "-"}
                  <span className="muted ml-1.5 text-[0.85rem]">
                    / {stats.data.total_deployments ?? "-"}
                  </span>
                </>
              }
              icon={<Activity size={18} />}
              hint="Ready / Total"
            />
            <MetricCard
              label="Pods"
              value={stats.data.total_pods ?? "-"}
              icon={<Activity size={18} />}
              hint={locale === "fr" ? "Tous namespaces" : "All namespaces"}
            />
            <MetricCard
              label="Namespaces"
              value={stats.data.total_namespaces ?? "-"}
              icon={<HardDrive size={18} />}
              hint="Total"
            />
          </section>

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
                      const cpuPercent =
                        node.cpu_usage_m != null && node.cpu_allocatable_m
                          ? Math.round((node.cpu_usage_m / node.cpu_allocatable_m) * 100)
                          : 0;
                      const memPercent =
                        node.mem_usage_mi != null && node.mem_allocatable_mi
                          ? Math.round((node.mem_usage_mi / node.mem_allocatable_mi) * 100)
                          : 0;
                      const cpuTone = cpuPercent >= 90 ? "danger" : cpuPercent >= 75 ? "warn" : "";
                      const memTone = memPercent >= 90 ? "danger" : memPercent >= 75 ? "warn" : "";

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
                                <strong>{cpuPercent}%</strong>
                              </div>
                              <div className="meter-track">
                                <div
                                  className={`meter-fill ${cpuTone}`}
                                  style={{ width: `${cpuPercent}%` }}
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
                                <strong>{memPercent}%</strong>
                              </div>
                              <div className="meter-track">
                                <div
                                  className={`meter-fill ${memTone}`}
                                  style={{ width: `${memPercent}%` }}
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
        </>
      ) : null}
    </>
  );
}
