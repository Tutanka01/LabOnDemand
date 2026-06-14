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
  pass: "var(--success)",
  fail: "var(--danger)",
  error: "var(--danger)",
  skip: "var(--warning)",
  running: "var(--accent-blue)",
  queued: "var(--accent-blue)",
  pending: "var(--muted)",
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
  if (run.status === "queued") {
    return (
      <p className="muted text-sm inline-flex items-center gap-2">
        <Clock size={14} /> {t("probe.queued")}
      </p>
    );
  }
  if (run.status === "running") {
    return (
      <p className="text-sm inline-flex items-center gap-2" style={{ color: STATUS_COLOR.running }}>
        <Loader2 size={14} className="animate-spin" /> {t("probe.running")}
      </p>
    );
  }
  if (run.status === "error") {
    return (
      <p
        className="text-sm inline-flex items-center gap-2"
        style={{ color: STATUS_COLOR.error }}
      >
        <AlertTriangle size={14} /> {run.error || t("probe.run_failed")}
      </p>
    );
  }
  const passed = run.passed_checks ?? 0;
  const total = run.total_checks ?? 0;
  const pct = total > 0 ? Math.round((passed / total) * 100) : 0;
  const allPass = total > 0 && passed === total;
  const barColor = allPass ? "var(--success)" : passed === 0 ? "var(--danger)" : "var(--warning)";

  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-2"
      style={{
        padding: "12px 14px",
        borderRadius: "var(--radius)",
        background: "var(--surface-soft)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-center gap-2">
        {allPass ? (
          <CheckCircle2 size={18} style={{ color: "var(--success)" }} />
        ) : (
          <XCircle size={18} style={{ color: barColor }} />
        )}
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 700,
            fontSize: "1.05rem",
            color: barColor,
          }}
        >
          {passed}
          <span className="muted" style={{ fontWeight: 600 }}>
            /{total}
          </span>
        </span>
        <span className="muted text-sm">{t("probe.score", { passed, total })}</span>
      </div>

      {/* Progress track */}
      <div
        aria-hidden
        style={{
          flex: "1 1 120px",
          minWidth: 80,
          height: 6,
          borderRadius: "var(--radius-full)",
          background: "var(--surface-muted)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: barColor,
            borderRadius: "var(--radius-full)",
            transition: "width 0.4s ease",
          }}
        />
      </div>

      {run.score_suggestion ? (
        <span className="muted text-sm whitespace-nowrap">
          {t("probe.suggested_grade")}: <strong style={{ color: "var(--text)" }}>{run.score_suggestion}</strong>
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
        const accent = STATUS_COLOR[status] || STATUS_COLOR.pending;
        return (
          <li
            key={row.id}
            className="grading-check"
            style={{ borderLeft: `3px solid ${accent}` }}
          >
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
                <pre
                  className="grading-check-output"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {row.result.output}
                </pre>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
