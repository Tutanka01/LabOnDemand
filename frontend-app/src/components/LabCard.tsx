import { ExternalLink, Info, PauseCircle, PlayCircle, Trash2 } from "lucide-react";
import { motion } from "motion/react";
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
    <motion.article className="card lab-card" layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <div className="lab-card-head">
        <div className="lab-title">
          <span className="runtime-mark">
            <RuntimeIcon type={deployment.type || deployment.deployment_type} />
          </span>
          <div>
            <strong>{deployment.name}</strong>
            <div className="muted">{deployment.namespace}</div>
          </div>
        </div>
        <StatusBadge state={state} />
      </div>

      <div className="lab-meta">
        <span className="badge">{deployment.type || deployment.deployment_type || "custom"}</span>
        <span className="badge">
          {deployment.ready_replicas || 0}/{deployment.replicas || 1} replicas
        </span>
        <span className="badge">TTL {ttl(deployment.expires_at)}</span>
      </div>

      <div className="actions-row">
        <Button variant="primary" disabled={!ready} onClick={() => onOpen(deployment)}>
          <ExternalLink size={16} />
          {ready ? (locale === "fr" ? "Ouvrir" : "Open") : (locale === "fr" ? "En préparation" : "Preparing")}
        </Button>
        <Button onClick={() => onDetails(deployment)}>
          <Info size={16} />
          {locale === "fr" ? "Infos" : "Info"}
        </Button>
        <Button onClick={() => onLifecycle(deployment, paused ? "resume" : "pause")}>
          {paused ? <PlayCircle size={16} /> : <PauseCircle size={16} />}
          {paused ? (locale === "fr" ? "Reprendre" : "Resume") : (locale === "fr" ? "Pause" : "Pause")}
        </Button>
        <ConfirmDialog
          destructive
          title={locale === "fr" ? "Supprimer le lab" : "Delete lab"}
          description={locale === "fr" ? `Supprimer ${deployment.name} et son service Kubernetes ? Les volumes persistants ne sont pas supprimés automatiquement.` : `Delete ${deployment.name} and its Kubernetes service? Persistent volumes are not deleted automatically.`}
          confirmLabel={locale === "fr" ? "Supprimer" : "Delete"}
          trigger={
            <Button variant="danger">
              <Trash2 size={16} />
              {locale === "fr" ? "Supprimer" : "Delete"}
            </Button>
          }
          onConfirm={() => onDelete(deployment)}
        />
      </div>
    </motion.article>
  );
}
