import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import { Boxes, Cpu, Database, Gauge, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { PageHeader } from "../components/AppShell";
import { Button, MetricCard, showToast } from "../components/ui";
import { CATALOG_ID, CATALOG_SEARCH_ID, CatalogPanel } from "../components/dashboard/CatalogPanel";
import { DeploymentDetailsDialog } from "../components/dashboard/DeploymentDetailsDialog";
import { K8sAdminPanel } from "../components/dashboard/K8sAdminPanel";
import { LabsPanel } from "../components/dashboard/LabsPanel";
import { LaunchDialog } from "../components/dashboard/LaunchDialog";
import { NovncDialog } from "../components/dashboard/NovncDialog";
import { QuotaPanel } from "../components/dashboard/QuotaPanel";
import { VolumesPanel } from "../components/dashboard/VolumesPanel";
import { VolumeBrowserDialog } from "../components/files/VolumeBrowserDialog";
import { useDeployments } from "../hooks/useDeployments";
import { getPvcs, getQuotas } from "../lib/api";
import { useI18n } from "../lib/i18n";
import type { Deployment, Template, User, VolumeTarget } from "../types/api";

function scrollToCatalog() {
  document.getElementById(CATALOG_ID)?.scrollIntoView({ behavior: "smooth", block: "start" });
  document.getElementById(CATALOG_SEARCH_ID)?.focus({ preventScroll: true });
}

export default function DashboardPage() {
  const user = useOutletContext<User>();
  const { t } = useI18n();
  const labsState = useDeployments();
  // Shared with the panels through the query cache (no extra requests).
  const quotas = useQuery({ queryKey: ["quotas"], queryFn: getQuotas });
  const pvcs = useQuery({ queryKey: ["pvcs"], queryFn: getPvcs });

  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [detailsTarget, setDetailsTarget] = useState<Deployment | null>(null);
  const [novncTarget, setNovncTarget] = useState<Deployment | null>(null);
  const [browseTarget, setBrowseTarget] = useState<{ target: VolumeTarget; title: string } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const isAdmin = user.role === "admin";
  const student = user.role === "student";
  const labs = labsState.labs;
  const readyLabs = labs.filter((lab) => lab.phase === "ready").length;
  const labsKnown = labsState.query.data !== undefined;

  const refreshAll = async () => {
    setRefreshing(true);
    try {
      await labsState.refresh();
    } finally {
      setRefreshing(false);
    }
  };

  const metrics = [
    { key: "active", label: t("labs.metric_active"), value: labsKnown ? labs.length : "–", icon: <Boxes size={18} aria-hidden="true" /> },
    { key: "ready", label: t("labs.metric_ready"), value: labsKnown ? readyLabs : "–", icon: <Gauge size={18} aria-hidden="true" /> },
    { key: "volumes", label: t("labs.metric_volumes"), value: pvcs.data ? pvcs.data.length : "–", icon: <Database size={18} aria-hidden="true" /> },
    {
      key: "remaining",
      label: t("labs.metric_remaining"),
      value: quotas.data?.remaining?.apps ?? "–",
      icon: <Cpu size={18} aria-hidden="true" />,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("dashboard.title")}
        subtitle={t("labs.page_subtitle")}
        actions={
          <>
            <Button variant="primary" onClick={scrollToCatalog}>
              <Plus size={16} aria-hidden="true" />
              {t("dashboard.create_lab")}
            </Button>
            <Button onClick={() => void refreshAll()} disabled={refreshing}>
              <RefreshCw size={16} className={refreshing ? "animate-spin" : undefined} aria-hidden="true" />
              {t("common.refresh")}
            </Button>
          </>
        }
      />

      <section className="metric-grid" aria-label={t("labs.metrics_label")}>
        {metrics.map((metric) => (
          <MetricCard key={metric.key} label={metric.label} value={metric.value} icon={metric.icon} />
        ))}
      </section>

      <div className="grid-2">
        <LabsPanel labsState={labsState} onDetails={setDetailsTarget} onBrowseCatalog={scrollToCatalog} />
        <QuotaPanel />
      </div>

      <K8sAdminPanel admin={isAdmin} />

      <CatalogPanel technical={!student} onSelect={setSelectedTemplate} />

      <VolumesPanel showNamespace={isAdmin} onBrowse={(target, title) => setBrowseTarget({ target, title })} />

      {selectedTemplate ? (
        <LaunchDialog
          template={selectedTemplate}
          pvcs={pvcs.data || []}
          student={student}
          existingNames={labs.map((lab) => lab.deployment.name)}
          onOpenChange={(open) => !open && setSelectedTemplate(null)}
          onCreated={(created, name) => {
            const type =
              created.deployment_type ||
              selectedTemplate.deployment_type ||
              selectedTemplate.key ||
              String(selectedTemplate.id || "custom");
            setSelectedTemplate(null);
            labsState.registerCreated({ name, namespace: created.namespace, type });
            showToast(t("labs.created_toast", { name }), "info");
          }}
        />
      ) : null}

      {detailsTarget ? (
        <DeploymentDetailsDialog deployment={detailsTarget} onClose={() => setDetailsTarget(null)} onNovnc={setNovncTarget} />
      ) : null}

      {novncTarget ? <NovncDialog deployment={novncTarget} onClose={() => setNovncTarget(null)} /> : null}

      {browseTarget ? (
        <VolumeBrowserDialog
          target={browseTarget.target}
          title={`${browseTarget.title} — ${t("files.title")}`}
          onClose={() => setBrowseTarget(null)}
        />
      ) : null}
    </>
  );
}
