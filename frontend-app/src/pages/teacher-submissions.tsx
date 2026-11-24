import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical, PlayCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageHeader } from "../components/AppShell";
import { Badge, Button, EmptyState, errorMessage, QueryState, showToast, SkeletonRows } from "../components/ui";
import { type ColumnDef, DataTable } from "../components/DataTable";
import { GradingResultList, RunSummary, RunVerdictBadge } from "../components/GradingResults";
import { CorrectionDialog } from "../components/teacher/CorrectionDialog";
import { getAssignmentSubmissions, getGradingRunTeacher, runTestsAll, testNow } from "../lib/api";
import { fullDate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { GradingRun, TeacherSubmissionRow } from "../types/api";

/** Sort rank so that work to correct comes first when sorting by status. */
function statusRank(row: TeacherSubmissionRow): number {
  if (row.submission_status === "submitted") return row.is_late ? 1 : 0;
  if (row.submission_status === "graded") return 2;
  return 3;
}

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
    // While tests run, poll so the verdict column updates.
    refetchInterval: (query) => {
      const data = query.state.data as TeacherSubmissionRow[] | undefined;
      const running = data?.some((r) => r.grading_status === "queued" || r.grading_status === "running");
      return running ? 2500 : false;
    },
  });

  // Teacher's demo run ("Test now").
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
    onError: (e) => showToast(errorMessage(e, t("probe.run_failed")), "error"),
  });

  const runAllMut = useMutation({
    mutationFn: () => runTestsAll(classroomId, assignmentId),
    onSuccess: (res) => {
      showToast(t("probe.run_all_done", { n: res.queued }), "success");
      queryClient.invalidateQueries({ queryKey: ["assignment-submissions", classroomId, assignmentId] });
    },
    onError: (e) => showToast(errorMessage(e, t("probe.run_failed")), "error"),
  });

  const demoActive = demoRun.data?.status === "queued" || demoRun.data?.status === "running" || testNowMut.isPending;

  const columns = useMemo<ColumnDef<TeacherSubmissionRow>[]>(
    () => [
      {
        id: "student",
        header: t("correction.student"),
        accessorFn: (row) => row.username,
        cell: ({ row }) => (
          <>
            <strong>{row.original.username}</strong>
            {row.original.email ? <div className="muted text-sm">{row.original.email}</div> : null}
          </>
        ),
      },
      {
        id: "status",
        header: t("submission.status"),
        accessorFn: statusRank,
        cell: ({ row }) => <StatusCell row={row.original} />,
      },
      {
        id: "verdict",
        header: t("probe.verdict_label"),
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original;
          return (
            <RunVerdictBadge
              run={
                r.grading_status
                  ? { status: r.grading_status, passed_checks: r.grading_passed ?? null, total_checks: r.grading_total ?? null }
                  : null
              }
            />
          );
        },
      },
      {
        id: "submitted",
        header: t("submission.submitted_at"),
        accessorFn: (row) => row.submitted_at ?? "",
        cell: ({ row }) => <span className="muted">{row.original.submitted_at ? fullDate(row.original.submitted_at) : "—"}</span>,
      },
      {
        id: "grade",
        header: t("submission.grade"),
        accessorFn: (row) => row.grade ?? "",
        cell: ({ row }) =>
          row.original.grade ? (
            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700 }}>{row.original.grade}</span>
          ) : (
            <span className="muted">—</span>
          ),
      },
      {
        id: "actions",
        header: t("dashboard.actions"),
        enableSorting: false,
        cell: ({ row }) =>
          row.original.submission_id ? (
            <Button
              onClick={() => setOpenSid(row.original.submission_id!)}
              aria-label={t("teacher.grade_student", { name: row.original.username })}
            >
              {t("correction.grade")}
            </Button>
          ) : (
            <span className="muted text-sm">{t("correction.nothing_to_grade")}</span>
          ),
      },
    ],
    [t],
  );

  const items = rows.data || [];

  return (
    <>
      <div>
        <Link to="/teacher" className="muted inline-flex items-center gap-1 text-sm no-underline">
          <ArrowLeft size={15} aria-hidden="true" /> {t("correction.back")}
        </Link>
      </div>
      <PageHeader title={t("correction.title")} subtitle={t("correction.subtitle")} />

      <div className="actions-row justify-end mb-3 gap-2">
        <Button onClick={() => testNowMut.mutate()} disabled={demoActive} title={t("probe.test_now_hint")}>
          <FlaskConical size={16} aria-hidden="true" /> {demoActive ? t("probe.running") : t("probe.test_now")}
        </Button>
        <Button variant="primary" onClick={() => runAllMut.mutate()} disabled={runAllMut.isPending}>
          <PlayCircle size={16} aria-hidden="true" /> {runAllMut.isPending ? t("probe.run_all_pending") : t("probe.run_all")}
        </Button>
      </div>

      {demoRunId !== null && demoRun.data ? (
        <section className="panel tests-panel mb-3">
          <div className="section-head">
            <h2 className="inline-flex items-center gap-2 text-base">
              <FlaskConical size={16} aria-hidden="true" /> {t("probe.test_now")}
            </h2>
            <RunSummary run={demoRun.data} />
          </div>
          <GradingResultList run={demoRun.data} />
        </section>
      ) : null}

      <QueryState
        query={rows}
        skeleton={
          <section className="panel">
            <SkeletonRows rows={6} cols={6} />
          </section>
        }
        errorTitle={t("teacher.error_submissions")}
        isEmpty={items.length === 0}
        empty={<EmptyState title={t("correction.empty")}>{t("teacher.submissions_empty_hint")}</EmptyState>}
      >
        <section className="panel">
          <DataTable
            data={items}
            columns={columns}
            getRowId={(row) => String(row.user_id)}
            label={t("correction.title")}
          />
        </section>
      </QueryState>

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
