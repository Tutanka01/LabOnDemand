import { ExternalLink, PauseCircle, PlayCircle, Trash2 } from "lucide-react";
import { motion } from "motion/react";
import type { Deployment } from "../types/api";
import { ttl } from "../lib/format";
import { RuntimeIcon } from "../lib/icons";
import { Button, ConfirmDialog, StatusBadge } from "./ui";

export function LabCard({
  deployment,
  onDetails,
  onDelete,
  onLifecycle
}: {
  deployment: Deployment;
  onDetails: (deployment: Deployment) => void;
  onDelete: (deployment: Deployment) => void;
  onLifecycle: (deployment: Deployment, action: "pause" | "resume") => void;
}) {
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
        <span className={ready ? "badge green" : paused ? "badge amber" : "badge blue"}>
          {deployment.ready_replicas || 0}/{deployment.replicas || 1} replicas
        </span>
        <span className="badge">TTL {ttl(deployment.expires_at)}</span>
      </div>

      <div className="actions-row">
        <Button variant="primary" onClick={() => onDetails(deployment)}>
          <ExternalLink size={16} />
          Ouvrir
        </Button>
        <Button onClick={() => onLifecycle(deployment, paused ? "resume" : "pause")}>
          {paused ? <PlayCircle size={16} /> : <PauseCircle size={16} />}
          {paused ? "Reprendre" : "Pause"}
        </Button>
        <ConfirmDialog
          destructive
          title="Supprimer le lab"
          description={`Supprimer ${deployment.name} et son service Kubernetes ? Les volumes persistants ne sont pas supprimes automatiquement.`}
          confirmLabel="Supprimer"
          trigger={
            <Button variant="danger">
              <Trash2 size={16} />
              Supprimer
            </Button>
          }
          onConfirm={() => onDelete(deployment)}
        />
      </div>
    </motion.article>
  );
}
