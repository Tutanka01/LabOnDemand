import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { getAllPvcs, getNamespaces } from "../../lib/api";
import { shortDate } from "../../lib/format";
import type { PvcInfo } from "../../types/api";
import { Button, ConfirmDialog, EmptyState, ErrorState, LoadingState, StatusBadge } from "../ui";

export function K8sAdminPanel({ admin }: { admin: boolean }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  if (!admin) return null;

  return (
    <section className="panel">
      <div className="section-head">
        <h2>
          <button
            className="btn ghost"
            onClick={() => setOpen(!open)}
            style={{ padding: "4px 8px" }}
          >
            {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            Ressources Kubernetes (admin)
          </button>
        </h2>
        <Button onClick={() => {
          queryClient.invalidateQueries({ queryKey: ["namespaces"] });
          queryClient.invalidateQueries({ queryKey: ["all-pvcs"] });
        }}>
          <RefreshCw size={16} /> Actualiser
        </Button>
      </div>
      {open ? (
        <div style={{ display: "grid", gap: 18 }}>
          <NamespacesView />
          <GlobalPvcView />
        </div>
      ) : null}
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
      {ns.isLoading ? <LoadingState /> : null}
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
      {pvcs.isLoading ? <LoadingState /> : null}
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
