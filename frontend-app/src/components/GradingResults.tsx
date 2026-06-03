import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  MinusCircle,
  XCircle,
} from "lucide-react";
import { Badge } from "./ui";
import { useI18n } from "../lib/i18n";
import type { GradingRun, ProbeResult, StudentProbe } from "../types/api";

/**
 * Affichage du triage des tests boîte noire, partagé entre la vue étudiant
 * (poste de travail) et la vue prof (correction). Rendu check par check, avec
 * un état de progression vivant (en attente → en cours → vert / rouge).
 */

const STATUS_COLOR: Record<string, string> = {
  pass: "#16a34a",
  fail: "#dc2626",
  error: "#dc2626",
  skip: "#d97706",
  running: "#2563eb",
  queued: "#2563eb",
  pending: "#94a3b8",
};

type Tone = "green" | "red" | "amber" | "blue" | "default";

function statusTone(status: string): Tone {
  switch (status) {
    case "pass":
      return "green";
    case "fail":
    case "error":
      return "red";
    case "skip":
      return "amber";
    case "running":
    case "queued":
      return "blue";
    default:
      return "default";
  }
}

function StatusIcon({ status }: { status: string }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.pending;
  const common = { size: 17, style: { color, flexShrink: 0 } } as const;
  switch (status) {
    case "pass":
      return <CheckCircle2 {...common} />;
    case "fail":
      return <XCircle {...common} />;
    case "error":
      return <AlertTriangle {...common} />;
    case "skip":
      return <MinusCircle {...common} />;
    case "running":
    case "queued":
      return <Loader2 {...common} className="animate-spin" />;
    default:
      return <Clock {...common} />;
  }
}

function useStatusLabel() {
  const { t } = useI18n();
  return (status: string): string => {
    switch (status) {
      case "pass":
        return t("probe.result_pass");
      case "fail":
        return t("probe.result_fail");
      case "error":
        return t("probe.result_error");
      case "skip":
        return t("probe.result_skip");
      case "running":
        return t("probe.running");
      case "queued":
        return t("probe.queued");
      default:
        return t("probe.pending");
    }
  };
}

/** Petit badge verdict « 4/5 » (utilisé dans le tableau prof). */
export function RunVerdictBadge({ run }: { run?: Pick<GradingRun, "status" | "passed_checks" | "total_checks"> | null }) {
  const { t } = useI18n();
  if (!run) return <span className="muted">—</span>;
  if (run.status === "queued" || run.status === "running") {
    return (
      <Badge tone="blue">
        <Loader2 size={12} className="animate-spin" /> {t("probe.running")}
      </Badge>
    );
  }
  if (run.status === "error") return <Badge tone="red">{t("probe.result_error")}</Badge>;
  const passed = run.passed_checks ?? 0;
  const total = run.total_checks ?? 0;
  const tone: Tone = total > 0 && passed === total ? "green" : passed === 0 ? "red" : "amber";
  return <Badge tone={tone}>{`${passed}/${total}`}</Badge>;
}

/** Résumé d'un run : statut global + score suggéré. */
export function RunSummary({ run }: { run?: GradingRun | null }) {
  const { t } = useI18n();
  if (!run) return null;
  if (run.status === "queued") return <p className="muted text-sm">{t("probe.queued")}</p>;
  if (run.status === "running") {
    return (
      <p className="text-sm inline-flex items-center gap-2" style={{ color: STATUS_COLOR.running }}>
        <Loader2 size={14} className="animate-spin" /> {t("probe.running")}
      </p>
    );
  }
  if (run.status === "error") {
    return <p className="text-sm" style={{ color: STATUS_COLOR.error }}>{run.error || t("probe.run_failed")}</p>;
  }
  const passed = run.passed_checks ?? 0;
  const total = run.total_checks ?? 0;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <RunVerdictBadge run={run} />
      <span className="text-sm">{t("probe.score", { passed, total })}</span>
      {run.score_suggestion ? (
        <span className="muted text-sm">
          {t("probe.suggested_grade")}: <strong>{run.score_suggestion}</strong>
        </span>
      ) : null}
    </div>
  );
}

/**
 * Liste check par check. Deux modes :
 *  - étudiant : on passe `visibleProbes` pour afficher les tests « en attente »
 *    avant l'exécution, puis on superpose les résultats du run par id.
 *  - prof : on passe directement `run` (résultats détaillés non filtrés).
 */
export function GradingResultList({
  run,
  visibleProbes,
}: {
  run?: GradingRun | null;
  visibleProbes?: StudentProbe[];
}) {
  const { t } = useI18n();
  const label = useStatusLabel();

  const resultsById = new Map<string, ProbeResult>();
  (run?.results || []).forEach((r) => resultsById.set(r.id, r));

  const runPending = run?.status === "queued" || run?.status === "running";

  // Lignes à afficher : la liste des probes visibles (étudiant) ou les résultats (prof).
  let rows: Array<{ id: string; name: string; result?: ProbeResult }>;
  if (visibleProbes && visibleProbes.length > 0) {
    rows = visibleProbes.map((p) => ({ id: p.id, name: p.name, result: resultsById.get(p.id) }));
  } else {
    rows = (run?.results || []).map((r) => ({ id: r.id, name: r.name, result: r }));
  }

  if (rows.length === 0) {
    return <p className="muted text-sm">{t("probe.no_tests_student")}</p>;
  }

  return (
    <ul className="grading-checklist">
      {rows.map((row) => {
        const status = row.result?.status || (runPending ? "running" : "pending");
        return (
          <li key={row.id} className="grading-check">
            <StatusIcon status={status} />
            <div className="grading-check-body">
              <div className="grading-check-head">
                <span className="grading-check-name">{row.name}</span>
                <Badge tone={statusTone(status)}>{label(status)}</Badge>
              </div>
              {row.result?.message ? (
                <p className="grading-check-message">{row.result.message}</p>
              ) : null}
              {row.result?.output ? (
                <pre className="grading-check-output">{row.result.output}</pre>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
