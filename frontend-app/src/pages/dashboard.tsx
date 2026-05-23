import "../styles/main.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Cpu, Database, Gauge, Monitor, Plus, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AppShell, PageHeader } from "../components/AppShell";
import { LabCard } from "../components/LabCard";
import { TemplateCard } from "../components/TemplateCard";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  ResourceMeter,
  SearchBox,
  StatusBadge,
  ToastContainer,
  showToast,
} from "../components/ui";
import {
  deleteDeployment,
  deletePvc,
  getDeploymentDetails,
  getDeployments,
  getPvcs,
  getQuotas,
  getTemplates,
  setDeploymentLifecycle,
} from "../lib/api";
import { shortDate } from "../lib/format";
import type { Deployment, PvcInfo, Template, User } from "../types/api";
import { QueryProvider } from "../lib/query";
import { LaunchDialog } from "../components/dashboard/LaunchDialog";
import { DeploymentDetailsDialog } from "../components/dashboard/DeploymentDetailsDialog";
import { K8sAdminPanel } from "../components/dashboard/K8sAdminPanel";

function Dashboard({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const [templateQuery, setTemplateQuery] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [detailsTarget, setDetailsTarget] = useState<Deployment | null>(null);
  const [novncTarget, setNovncTarget] = useState<Deployment | null>(null);

  const deployments = useQuery({ queryKey: ["deployments"], queryFn: getDeployments });
  const quotas = useQuery({ queryKey: ["quotas"], queryFn: getQuotas });
  const pvcs = useQuery({ queryKey: ["pvcs"], queryFn: getPvcs });
  const templates = useQuery({ queryKey: ["templates"], queryFn: getTemplates });

  const invalidateDashboard = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["deployments"] }),
      queryClient.invalidateQueries({ queryKey: ["quotas"] }),
      queryClient.invalidateQueries({ queryKey: ["pvcs"] }),
    ]);
  };

  const deleteMutation = useMutation({
    mutationFn: (deployment: Deployment) => deleteDeployment(deployment.namespace, deployment.name),
    onSuccess: () => {
      invalidateDashboard();
      showToast("Lab supprime", "success");
    },
  });

  const lifecycleMutation = useMutation({
    mutationFn: ({ deployment, action }: { deployment: Deployment; action: "pause" | "resume" }) =>
      setDeploymentLifecycle(deployment.namespace, deployment.name, action),
    onSuccess: (_data, variables) => {
      invalidateDashboard();
      showToast(
        variables.action === "pause" ? "Lab mis en pause" : "Lab repris",
        "success",
      );
    },
  });

  const deletePvcMutation = useMutation({
    mutationFn: (pvc: PvcInfo) => deletePvc(pvc.name, Boolean(pvc.bound)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pvcs"] });
      showToast("Volume supprime", "success");
    },
  });

  const activeLabs = deployments.data || [];
  const readyLabs = activeLabs.filter((lab) => (lab.ready_replicas || 0) > 0).length;
  const pvcItems = pvcs.data || [];
  const isAdmin = user.role === "admin";

  const filteredTemplates = useMemo(() => {
    const text = templateQuery.trim().toLowerCase();
    return (templates.data || []).filter((item) => {
      if (!text) return true;
      return `${item.name} ${item.description || ""} ${(item.tags || []).join(" ")}`.toLowerCase().includes(text);
    });
  }, [templateQuery, templates.data]);

  return (
    <>
      <ToastContainer />
      <PageHeader
        title="Mes environnements de TP"
        subtitle="Lancez vos labs, retrouvez vos fichiers persistants et surveillez les quotas disponibles."
        actions={
          <>
            <Button
              variant="primary"
              onClick={() => {
                document.getElementById("lab-catalog")?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              <Plus size={16} />
              Lancer un lab
            </Button>
            <Button onClick={() => void invalidateDashboard()}>
              <RefreshCw size={16} />
              Actualiser
            </Button>
          </>
        }
      />

      <section className="metric-grid">
        <MetricCard label="Labs actifs" value={activeLabs.length} icon={<Boxes size={18} />} />
        <MetricCard label="Labs prets" value={readyLabs} icon={<Gauge size={18} />} />
        <MetricCard label="Volumes" value={pvcItems.length} icon={<Database size={18} />} />
        <MetricCard label="Labs restants" value={quotas.data?.remaining?.apps ?? "-"} icon={<Cpu size={18} />} />
      </section>

      <section className="grid-2">
        <div className="panel">
          <div className="section-head">
            <h2>Labs actifs</h2>
            <StatusBadge state={deployments.isFetching ? "starting" : "running"} />
          </div>
          {deployments.isLoading ? <LoadingState /> : null}
          {deployments.error ? <ErrorState>Impossible de charger les labs.</ErrorState> : null}
          {!deployments.isLoading && !deployments.error && activeLabs.length === 0 ? (
            <EmptyState title="Aucun lab actif">
              Choisissez un template dans le catalogue pour demarrer votre premier environnement.
            </EmptyState>
          ) : null}
          <div className="lab-list">
            {activeLabs.map((deployment) => (
              <LabCard
                key={`${deployment.namespace}-${deployment.name}`}
                deployment={deployment}
                onOpen={async (item) => {
                  try {
                    const details = await getDeploymentDetails(item.namespace, item.name);
                    const firstUrl = details.access_urls?.find((access) => access.url)?.url;
                    if (firstUrl) {
                      window.open(firstUrl, "_blank", "noopener,noreferrer");
                      return;
                    }
                    showToast("Aucune URL disponible pour ce lab pour le moment.", "error");
                  } catch {
                    showToast("Impossible de recuperer l'URL du lab.", "error");
                  }
                }}
                onDetails={setDetailsTarget}
                onDelete={(item) => deleteMutation.mutate(item)}
                onLifecycle={(item, action) => lifecycleMutation.mutate({ deployment: item, action })}
              />
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="section-head">
            <h2>Ressources</h2>
            <Button onClick={() => void queryClient.invalidateQueries({ queryKey: ["quotas"] })}>
              <RefreshCw size={16} /> Refresh
            </Button>
          </div>
          {quotas.isLoading ? <LoadingState /> : null}
          {quotas.error ? <ErrorState>Quotas indisponibles.</ErrorState> : null}
          {quotas.data ? (
            <div className="grid gap-3.5">
              <ResourceMeter label="Applications" used={quotas.data.usage.apps_used} max={quotas.data.limits.max_apps} />
              <ResourceMeter label="CPU" used={quotas.data.usage.cpu_m_used} max={quotas.data.limits.max_requests_cpu_m} unit="m" />
              <ResourceMeter label="Memoire" used={quotas.data.usage.mem_mi_used} max={quotas.data.limits.max_requests_mem_mi} unit="Mi" />
              {quotas.data.limits.max_storage_gi != null ? (
                <ResourceMeter
                  label="Stockage"
                  used={quotas.data.usage.storage_gi_used || 0}
                  max={quotas.data.limits.max_storage_gi}
                  unit="Gi"
                />
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      <K8sAdminPanel admin={isAdmin} />

      <section className="panel" id="lab-catalog">
        <div className="section-head">
          <div>
            <h2>Catalogue</h2>
            <p className="muted">Templates autorises pour votre role {user.role}.</p>
          </div>
          <SearchBox
            placeholder="Rechercher un template"
            value={templateQuery}
            onChange={(e) => setTemplateQuery(e.target.value)}
          />
        </div>
        {templates.isLoading ? <LoadingState /> : null}
        {templates.error ? <ErrorState>Impossible de charger le catalogue.</ErrorState> : null}
        <div className="grid-3">
          {filteredTemplates.map((template) => (
            <TemplateCard
              key={String(template.key || template.id || template.name)}
              template={template}
              onSelect={setSelectedTemplate}
            />
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <h2>Volumes persistants</h2>
          <Button onClick={() => void queryClient.invalidateQueries({ queryKey: ["pvcs"] })}>
            <RefreshCw size={16} /> Actualiser
          </Button>
        </div>
        {pvcs.isLoading ? <LoadingState /> : null}
        {pvcs.error ? <ErrorState>Impossible de charger les volumes.</ErrorState> : null}
        {!pvcs.isLoading && !pvcs.error && pvcItems.length === 0 ? (
          <EmptyState title="Aucun volume">Les volumes VS Code et Jupyter apparaitront ici apres creation.</EmptyState>
        ) : null}
        {pvcItems.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Volume</th>
                  <th>Etat</th>
                  <th>Capacite</th>
                  <th>StorageClass</th>
                  {isAdmin ? <th>Namespace</th> : null}
                  <th>Acces</th>
                  <th>Dernier lab</th>
                  <th>Cree le</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pvcItems.map((pvc) => (
                  <tr key={pvc.name}>
                    <td>{pvc.name}</td>
                    <td>
                      <span className={pvc.bound ? "badge amber" : "badge green"}>
                        {pvc.bound ? `${pvc.phase || "Bound"} - attache` : `${pvc.phase || "Libre"} - disponible`}
                      </span>
                    </td>
                    <td>{pvc.storage || "N/A"}</td>
                    <td>{pvc.storage_class || "N/A"}</td>
                    {isAdmin ? <td>{pvc.namespace || "N/A"}</td> : null}
                    <td>{pvc.access_modes?.length ? pvc.access_modes.join(", ") : "N/A"}</td>
                    <td>{pvc.last_bound_app || pvc.app_type || "N/A"}</td>
                    <td>{shortDate(pvc.created_at)}</td>
                    <td>
                      <ConfirmDialog
                        destructive
                        title="Supprimer le volume"
                        description={`Supprimer ${pvc.name} ? Les donnees stockees dans ce volume seront perdues.`}
                        confirmLabel="Supprimer"
                        trigger={<Button variant="danger">Supprimer</Button>}
                        onConfirm={() => deletePvcMutation.mutate(pvc)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {selectedTemplate ? (
        <LaunchDialog
          template={selectedTemplate}
          pvcs={pvcItems}
          student={user.role === "student"}
          onOpenChange={(open) => !open && setSelectedTemplate(null)}
          onCreated={async (created, name) => {
            setSelectedTemplate(null);
            await invalidateDashboard();
            showToast(`Deploiement de ${name} en cours. Le lab apparaitra pret des que Kubernetes aura termine.`, "info");
          }}
        />
      ) : null}

      {detailsTarget ? (
        <DeploymentDetailsDialog
          deployment={detailsTarget}
          onClose={() => setDetailsTarget(null)}
          onNovnc={setNovncTarget}
        />
      ) : null}

      {novncTarget ? (
        <NovncDialog deployment={novncTarget} onClose={() => setNovncTarget(null)} />
      ) : null}
    </>
  );
}

function NovncDialog({ deployment, onClose }: { deployment: Deployment; onClose: () => void }) {
  const details = useQuery({
    queryKey: ["deployment-details", deployment.namespace, deployment.name],
    queryFn: () => getDeploymentDetails(deployment.namespace, deployment.name),
    staleTime: 30_000,
  });

  const novncUrl = details.data?.novnc_endpoint;

  return (
    <div className="dialog-overlay z-[60]" onClick={onClose}>
      <div
        className="dialog-content panel flex h-[min(768px,calc(100vh-32px))] w-[min(1024px,calc(100vw-32px))] flex-col p-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="section-head border-b border-[var(--border)] px-4 py-3">
          <h2>{deployment.name} — Bureau NoVNC</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Fermer">
            <Monitor size={17} />
          </button>
        </div>
        {details.isLoading ? (
          <div className="grid flex-1 place-items-center">
            <span className="muted">Chargement...</span>
          </div>
        ) : novncUrl ? (
          <iframe className="w-full flex-1 border-0" src={novncUrl} title="NoVNC" />
        ) : (
          <div className="grid flex-1 place-items-center">
            <span className="muted">NoVNC non disponible pour ce lab.</span>
          </div>
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <AppShell page="dashboard">{(user) => <Dashboard user={user} />}</AppShell>
  </QueryProvider>,
);
