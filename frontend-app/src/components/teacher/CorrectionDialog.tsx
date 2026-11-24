import { useMutation, useQuery } from "@tanstack/react-query";
import { ExternalLink, FlaskConical } from "lucide-react";
import { useEffect, useState } from "react";
import { GradingResultList, RunSummary } from "../GradingResults";
import { getDeploymentDetails, getSubmissionDetail, gradeSubmission } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Badge, Button, errorMessage, ErrorState, LoadingState, ModalShell, showToast } from "../ui";

/** Shows a student's submission and test results, and publishes the grade + feedback. */
export function CorrectionDialog({
  classroomId,
  assignmentId,
  submissionId,
  onClose,
  onGraded,
}: {
  classroomId: number;
  assignmentId: number;
  submissionId: number;
  onClose: () => void;
  onGraded: () => void;
}) {
  const { t } = useI18n();
  const [grade, setGrade] = useState("");
  const [feedback, setFeedback] = useState("");
  const [prefilled, setPrefilled] = useState(false);
  const [suggested, setSuggested] = useState(false);
  const [opening, setOpening] = useState(false);

  const sub = useQuery({
    queryKey: ["submission-detail", classroomId, assignmentId, submissionId],
    queryFn: () => getSubmissionDetail(classroomId, assignmentId, submissionId),
  });
  const data = sub.data;

  // Prefill once with the existing correction, or else the weighted suggestion from the
  // tests. Done once so the teacher can clear the fields without them refilling.
  useEffect(() => {
    if (!data || prefilled) return;
    const suggestion = !data.grade ? data.grading_run?.score_suggestion : null;
    setGrade(data.grade || suggestion || "");
    setFeedback(data.feedback || "");
    setSuggested(Boolean(suggestion));
    setPrefilled(true);
  }, [data, prefilled]);

  const gradeMut = useMutation({
    mutationFn: () =>
      gradeSubmission(classroomId, assignmentId, submissionId, {
        grade: grade.trim() || undefined,
        feedback: feedback.trim() || undefined,
      }),
    onSuccess: () => {
      showToast(t("correction.graded_ok"), "success");
      onGraded();
    },
    onError: (e) => showToast(errorMessage(e, t("common.error")), "error"),
  });

  async function openStudentLab() {
    const snap = data?.lab_snapshot as { name?: string; namespace?: string } | null | undefined;
    if (!snap?.name || !snap?.namespace) {
      showToast(t("correction.lab_gone"), "info");
      return;
    }
    setOpening(true);
    try {
      const d = await getDeploymentDetails(snap.namespace, snap.name);
      const url = d.access_urls?.find((a) => a.url)?.url;
      if (url) window.open(url, "_blank", "noopener,noreferrer");
      else showToast(t("correction.lab_gone"), "info");
    } catch {
      showToast(t("correction.lab_gone"), "info");
    } finally {
      setOpening(false);
    }
  }

  return (
    <ModalShell open onOpenChange={(o) => (!o ? onClose() : undefined)} title={t("correction.dialog_title")} wide>
      {sub.isLoading ? <LoadingState label={t("common.loading")} /> : null}
      {sub.error ? (
        <ErrorState
          title={t("teacher.error_load_submission")}
          error={sub.error}
          onRetry={() => void sub.refetch()}
          retrying={sub.isFetching}
        />
      ) : null}
      {data ? (
        <div className="flex flex-col gap-4">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="m-0">{t("correction.submitted_work")}</h3>
              {data.is_late ? <Badge tone="amber">{t("myassignments.status_late")}</Badge> : null}
            </div>
            {data.text ? (
              <p
                className="whitespace-pre-wrap leading-relaxed mt-2 break-words"
                style={{
                  padding: "12px 14px",
                  borderRadius: "var(--radius)",
                  background: "var(--surface-muted)",
                  border: "1px solid var(--border)",
                }}
              >
                {data.text}
              </p>
            ) : (
              <p className="muted mt-2">{t("correction.no_text")}</p>
            )}
            {data.links && data.links.length > 0 ? (
              <ul className="mt-2 flex flex-col gap-1">
                {data.links.map((l, i) => (
                  <li key={i}>
                    <a href={l.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 break-all">
                      {l.label || l.url} <ExternalLink size={13} aria-hidden="true" />
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={openStudentLab} disabled={opening}>
              <ExternalLink size={16} aria-hidden="true" />{" "}
              {opening ? t("submission.opening") : t("correction.open_student_lab")}
            </Button>
            <span className="muted text-sm">{t("correction.lab_hint")}</span>
          </div>

          {data.grading_run ? (
            <div className="border-t border-[var(--border)] pt-4">
              <h3 className="inline-flex items-center gap-2">
                <FlaskConical size={16} aria-hidden="true" /> {t("probe.results")}
              </h3>
              <div className="mt-2 mb-3">
                <RunSummary run={data.grading_run} />
              </div>
              <GradingResultList run={data.grading_run} />
            </div>
          ) : null}

          <form
            className="border-t border-[var(--border)] pt-4 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              gradeMut.mutate();
            }}
          >
            <div className="field">
              <label htmlFor="correction-grade">{t("submission.grade")}</label>
              <input
                id="correction-grade"
                value={grade}
                onChange={(e) => {
                  setGrade(e.target.value);
                  setSuggested(false);
                }}
                placeholder="15/20"
              />
              {suggested ? <span className="muted text-xs">{t("teacher.grade_suggested_hint")}</span> : null}
            </div>
            <div className="field full">
              <label htmlFor="correction-feedback">{t("submission.feedback")}</label>
              <textarea id="correction-feedback" rows={5} value={feedback} onChange={(e) => setFeedback(e.target.value)} />
            </div>
            <div className="actions-row justify-end">
              <Button type="button" onClick={onClose}>
                {t("common.cancel")}
              </Button>
              <Button variant="primary" type="submit" disabled={gradeMut.isPending}>
                {gradeMut.isPending ? t("correction.grading") : t("correction.publish")}
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </ModalShell>
  );
}
