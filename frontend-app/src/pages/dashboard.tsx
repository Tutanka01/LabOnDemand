import "../styles/main.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Cpu, Database, Gauge, Plus, RefreshCw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { PageHeader } from "../components/AppShell";
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
import { LaunchDialog } from "../components/dashboard/LaunchDialog";
import { DeploymentDetailsDialog } from "../components/dashboard/DeploymentDetailsDialog";
import { K8sAdminPanel } from "../components/dashboard/K8sAdminPanel";
import { useI18n } from "../lib/i18n";

export default function DashboardPage() {
  const user = useOutletContext<User>();
  const queryClient = useQueryClient();
  const { locale, t } = useI18n();

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
      showToast(locale === "fr" ? "Lab supprimé" : "Lab deleted", "success");
    },
  });

  const lifecycleMutation = useMutation({
    mutationFn: ({ deployment, action }: { deployment: Deployment; action: "pause" | "resume" }) =>
      setDeploymentLifecycle(deployment.namespace, deployment.name, action),
    onSuccess: (_data, variables) => {
      invalidateDashboard();
      showToast(
        variables.action === "pause" 
          ? (locale === "fr" ? "Lab mis en pause" : "Lab paused") 
          : (locale === "fr" ? "Lab repris" : "Lab resumed"),
        "success",
      );
    },
  });

  const deletePvcMutation = useMutation({
    mutationFn: (pvc: PvcInfo) => deletePvc(pvc.name, Boolean(pvc.bound)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pvcs"] });
      showToast(locale === "fr" ? "Volume supprimé" : "Volume deleted", "success");
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
      <PageHeader
        title={t("dashboard.title")}
        subtitle={locale === "fr" ? "Lancez vos labs, retrouvez vos fichiers persistants et surveillez les quotas disponibles." : "Launch your labs, restore your persistent files, and monitor available resource quotas."}
        actions={
          <>
            <Button
              variant="primary"
              onClick={() => {
                document.getElementById("lab-catalog")?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              <Plus size={16} />
              {t("dashboard.create_lab")}
            </Button>
            <Button onClick={() => void invalidateDashboard()}>
              <RefreshCw size={16} />
              {t("overview.refresh")}
            </Button>
          </>
        }
      />

      <section className="metric-grid">
        <MetricCard label={locale === "fr" ? "Labs actifs" : "Active labs"} value={activeLabs.length} icon={<Boxes size={18} />} />
        <MetricCard label={locale === "fr" ? "Labs prêts" : "Ready labs"} value={readyLabs} icon={<Gauge size={18} />} />
        <MetricCard label={locale === "fr" ? "Volumes" : "Volumes"} value={pvcItems.length} icon={<Database size={18} />} />
        <MetricCard label={locale === "fr" ? "Labs restants" : "Remaining labs"} value={quotas.data?.remaining?.apps ?? "-"} icon={<Cpu size={18} />} />
      </section>

      <section className="grid-2">
        <div className="panel">
          <div className="section-head">
            <h2>{locale === "fr" ? "Labs actifs" : "Active labs"}</h2>
            <StatusBadge state={deployments.isFetching ? "starting" : "running"} />
          </div>
          {deployments.isLoading ? <LoadingState /> : null}
          {deployments.error ? <ErrorState>{locale === "fr" ? "Impossible de charger les labs." : "Unable to load labs."}</ErrorState> : null}
          {!deployments.isLoading && !deployments.error && activeLabs.length === 0 ? (
            <EmptyState title={t("dashboard.no_labs")}>
              {locale === "fr" ? "Choisissez un template dans le catalogue pour démarrer votre premier environnement." : "Choose a template from the catalog to start your first environment."}
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
                    showToast(locale === "fr" ? "Aucune URL disponible pour ce lab pour le moment." : "No URL available for this lab at the moment.", "error");
                  } catch {
                    showToast(locale === "fr" ? "Impossible de récupérer l'URL du lab." : "Failed to retrieve lab URL.", "error");
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
            <h2>{locale === "fr" ? "Vos ressources" : "Your resources"}</h2>
            <Button onClick={() => void queryClient.invalidateQueries({ queryKey: ["quotas"] })}>
              <RefreshCw size={16} /> {t("overview.refresh")}
            </Button>
          </div>
          {quotas.isLoading ? <LoadingState /> : null}
          {quotas.error ? <ErrorState>{locale === "fr" ? "Quotas indisponibles." : "Quotas unavailable."}</ErrorState> : null}
          {quotas.data ? (
            <div className="grid gap-3.5">
              <ResourceMeter label={locale === "fr" ? "Applications" : "Applications"} used={quotas.data.usage.apps_used} max={quotas.data.limits.max_apps} />
              <ResourceMeter label="CPU" used={quotas.data.usage.cpu_m_used} max={quotas.data.limits.max_requests_cpu_m} unit="m" />
              <ResourceMeter label={locale === "fr" ? "Mémoire" : "Memory"} used={quotas.data.usage.mem_mi_used} max={quotas.data.limits.max_requests_mem_mi} unit="Mi" />
              {quotas.data.limits.max_storage_gi != null ? (
                <ResourceMeter
                  label={locale === "fr" ? "Stockage" : "Storage"}
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
            <h2>{locale === "fr" ? "Catalogue" : "Catalog"}</h2>
            <p className="muted">
              {locale === "fr" ? `Templates autorisés pour votre rôle ${user.role}.` : `Templates authorized for your role ${user.role}.`}
            </p>
          </div>
          <SearchBox
            placeholder={locale === "fr" ? "Rechercher un template..." : "Search template..."}
            value={templateQuery}
            onChange={(e) => setTemplateQuery(e.target.value)}
          />
        </div>
        {templates.isLoading ? <LoadingState /> : null}
        {templates.error ? <ErrorState>{locale === "fr" ? "Impossible de charger le catalogue." : "Unable to load catalog."}</ErrorState> : null}
        {!templates.isLoading && !templates.error && filteredTemplates.length === 0 ? (
          <EmptyState title={locale === "fr" ? "Aucun template" : "No templates"}>
            {templateQuery
              ? (locale === "fr" ? "Aucun template ne correspond à la recherche." : "No template matches the search.")
              : (locale === "fr" ? "Aucun template actif n'est disponible pour votre rôle." : "No active template is available for your role.")}
          </EmptyState>
        ) : null}
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
          <h2>{locale === "fr" ? "Mes volumes persistants" : "My persistent volumes"}</h2>
          <Button onClick={() => void queryClient.invalidateQueries({ queryKey: ["pvcs"] })}>
            <RefreshCw size={16} /> {t("overview.refresh")}
          </Button>
        </div>
        {pvcs.isLoading ? <LoadingState /> : null}
        {pvcs.error ? <ErrorState>{locale === "fr" ? "Impossible de charger les volumes." : "Unable to load volumes."}</ErrorState> : null}
        {!pvcs.isLoading && !pvcs.error && pvcItems.length === 0 ? (
          <EmptyState title={locale === "fr" ? "Aucun volume" : "No volumes"}>
            {locale === "fr" ? "Les volumes VS Code et Jupyter apparaîtront ici après création." : "VS Code and Jupyter volumes will appear here after creation."}
          </EmptyState>
        ) : null}
        {pvcItems.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Volume</th>
                  <th>{locale === "fr" ? "État" : "State"}</th>
                  <th>{locale === "fr" ? "Capacité" : "Capacity"}</th>
                  <th>StorageClass</th>
                  {isAdmin ? <th>Namespace</th> : null}
                  <th>{locale === "fr" ? "Accès" : "Access"}</th>
                  <th>{locale === "fr" ? "Dernier lab" : "Last lab"}</th>
                  <th>{locale === "fr" ? "Créé le" : "Created at"}</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pvcItems.map((pvc) => (
                  <tr key={pvc.name}>
                    <td>{pvc.name}</td>
                    <td>
                      <span className={pvc.bound ? "badge amber" : "badge green"}>
                        {pvc.bound 
                          ? (locale === "fr" ? `${pvc.phase || "Bound"} - attaché` : `${pvc.phase || "Bound"} - bound`) 
                          : (locale === "fr" ? `${pvc.phase || "Libre"} - disponible` : `${pvc.phase || "Available"} - free`)}
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
                        title={locale === "fr" ? "Supprimer le volume" : "Delete volume"}
                        description={locale === "fr" ? `Supprimer ${pvc.name} ? Les données stockées dans ce volume seront perdues.` : `Delete ${pvc.name}? Data stored in this volume will be permanently lost.`}
                        confirmLabel={t("common.delete")}
                        trigger={<Button variant="danger">{t("common.delete")}</Button>}
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
            showToast(
              locale === "fr"
                ? `Déploiement de ${name} en cours. Le lab apparaîtra prêt dès que Kubernetes aura terminé.`
                : `Deployment of ${name} in progress. The lab will appear ready as soon as Kubernetes finishes.`,
              "info"
            );
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
  const { locale } = useI18n();
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
          <h2>{deployment.name} — {locale === "fr" ? "Bureau NoVNC" : "NoVNC Desktop"}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Fermer">
            <X size={17} />
          </button>
        </div>
        {details.isLoading ? (
          <div className="grid flex-1 place-items-center">
            <span className="muted">{locale === "fr" ? "Chargement..." : "Loading..."}</span>
          </div>
        ) : novncUrl ? (
          <iframe className="w-full flex-1 border-0" src={novncUrl} title="NoVNC" />
        ) : (
          <div className="grid flex-1 place-items-center">
            <span className="muted">{locale === "fr" ? "NoVNC non disponible pour ce lab." : "NoVNC not available for this lab."}</span>
          </div>
        )}
      </div>
    </div>
  );
}
