import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, FlaskConical, PlayCircle } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageHeader } from "../components/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  ModalShell,
  SkeletonRows,
  showToast,
} from "../components/ui";
import { GradingResultList, RunSummary, RunVerdictBadge } from "../components/GradingResults";
import {
  getAssignmentSubmissions,
  getDeploymentDetails,
  getGradingRunTeacher,
  getSubmissionDetail,
  gradeSubmission,
  runTestsAll,
  testNow,
} from "../lib/api";
import { fullDate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { GradingRun, TeacherSubmissionRow } from "../types/api";

function StatusCell({ row }: { row: TeacherSubmissionRow }) {
  const { t } = useI18n();
  if (row.submission_status === "graded") return <Badge tone="green">{t("myassignments.status_graded")}</Badge>;
  if (row.submission_status === "submitted")
    return row.is_late ? (
      <Badge tone="amber">{t("myassignments.status_late")}</Badge>
    ) : (
      <Badge tone="blue">{t("myassignments.status_submitted")}</Badge>
    );
  return <Badge>{t("myassignments.status_not_started")}</Badge>;
}

export default function TeacherSubmissionsPage() {
  const { cid, aid } = useParams();
  const classroomId = Number(cid);
  const assignmentId = Number(aid);
  const { t } = useI18n();
  const queryClient = useQueryClient();

  const [openSid, setOpenSid] = useState<number | null>(null);
  const [demoRunId, setDemoRunId] = useState<number | null>(null);

  const rows = useQuery({
    queryKey: ["assignment-submissions", classroomId, assignmentId],
    queryFn: () => getAssignmentSubmissions(classroomId, assignmentId),
    enabled: Number.isFinite(classroomId) && Number.isFinite(assignmentId),
    // Tant que des tests tournent, on rafraîchit pour faire vivre la colonne verdict.
    refetchInterval: (query) => {
      const data = query.state.data as TeacherSubmissionRow[] | undefined;
      const running = data?.some((r) => r.grading_status === "queued" || r.grading_status === "running");
      return running ? 2500 : false;
    },
  });

  // Run de démo du prof (« Tester maintenant »).
  const demoRun = useQuery({
    queryKey: ["teacher-grading-run", classroomId, assignmentId, demoRunId],
    queryFn: () => getGradingRunTeacher(classroomId, assignmentId, demoRunId as number),
    enabled: demoRunId !== null,
    refetchInterval: (query) => {
      const s = (query.state.data as GradingRun | undefined)?.status;
      return s === "queued" || s === "running" ? 1500 : false;
    },
  });

  const testNowMut = useMutation({
    mutationFn: () => testNow(classroomId, assignmentId),
    onSuccess: (run) => {
      setDemoRunId(run.id);
      queryClient.setQueryData(["teacher-grading-run", classroomId, assignmentId, run.id], run);
    },
    onError: (e) => showToast((e as Error).message, "error"),
  });

  const runAllMut = useMutation({
    mutationFn: () => runTestsAll(classroomId, assignmentId),
    onSuccess: (res) => {
      showToast(t("probe.run_all_done", { n: res.queued }), "success");
      queryClient.invalidateQueries({ queryKey: ["assignment-submissions", classroomId, assignmentId] });
    },
    onError: (e) => showToast((e as Error).message, "error"),
  });

  const demoActive = demoRun.data?.status === "queued" || demoRun.data?.status === "running" || testNowMut.isPending;

  return (
    <>
      <div>
        <Link to="/teacher" className="muted inline-flex items-center gap-1 text-sm no-underline">
          <ArrowLeft size={15} /> {t("correction.back")}
        </Link>
      </div>
      <PageHeader title={t("correction.title")} subtitle={t("correction.subtitle")} />

      <div className="actions-row justify-end mb-3 gap-2">
        <Button onClick={() => testNowMut.mutate()} disabled={demoActive}>
          <FlaskConical size={16} /> {demoActive ? t("probe.running") : t("probe.test_now")}
        </Button>
        <Button variant="primary" onClick={() => runAllMut.mutate()} disabled={runAllMut.isPending}>
          <PlayCircle size={16} /> {runAllMut.isPending ? t("probe.run_all_pending") : t("probe.run_all")}
        </Button>
      </div>

      {demoRunId !== null && demoRun.data ? (
        <section className="panel tests-panel mb-3">
          <div className="section-head">
            <h2 className="inline-flex items-center gap-2 text-base">
              <FlaskConical size={16} /> {t("probe.test_now")}
            </h2>
            <RunSummary run={demoRun.data} />
          </div>
          <GradingResultList run={demoRun.data} />
        </section>
      ) : null}

      {rows.isLoading ? (
        <section className="panel">
          <SkeletonRows rows={6} cols={6} />
        </section>
      ) : null}
      {rows.error ? <ErrorState>{(rows.error as Error).message}</ErrorState> : null}
      {!rows.isLoading && !rows.error && (rows.data?.length || 0) === 0 ? (
        <EmptyState title={t("correction.empty")} />
      ) : null}

      {rows.data && rows.data.length > 0 ? (
        <section className="panel">
          <table className="data-table w-full">
            <thead>
              <tr>
                <th>{t("correction.student")}</th>
                <th>{t("submission.status")}</th>
                <th>{t("probe.verdict_label")}</th>
                <th>{t("submission.submitted_at")}</th>
                <th>{t("submission.grade")}</th>
                <th>{t("dashboard.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((row) => (
                <tr key={row.user_id}>
                  <td>
                    <strong>{row.username}</strong>
                    {row.email ? <div className="muted text-sm">{row.email}</div> : null}
                  </td>
                  <td><StatusCell row={row} /></td>
                  <td>
                    <RunVerdictBadge
                      run={
                        row.grading_status
                          ? {
                              status: row.grading_status,
                              passed_checks: row.grading_passed ?? null,
                              total_checks: row.grading_total ?? null,
                            }
                          : null
                      }
                    />
                  </td>
                  <td className="muted">{row.submitted_at ? fullDate(row.submitted_at) : "—"}</td>
                  <td>
                    {row.grade ? (
                      <span style={{ fontFamily: "var(--font-display)", fontWeight: 700 }}>
                        {row.grade}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {row.submission_id ? (
                      <Button onClick={() => setOpenSid(row.submission_id!)}>{t("correction.grade")}</Button>
                    ) : (
                      <span className="muted text-sm">{t("correction.nothing_to_grade")}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {openSid !== null ? (
        <CorrectionDialog
          classroomId={classroomId}
          assignmentId={assignmentId}
          submissionId={openSid}
          onClose={() => setOpenSid(null)}
          onGraded={() => {
            queryClient.invalidateQueries({ queryKey: ["assignment-submissions", classroomId, assignmentId] });
            setOpenSid(null);
          }}
        />
      ) : null}
    </>
  );
}

function CorrectionDialog({
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
  const [opening, setOpening] = useState(false);

  const sub = useQuery({
    queryKey: ["submission-detail", classroomId, assignmentId, submissionId],
    queryFn: () => getSubmissionDetail(classroomId, assignmentId, submissionId),
  });

  // Pré-remplir avec la correction existante.
  const data = sub.data;
  if (data && grade === "" && feedback === "" && (data.grade || data.feedback)) {
    if (data.grade) setGrade(data.grade);
    if (data.feedback) setFeedback(data.feedback);
  }
  // À défaut de note existante, proposer la suggestion pondérée des tests (modifiable).
  if (data && grade === "" && !data.grade && data.grading_run?.score_suggestion) {
    setGrade(data.grading_run.score_suggestion);
  }

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
    onError: (e) => showToast((e as Error).message, "error"),
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
      {sub.error ? <ErrorState>{(sub.error as Error).message}</ErrorState> : null}
      {data ? (
        <div className="flex flex-col gap-4">
          {/* Rendu de l'étudiant */}
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="m-0">{t("correction.submitted_work")}</h3>
              {data.is_late ? <Badge tone="amber">{t("myassignments.status_late")}</Badge> : null}
            </div>
            {data.text ? (
              <p
                className="whitespace-pre-wrap leading-relaxed mt-2"
                style={{
                  padding: "12px 14px",
                  borderRadius: "var(--radius)",
                  background: "var(--surface-soft)",
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
                    <a href={l.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1">
                      {l.label || l.url} <ExternalLink size={13} />
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          {/* Snapshot lab */}
          <div className="flex items-center gap-3">
            <Button onClick={openStudentLab} disabled={opening}>
              <ExternalLink size={16} /> {opening ? t("submission.opening") : t("correction.open_student_lab")}
            </Button>
            <span className="muted text-sm">{t("correction.lab_hint")}</span>
          </div>

          {/* Résultats des tests automatiques */}
          {data.grading_run ? (
            <div className="border-t border-[var(--border)] pt-4">
              <h3 className="inline-flex items-center gap-2">
                <FlaskConical size={16} /> {t("probe.results")}
              </h3>
              <div className="mt-2 mb-3">
                <RunSummary run={data.grading_run} />
              </div>
              <GradingResultList run={data.grading_run} />
            </div>
          ) : null}

          {/* Correction */}
          <div className="border-t border-[var(--border)] pt-4 flex flex-col gap-3">
            <div className="field">
              <label>{t("submission.grade")}</label>
              <input value={grade} onChange={(e) => setGrade(e.target.value)} placeholder="15/20" />
            </div>
            <div className="field full">
              <label>{t("submission.feedback")}</label>
              <textarea rows={5} value={feedback} onChange={(e) => setFeedback(e.target.value)} />
            </div>
            <div className="actions-row justify-end">
              <Button onClick={onClose}>{t("common.cancel")}</Button>
              <Button variant="primary" disabled={gradeMut.isPending} onClick={() => gradeMut.mutate()}>
                {gradeMut.isPending ? t("correction.grading") : t("correction.publish")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </ModalShell>
  );
}
