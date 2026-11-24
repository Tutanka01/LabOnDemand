import { Loader2 } from "lucide-react";
import type { LabPhase } from "../../hooks/useDeployments";
import { isTransitional } from "../../hooks/useDeployments";
import { useI18n } from "../../lib/i18n";
import { Badge } from "../ui";

const TONES: Record<LabPhase, "green" | "amber" | "blue" | "red"> = {
  ready: "green",
  starting: "blue",
  creating: "blue",
  resuming: "blue",
  paused: "amber",
  pausing: "amber",
  deleting: "red",
};

/** Lab state badge shared by the dashboard cards and the student assignment pages. */
export function LabStatusBadge({ phase }: { phase: LabPhase }) {
  const { t } = useI18n();
  const busy = isTransitional(phase);
  return (
    <Badge tone={TONES[phase]} aria-live="polite">
      {busy ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : null}
      {t(`labs.phase_${phase}`)}
    </Badge>
  );
}
