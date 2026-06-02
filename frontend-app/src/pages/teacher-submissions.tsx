import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
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
  showToast,
} from "../components/ui";
import {
  getAssignmentSubmissions,
  getDeploymentDetails,
  getSubmissionDetail,
  gradeSubmission,
} from "../lib/api";
import { fullDate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { TeacherSubmissionRow } from "../types/api";

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

  const rows = useQuery({
    queryKey: ["assignment-submissions", classroomId, assignmentId],
    queryFn: () => getAssignmentSubmissions(classroomId, assignmentId),
    enabled: Number.isFinite(classroomId) && Number.isFinite(assignmentId),
  });

  return (
    <>
      <div>
        <Link to="/teacher" className="muted inline-flex items-center gap-1 text-sm no-underline">
          <ArrowLeft size={15} /> {t("correction.back")}
        </Link>
      </div>
      <PageHeader title={t("correction.title")} subtitle={t("correction.subtitle")} />

      {rows.isLoading ? <LoadingState label={t("common.loading")} /> : null}
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
                  <td>{row.submitted_at ? fullDate(row.submitted_at) : "—"}</td>
                  <td>{row.grade || "—"}</td>
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
            <h3>{t("correction.submitted_work")}</h3>
            {data.is_late ? <Badge tone="amber">{t("myassignments.status_late")}</Badge> : null}
            {data.text ? (
              <p className="whitespace-pre-wrap leading-relaxed mt-2">{data.text}</p>
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
