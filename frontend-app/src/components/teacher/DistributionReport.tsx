import { X } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import type { BulkSpawnResult } from "../../types/api";
import { IconButton, LoadingState, StatusBadge } from "../ui";
import type { DistributionState } from "./queries";

/** Progress and per-student outcome of "distribute to the class". */
export function DistributionReport({
  state,
  assignmentTitle,
  onDismiss,
}: {
  state: DistributionState;
  assignmentTitle?: string;
  onDismiss: () => void;
}) {
  const { t } = useI18n();
  const report = state.report;

  return (
    <div className="card mb-4 p-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <strong>{assignmentTitle ? t("teacher.distribution_of", { title: assignmentTitle }) : t("assignment.distribute")}</strong>
        {report ? (
          <div className="flex items-center gap-2">
            <span>{t("assignment.deploy_done", { ok: report.ok, errors: report.errors, skipped: report.skipped })}</span>
            <IconButton onClick={onDismiss} aria-label={t("common.close")}>
              <X size={15} aria-hidden="true" />
            </IconButton>
          </div>
        ) : null}
      </div>
      {!report ? <LoadingState label={t("assignment.deploying")} /> : null}
      {report && report.results.length ? (
        <div className="table-wrap mt-3">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("overview.student")}</th>
                <th>{t("submission.status")}</th>
                <th>{t("teacher.col_lab")}</th>
                <th>{t("common.error")}</th>
              </tr>
            </thead>
            <tbody>
              {report.results.map((result: BulkSpawnResult) => (
                <tr key={result.user_id}>
                  <td>{result.username}</td>
                  <td>
                    <StatusBadge state={result.status === "ok" ? "ok" : result.status === "skipped" ? "skipped" : "error"} />
                  </td>
                  <td>{result.deployment_name || "—"}</td>
                  <td className="whitespace-normal">{result.error || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
