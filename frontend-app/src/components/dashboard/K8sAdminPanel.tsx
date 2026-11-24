import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FolderTree, RefreshCw, Server, Trash2 } from "lucide-react";
import { useState } from "react";
import { deletePod, getAllK8sDeployments, getAllPods, getAllPvcs, getNamespaces, getUsageMyApps, pingK8s } from "../../lib/api";
import { shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { VolumeTarget } from "../../types/api";
import { VolumeBrowserDialog } from "../files/VolumeBrowserDialog";
import { Button, ConfirmDialog, EmptyState, IconButton, MetricCard, SkeletonRows, StatusBadge, showToast } from "../ui";
import { QueryProblem, problemDetail } from "./QueryProblem";

const ADMIN_QUERY_KEYS = [["namespaces"], ["all-pvcs"], ["all-pods"], ["k8s-usage-my-apps"], ["raw-k8s-deployments"], ["k8s-ping"]];

export function K8sAdminPanel({ admin }: { admin: boolean }) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  if (!admin) return null;

  return (
    <section className="panel">
      <div className="section-head flex-wrap">
        <h2 className="!m-0">
          <button
            type="button"
            className="btn ghost flex items-center gap-2 px-2 py-1"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-controls="k8s-admin-panel"
          >
            {open ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
            <Server size={16} className="text-[var(--primary)]" aria-hidden="true" />
            {t("k8spanel.title")} <span className="badge">{t("k8spanel.admin_badge")}</span>
          </button>
        </h2>
        {open ? (
          <Button
            onClick={() => {
              ADMIN_QUERY_KEYS.forEach((queryKey) => void queryClient.invalidateQueries({ queryKey }));
            }}
          >
            <RefreshCw size={16} aria-hidden="true" /> {t("common.refresh")}
          </Button>
        ) : null}
      </div>
      {open ? (
        <div className="grid gap-4" id="k8s-admin-panel">
          <ClusterPingView />
          <NamespacesView />
          <PodsView />
          <RawDeploymentsView />
          <UsageView />
          <GlobalPvcView />
        </div>
      ) : null}
    </section>
  );
}

function ClusterPingView() {
  const { t } = useI18n();
  const ping = useQuery({ queryKey: ["k8s-ping"], queryFn: pingK8s, refetchInterval: 30_000 });
  return (
    <section className="metric-grid">
      <MetricCard
        label={t("k8spanel.cluster")}
        value={ping.isLoading ? "…" : ping.data ? t("k8spanel.cluster_ok") : t("k8spanel.cluster_down")}
        icon={<Server size={18} aria-hidden="true" />}
      />
    </section>
  );
}

function NamespacesView() {
  const { t } = useI18n();
  const ns = useQuery({ queryKey: ["namespaces"], queryFn: getNamespaces, staleTime: 30_000 });

  return (
    <div>
      <h3>{t("k8spanel.namespaces")}</h3>
      {ns.isLoading ? <SkeletonRows rows={3} cols={2} /> : null}
      {ns.error ? (
        <QueryProblem error={ns.error} title={t("k8spanel.namespaces_error")} onRetry={() => void ns.refetch()} retrying={ns.isFetching} stale={Boolean(ns.data)} />
      ) : null}
      {ns.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("k8spanel.name")}</th>
                <th>{t("details.status")}</th>
              </tr>
            </thead>
            <tbody>
              {ns.data.map((item) => (
                <tr key={item.name}>
                  <td>{item.name}</td>
                  <td>
                    <StatusBadge state={item.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function PodsView() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const pods = useQuery({ queryKey: ["all-pods"], queryFn: getAllPods, staleTime: 30_000 });
  const deleteMut = useMutation({
    mutationFn: (pod: { namespace: string; name: string }) => deletePod(pod.namespace, pod.name),
    onSuccess: (_data, pod) => {
      void queryClient.invalidateQueries({ queryKey: ["all-pods"] });
      showToast(t("k8spanel.pod_deleted", { name: pod.name }), "success");
    },
    onError: (error, pod) => showToast(t("k8spanel.pod_delete_failed", { name: pod.name, detail: problemDetail(error) }), "error"),
  });

  return (
    <div>
      <h3>{t("k8spanel.pods")}</h3>
      {pods.isLoading ? <SkeletonRows rows={4} cols={5} /> : null}
      {pods.error ? (
        <QueryProblem error={pods.error} title={t("k8spanel.pods_error")} onRetry={() => void pods.refetch()} retrying={pods.isFetching} stale={Boolean(pods.data)} />
      ) : null}
      {pods.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("details.pod")}</th>
                <th>{t("details.namespace")}</th>
                <th>{t("details.status")}</th>
                <th>{t("details.ip")}</th>
                <th>
                  <span className="sr-only">{t("dashboard.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {pods.data.map((pod) => (
                <tr key={`${pod.namespace}-${pod.name}`}>
                  <td>{pod.name}</td>
                  <td>{pod.namespace}</td>
                  <td>
                    <StatusBadge state={pod.status || pod.phase} />
                  </td>
                  <td>{pod.ip || "—"}</td>
                  <td>
                    <ConfirmDialog
                      destructive
                      title={t("k8spanel.delete_pod_title")}
                      description={t("k8spanel.delete_pod_description", { name: pod.name, namespace: pod.namespace })}
                      confirmLabel={t("common.delete")}
                      trigger={
                        <Button variant="danger" aria-label={t("k8spanel.delete_pod_named", { name: pod.name })}>
                          <Trash2 size={14} aria-hidden="true" />
                        </Button>
                      }
                      onConfirm={() => deleteMut.mutate({ namespace: pod.namespace, name: pod.name })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function RawDeploymentsView() {
  const { t } = useI18n();
  const deployments = useQuery({ queryKey: ["raw-k8s-deployments"], queryFn: getAllK8sDeployments, staleTime: 30_000 });
  return (
    <div>
      <h3>{t("k8spanel.raw_deployments")}</h3>
      {deployments.isLoading ? <SkeletonRows rows={3} cols={3} /> : null}
      {deployments.error ? (
        <QueryProblem
          error={deployments.error}
          title={t("k8spanel.deployments_error")}
          onRetry={() => void deployments.refetch()}
          retrying={deployments.isFetching}
          stale={Boolean(deployments.data)}
        />
      ) : null}
      {deployments.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("k8spanel.name")}</th>
                <th>{t("details.namespace")}</th>
                <th>{t("k8spanel.ready")}</th>
              </tr>
            </thead>
            <tbody>
              {deployments.data.map((deployment) => (
                <tr key={`${deployment.namespace}-${deployment.name}`}>
                  <td>{deployment.name}</td>
                  <td>{deployment.namespace}</td>
                  <td>
                    {deployment.ready_replicas || 0}/{deployment.replicas ?? "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function UsageView() {
  const { t } = useI18n();
  const usage = useQuery({ queryKey: ["k8s-usage-my-apps"], queryFn: getUsageMyApps, staleTime: 30_000 });
  return (
    <div>
      <h3>{t("k8spanel.usage")}</h3>
      {usage.isLoading ? <SkeletonRows rows={3} cols={5} /> : null}
      {usage.error ? (
        <QueryProblem error={usage.error} title={t("k8spanel.usage_error")} onRetry={() => void usage.refetch()} retrying={usage.isFetching} stale={Boolean(usage.data)} />
      ) : null}
      {usage.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("k8spanel.app")}</th>
                <th>{t("details.namespace")}</th>
                <th>{t("launch.cpu")}</th>
                <th>{t("launch.memory")}</th>
                <th>{t("k8spanel.pods")}</th>
              </tr>
            </thead>
            <tbody>
              {usage.data.map((item) => (
                <tr key={`${item.namespace}-${item.name}`}>
                  <td>{item.name}</td>
                  <td>{item.namespace || "—"}</td>
                  <td>{item.cpu_m}m</td>
                  <td>{item.mem_mi}Mi</td>
                  <td>{item.pods ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function GlobalPvcView() {
  const { t, locale } = useI18n();
  const [browseTarget, setBrowseTarget] = useState<{ target: VolumeTarget; title: string } | null>(null);
  const pvcs = useQuery({ queryKey: ["all-pvcs"], queryFn: getAllPvcs, staleTime: 60_000 });

  return (
    <div>
      <h3>{t("k8spanel.all_volumes")}</h3>
      {pvcs.isLoading ? <SkeletonRows rows={3} cols={6} /> : null}
      {pvcs.error ? (
        <QueryProblem error={pvcs.error} title={t("volumes.load_error")} onRetry={() => void pvcs.refetch()} retrying={pvcs.isFetching} stale={Boolean(pvcs.data)} />
      ) : null}
      {pvcs.data && pvcs.data.length === 0 ? <EmptyState title={t("volumes.empty_title")} /> : null}
      {pvcs.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("volumes.volume")}</th>
                <th>{t("details.namespace")}</th>
                <th>{t("details.status")}</th>
                <th>{t("volumes.capacity")}</th>
                <th>{t("volumes.last_lab")}</th>
                <th>{t("volumes.created")}</th>
                <th>
                  <span className="sr-only">{t("dashboard.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {pvcs.data.map((pvc) => (
                <tr key={`${pvc.namespace}-${pvc.name}`}>
                  <td>{pvc.name}</td>
                  <td>{pvc.namespace || "—"}</td>
                  <td>
                    <span className={`badge ${pvc.bound ? "amber" : "green"}`}>{pvc.phase || "—"}</span>
                  </td>
                  <td>{pvc.storage || "—"}</td>
                  <td>{pvc.last_bound_app || pvc.app_type || "—"}</td>
                  <td>{shortDate(pvc.created_at, locale)}</td>
                  <td>
                    {pvc.namespace ? (
                      <IconButton
                        title={t("files.browse")}
                        aria-label={t("files.browse")}
                        onClick={() =>
                          setBrowseTarget({
                            target: { namespace: pvc.namespace!, pvc: pvc.name },
                            title: pvc.name,
                          })
                        }
                      >
                        <FolderTree size={14} aria-hidden="true" />
                      </IconButton>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {browseTarget ? (
        <VolumeBrowserDialog
          target={browseTarget.target}
          title={`${browseTarget.title} — ${t("files.title")}`}
          onClose={() => setBrowseTarget(null)}
        />
      ) : null}
    </div>
  );
}
