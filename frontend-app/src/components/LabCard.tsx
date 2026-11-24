import { ExternalLink, Info, Loader2, PauseCircle, PlayCircle, Trash2 } from "lucide-react";
import { canOpen, type LabAction, type LabView } from "../hooks/useDeployments";
import { remainingTime } from "../lib/format";
import { RuntimeIcon } from "../lib/icons";
import { useI18n } from "../lib/i18n";
import type { Deployment } from "../types/api";
import { LabStatusBadge } from "./dashboard/LabStatusBadge";
import { Badge, Button, ConfirmDialog, cn } from "./ui";

export function LabCard({
  lab,
  highlight = false,
  onOpenFallback,
  onDetails,
  onAction,
}: {
  lab: LabView;
  /** Briefly emphasise a lab that just became ready. */
  highlight?: boolean;
  /** Called when the lab is ready but the list has no URL for it yet. */
  onOpenFallback: (deployment: Deployment) => void;
  onDetails: (deployment: Deployment) => void;
  onAction: (deployment: Deployment, action: LabAction) => void;
}) {
  const { t, locale } = useI18n();
  const { deployment, phase, busy } = lab;
  const type = deployment.type || deployment.deployment_type || "custom";
  const placeholder = phase === "creating";
  const paused = phase === "paused" || phase === "pausing";
  const openable = canOpen(lab) && !busy;
  const accessUrl = deployment.access_url || null;
  const remaining = remainingTime(deployment.expires_at, locale);
  const ready = deployment.ready_replicas ?? 0;
  const total = Math.max(deployment.replicas ?? 1, 1);

  const hint =
    phase === "starting" || phase === "creating" || phase === "resuming"
      ? t("labs.hint_starting")
      : phase === "paused"
        ? t("labs.hint_paused")
        : null;

  const openLabel = t("labs.open_named", { name: deployment.name });

  return (
    <article
      className={cn(
        "card lab-card",
        busy && "opacity-80",
        highlight && "border-[var(--success)] shadow-[var(--shadow)]",
      )}
      aria-busy={busy}
      aria-label={deployment.name}
    >
      <div className="lab-card-head">
        <div className="lab-title">
          <span className="runtime-mark">
            <RuntimeIcon type={type} />
          </span>
          <div className="min-w-0">
            <strong className="block truncate">{deployment.name}</strong>
            <div className="muted text-[var(--text-xs)]">{type}</div>
          </div>
        </div>
        <LabStatusBadge phase={phase} />
      </div>

      <div className="lab-meta">
        {phase === "starting" && total > 1 ? (
          <Badge tone="blue">{t("labs.replicas_ready", { ready, total })}</Badge>
        ) : null}
        <Badge tone={deployment.expires_at && !remaining ? "red" : "default"}>
          {!deployment.expires_at
            ? t("labs.no_expiry")
            : remaining
              ? t("labs.expires_in", { time: remaining })
              : t("labs.expired")}
        </Badge>
      </div>

      {hint ? <p className="muted m-0 text-[var(--text-xs)]">{hint}</p> : null}

      <div className="hairline" />

      <div className="actions-row">
        {openable && accessUrl ? (
          <a className="btn primary" href={accessUrl} target="_blank" rel="noopener noreferrer" aria-label={openLabel}>
            <ExternalLink size={15} aria-hidden="true" />
            {t("dashboard.open")}
          </a>
        ) : openable ? (
          <Button variant="primary" onClick={() => onOpenFallback(deployment)} aria-label={openLabel}>
            <ExternalLink size={15} aria-hidden="true" />
            {t("dashboard.open")}
          </Button>
        ) : (
          <Button variant="primary" disabled>
            {phase === "starting" || phase === "creating" || phase === "resuming" ? (
              <Loader2 size={15} className="animate-spin" aria-hidden="true" />
            ) : (
              <ExternalLink size={15} aria-hidden="true" />
            )}
            {phase === "starting" || phase === "creating" || phase === "resuming" ? t("labs.preparing") : t("dashboard.open")}
          </Button>
        )}
        <Button onClick={() => onDetails(deployment)} disabled={placeholder}>
          <Info size={15} aria-hidden="true" />
          {t("common.details")}
        </Button>
        <Button onClick={() => onAction(deployment, paused ? "resume" : "pause")} disabled={busy || placeholder}>
          {phase === "pausing" || phase === "resuming" ? (
            <Loader2 size={15} className="animate-spin" aria-hidden="true" />
          ) : paused ? (
            <PlayCircle size={15} aria-hidden="true" />
          ) : (
            <PauseCircle size={15} aria-hidden="true" />
          )}
          {phase === "pausing" || phase === "resuming"
            ? t(`labs.phase_${phase}`)
            : paused
              ? t("dashboard.resume")
              : t("dashboard.pause")}
        </Button>
        <ConfirmDialog
          destructive
          title={t("labs.delete_title")}
          description={t("labs.delete_description", { name: deployment.name })}
          confirmLabel={t("common.delete")}
          trigger={
            <Button variant="danger" disabled={busy || placeholder}>
              {phase === "deleting" ? (
                <Loader2 size={15} className="animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 size={15} aria-hidden="true" />
              )}
              {t("common.delete")}
            </Button>
          }
          onConfirm={() => onAction(deployment, "delete")}
        />
      </div>
    </article>
  );
}
