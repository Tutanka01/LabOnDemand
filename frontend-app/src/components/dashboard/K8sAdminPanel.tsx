import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RefreshCw, Server, Trash2 } from "lucide-react";
import { useState } from "react";
import { deletePod, getAllK8sDeployments, getAllPods, getAllPvcs, getNamespaces, getUsageMyApps, pingK8s } from "../../lib/api";
import { shortDate } from "../../lib/format";
import { Button, ConfirmDialog, EmptyState, ErrorState, MetricCard, SkeletonRows, StatusBadge, showToast } from "../ui";

export function K8sAdminPanel({ admin }: { admin: boolean }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  if (!admin) return null;

  return (
    <section className="panel">
      <div className="section-head">
        <h2 className="!m-0">
          <button
            className="btn ghost flex items-center gap-2 px-2 py-1"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
          >
            {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <Server size={16} className="text-[var(--primary)]" />
            Ressources Kubernetes <span className="badge blue">admin</span>
          </button>
        </h2>
        <Button onClick={() => {
          queryClient.invalidateQueries({ queryKey: ["namespaces"] });
          queryClient.invalidateQueries({ queryKey: ["all-pvcs"] });
          queryClient.invalidateQueries({ queryKey: ["all-pods"] });
          queryClient.invalidateQueries({ queryKey: ["k8s-usage-my-apps"] });
          queryClient.invalidateQueries({ queryKey: ["raw-k8s-deployments"] });
        }}>
          <RefreshCw size={16} /> Actualiser
        </Button>
      </div>
      {open ? (
        <div className="grid gap-[18px]">
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
  const ping = useQuery({ queryKey: ["k8s-ping"], queryFn: pingK8s, refetchInterval: 30_000 });
  return (
    <section className="metric-grid">
      <MetricCard label="Cluster" value={ping.data ? "OK" : "Indisponible"} icon={<RefreshCw size={18} />} />
    </section>
  );
}

function NamespacesView() {
  const ns = useQuery({
    queryKey: ["namespaces"],
    queryFn: getNamespaces,
    staleTime: 30_000,
  });

  return (
    <div>
      <h3>Namespaces</h3>
      {ns.isLoading ? <SkeletonRows rows={3} cols={2} /> : null}
      {ns.error ? <ErrorState>Impossible de charger les namespaces.</ErrorState> : null}
      {ns.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Nom</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {ns.data.map((item) => (
                <tr key={item.name}>
                  <td>{item.name}</td>
                  <td><StatusBadge state={item.status} /></td>
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
  const queryClient = useQueryClient();
  const pods = useQuery({ queryKey: ["all-pods"], queryFn: getAllPods, staleTime: 30_000 });
  const deleteMut = useMutation({
    mutationFn: (pod: { namespace: string; name: string }) => deletePod(pod.namespace, pod.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["all-pods"] });
      showToast("Pod supprime", "success");
    },
  });

  return (
    <div>
      <h3>Pods</h3>
      {pods.isLoading ? <SkeletonRows rows={4} cols={5} /> : null}
      {pods.error ? <ErrorState>Impossible de charger les pods.</ErrorState> : null}
      {pods.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Pod</th>
                <th>Namespace</th>
                <th>Statut</th>
                <th>IP</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pods.data.map((pod) => (
                <tr key={`${pod.namespace}-${pod.name}`}>
                  <td>{pod.name}</td>
                  <td>{pod.namespace}</td>
                  <td><StatusBadge state={pod.status || pod.phase} /></td>
                  <td>{pod.ip || "N/A"}</td>
                  <td>
                    <ConfirmDialog
                      destructive
                      title="Supprimer le pod"
                      description={`Supprimer ${pod.name} dans ${pod.namespace} ? Kubernetes peut le recreer si un deployment le gere.`}
                      confirmLabel="Supprimer"
                      trigger={<Button variant="danger"><Trash2 size={14} /></Button>}
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
  const deployments = useQuery({ queryKey: ["raw-k8s-deployments"], queryFn: getAllK8sDeployments, staleTime: 30_000 });
  return (
    <div>
      <h3>Deployments Kubernetes bruts</h3>
      {deployments.isLoading ? <SkeletonRows rows={3} cols={3} /> : null}
      {deployments.error ? <ErrorState>Impossible de charger les deployments.</ErrorState> : null}
      {deployments.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Nom</th><th>Namespace</th><th>Ready</th></tr>
            </thead>
            <tbody>
              {deployments.data.map((deployment) => (
                <tr key={`${deployment.namespace}-${deployment.name}`}>
                  <td>{deployment.name}</td>
                  <td>{deployment.namespace}</td>
                  <td>{deployment.ready_replicas || 0}/{deployment.replicas || "-"}</td>
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
  const usage = useQuery({ queryKey: ["k8s-usage-my-apps"], queryFn: getUsageMyApps, staleTime: 30_000 });
  return (
    <div>
      <h3>Usage de mes apps</h3>
      {usage.isLoading ? <SkeletonRows rows={3} cols={5} /> : null}
      {usage.error ? <ErrorState>Impossible de charger l'usage.</ErrorState> : null}
      {usage.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>App</th><th>Namespace</th><th>CPU</th><th>Memoire</th><th>Pods</th></tr>
            </thead>
            <tbody>
              {usage.data.map((item) => (
                <tr key={`${item.namespace}-${item.name}`}>
                  <td>{item.name}</td>
                  <td>{item.namespace || "N/A"}</td>
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
  const queryClient = useQueryClient();
  const pvcs = useQuery({
    queryKey: ["all-pvcs"],
    queryFn: getAllPvcs,
    staleTime: 60_000,
  });

  return (
    <div>
      <h3>Tous les volumes persistants</h3>
      {pvcs.isLoading ? <SkeletonRows rows={3} cols={6} /> : null}
      {pvcs.error ? <ErrorState>Impossible de charger les volumes.</ErrorState> : null}
      {pvcs.data && pvcs.data.length === 0 ? <EmptyState title="Aucun volume" /> : null}
      {pvcs.data?.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Volume</th>
                <th>Namespace</th>
                <th>Etat</th>
                <th>Capacite</th>
                <th>Application</th>
                <th>Cree le</th>
              </tr>
            </thead>
            <tbody>
              {pvcs.data.map((pvc) => (
                <tr key={pvc.name}>
                  <td>{pvc.name}</td>
                  <td>{pvc.namespace || "N/A"}</td>
                  <td><span className={`badge ${pvc.bound ? "amber" : "green"}`}>{pvc.phase || "N/A"}</span></td>
                  <td>{pvc.storage || "N/A"}</td>
                  <td>{pvc.last_bound_app || pvc.app_type || "N/A"}</td>
                  <td>{shortDate(pvc.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
