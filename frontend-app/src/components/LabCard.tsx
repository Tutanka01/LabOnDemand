import { ExternalLink, Info, PauseCircle, PlayCircle, Trash2 } from "lucide-react";
import type { Deployment } from "../types/api";
import { ttl } from "../lib/format";
import { RuntimeIcon } from "../lib/icons";
import { useI18n } from "../lib/i18n";
import { Button, ConfirmDialog, StatusBadge } from "./ui";

export function LabCard({
  deployment,
  onOpen,
  onDetails,
  onDelete,
  onLifecycle
}: {
  deployment: Deployment;
  index?: number;
  onOpen: (deployment: Deployment) => void;
  onDetails: (deployment: Deployment) => void;
  onDelete: (deployment: Deployment) => void;
  onLifecycle: (deployment: Deployment, action: "pause" | "resume") => void;
}) {
  const { locale } = useI18n();
  const lifecycle = deployment.lifecycle || deployment.lifecycle_summary;
  const state = lifecycle?.state || (deployment.is_paused ? "paused" : deployment.ready_replicas ? "running" : "starting");
  const paused = state === "paused" || lifecycle?.paused;
  const ready = !paused && Boolean(deployment.ready_replicas && deployment.ready_replicas > 0);

  return (
    <article className="card lab-card">
      <div className="lab-card-head">
        <div className="lab-title">
          <span className="runtime-mark">
            <RuntimeIcon type={deployment.type || deployment.deployment_type} />
          </span>
          <div className="min-w-0">
            <strong>{deployment.name}</strong>
            <div className="muted code-text">{deployment.namespace}</div>
          </div>
        </div>
        <StatusBadge state={state} />
      </div>

      <div className="lab-meta">
        <span className="badge">{deployment.type || deployment.deployment_type || "custom"}</span>
        <span className={`badge ${ready ? "green" : ""}`}>
          {deployment.ready_replicas || 0}/{deployment.replicas || 1} {locale === "fr" ? "réplicas" : "replicas"}
        </span>
        <span className="badge">TTL {ttl(deployment.expires_at)}</span>
      </div>

      <div className="hairline" />

      <div className="actions-row">
        <Button disabled={!ready} onClick={() => onOpen(deployment)}>
          <ExternalLink size={15} />
          {ready ? (locale === "fr" ? "Ouvrir" : "Open") : (locale === "fr" ? "En préparation" : "Preparing")}
        </Button>
        <Button onClick={() => onDetails(deployment)}>
          <Info size={15} />
          {locale === "fr" ? "Infos" : "Info"}
        </Button>
        <Button onClick={() => onLifecycle(deployment, paused ? "resume" : "pause")}>
          {paused ? <PlayCircle size={15} /> : <PauseCircle size={15} />}
          {paused ? (locale === "fr" ? "Reprendre" : "Resume") : (locale === "fr" ? "Pause" : "Pause")}
        </Button>
        <ConfirmDialog
          destructive
          title={locale === "fr" ? "Supprimer le lab" : "Delete lab"}
          description={locale === "fr" ? `Supprimer ${deployment.name} et son service Kubernetes ? Les volumes persistants ne sont pas supprimés automatiquement.` : `Delete ${deployment.name} and its Kubernetes service? Persistent volumes are not deleted automatically.`}
          confirmLabel={locale === "fr" ? "Supprimer" : "Delete"}
          trigger={
            <Button variant="danger">
              <Trash2 size={15} />
              {locale === "fr" ? "Supprimer" : "Delete"}
            </Button>
          }
          onConfirm={() => onDelete(deployment)}
        />
      </div>
    </article>
  );
}
