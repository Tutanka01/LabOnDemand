import { useMutation } from "@tanstack/react-query";
import { Archive, ClipboardList, Edit2, Plus, Rocket } from "lucide-react";
import { Link } from "react-router-dom";
import { deleteAssignment } from "../../lib/api";
import { fullDate, presetLabel } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { Assignment } from "../../types/api";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  errorMessage,
  QueryState,
  showToast,
  SkeletonCards,
} from "../ui";
import { DistributionReport } from "./DistributionReport";
import { type AssignmentDistribution, useClassroomAssignments, useInvalidateClassroom } from "./queries";

/** Assignments of a classroom: create, edit, distribute to the class, archive. */
export function ClassroomAssignmentsTab({
  classroomId,
  studentCount,
  distribution,
  onCreate,
  onEdit,
}: {
  classroomId: number;
  studentCount: number;
  distribution: AssignmentDistribution;
  onCreate: () => void;
  onEdit: (assignment: Assignment) => void;
}) {
  const { t } = useI18n();
  const assignments = useClassroomAssignments(classroomId);
  const invalidateClassroom = useInvalidateClassroom();

  const archive = useMutation({
    mutationFn: (assignmentId: number) => deleteAssignment(classroomId, assignmentId),
    onSuccess: () => {
      invalidateClassroom(classroomId);
      showToast(t("teacher.toast_assignment_archived"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("teacher.error_archive_assignment")), "error"),
  });

  const items = assignments.data || [];
  const distributedTitle = distribution.state
    ? items.find((a) => a.id === distribution.state?.assignmentId)?.title
    : undefined;

  return (
    <section className="panel">
      <div className="section-head">
        <h2>{t("assignment.title")}</h2>
        <Button variant="primary" onClick={onCreate}>
          <Plus size={16} aria-hidden="true" /> {t("assignment.new")}
        </Button>
      </div>

      {distribution.state ? (
        <DistributionReport state={distribution.state} assignmentTitle={distributedTitle} onDismiss={distribution.dismiss} />
      ) : null}

      <QueryState
        query={assignments}
        skeleton={<SkeletonCards count={3} lines={2} />}
        errorTitle={t("teacher.error_assignments")}
        isEmpty={items.length === 0}
        empty={
          <EmptyState
            title={t("assignment.empty")}
            action={
              <Button variant="primary" onClick={onCreate}>
                <Plus size={16} aria-hidden="true" /> {t("assignment.new")}
              </Button>
            }
          >
            {t("teacher.assignments_empty_hint")}
          </EmptyState>
        }
      >
        <div className="grid gap-3">
          {items.map((a) => (
            <article className="card p-4" key={a.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <strong>{a.title}</strong>
                  <div className="lab-meta mt-1.5">
                    {a.template_key ? <span className="badge">{a.template_key}</span> : null}
                    <span className="badge">CPU {presetLabel(a.cpu_preset)}</span>
                    <span className="badge">RAM {presetLabel(a.ram_preset)}</span>
                    {a.due_at ? (
                      <span className="badge">
                        {t("assignment.due")} {fullDate(a.due_at)}
                      </span>
                    ) : null}
                  </div>
                  {a.instructions ? (
                    <p className="muted mt-2 text-sm break-words">
                      {a.instructions.slice(0, 200)}
                      {a.instructions.length > 200 ? "…" : ""}
                    </p>
                  ) : null}
                </div>
                <div className="actions-row">
                  <ConfirmDialog
                    title={t("assignment.confirm_deploy_title")}
                    description={
                      studentCount > 0
                        ? t("assignment.confirm_deploy_body", { count: studentCount })
                        : t("teacher.distribute_no_students")
                    }
                    confirmLabel={t("assignment.distribute")}
                    trigger={
                      <Button variant="primary" disabled={distribution.isPending}>
                        <Rocket size={16} aria-hidden="true" />
                        {distribution.isPending && distribution.state?.assignmentId === a.id
                          ? t("assignment.deploying")
                          : t("assignment.distribute")}
                      </Button>
                    }
                    onConfirm={() => distribution.distribute(a.id)}
                  />
                  <Link
                    to={`/teacher/classrooms/${a.classroom_id}/assignments/${a.id}/submissions`}
                    className="btn inline-flex items-center gap-1 no-underline"
                  >
                    <ClipboardList size={16} aria-hidden="true" /> {t("assignment.view_submissions")}
                  </Link>
                  <Button onClick={() => onEdit(a)}>
                    <Edit2 size={14} aria-hidden="true" /> {t("common.edit")}
                  </Button>
                  <ConfirmDialog
                    destructive
                    title={t("assignment.archive")}
                    description={t("teacher.archive_assignment_body", { title: a.title })}
                    confirmLabel={t("assignment.archive")}
                    trigger={
                      <Button
                        variant="danger"
                        disabled={archive.isPending && archive.variables === a.id}
                        aria-label={t("teacher.archive_assignment_named", { title: a.title })}
                        title={t("assignment.archive")}
                      >
                        <Archive size={14} aria-hidden="true" />
                      </Button>
                    }
                    onConfirm={() => archive.mutate(a.id)}
                  />
                </div>
              </div>
            </article>
          ))}
        </div>
      </QueryState>
    </section>
  );
}
