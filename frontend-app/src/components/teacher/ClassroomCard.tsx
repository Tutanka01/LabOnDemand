import { useMutation } from "@tanstack/react-query";
import { Archive, BookOpen, Edit2, GraduationCap, Users } from "lucide-react";
import type { Classroom } from "../../types/api";
import { deleteClassroom } from "../../lib/api";
import { shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { Button, ConfirmDialog, errorMessage, showToast } from "../ui";
import { useInvalidateClassroom } from "./queries";

export function ClassroomCard({
  classroom,
  onEdit,
  onSelect,
}: {
  classroom: Classroom;
  onEdit: (c: Classroom) => void;
  onSelect: (id: number) => void;
}) {
  const { t } = useI18n();
  const invalidateClassroom = useInvalidateClassroom();

  const archiveMutation = useMutation({
    mutationFn: () => deleteClassroom(classroom.id),
    onSuccess: () => {
      invalidateClassroom();
      showToast(t("teacher.toast_classroom_archived"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("teacher.error_archive_classroom")), "error"),
  });

  const students = classroom.student_count || 0;
  const assignments = classroom.active_assignment_count || 0;

  return (
    <article
      className="card card-interactive teacher-classroom-card"
      onClick={() => onSelect(classroom.id)}
      role="button"
      tabIndex={0}
      aria-label={t("teacher.manage_classroom", { name: classroom.name })}
      onKeyDown={(e) => {
        // Only react to keys on the card itself, not on the buttons inside it.
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(classroom.id);
        }
      }}
    >
      <div className="teacher-cls-head">
        <div className="flex min-w-0 items-center gap-3">
          <span className="runtime-mark flex-none" aria-hidden="true">
            <GraduationCap size={18} />
          </span>
          <div className="min-w-0">
            <strong className="block truncate text-base">{classroom.name}</strong>
            <div className="muted truncate text-xs">{classroom.description || t("teacher.no_description")}</div>
          </div>
        </div>
        <div className="actions-row" onClick={(e) => e.stopPropagation()}>
          <Button
            onClick={() => onEdit(classroom)}
            aria-label={t("teacher.edit_classroom")}
            title={t("teacher.edit_classroom")}
          >
            <Edit2 size={16} aria-hidden="true" />
          </Button>
          <ConfirmDialog
            destructive
            title={t("teacher.archive_classroom_title")}
            description={t("teacher.archive_classroom_body", { name: classroom.name })}
            confirmLabel={t("classroom.archive")}
            trigger={
              <Button
                variant="danger"
                aria-label={t("teacher.archive_classroom_title")}
                title={t("teacher.archive_classroom_title")}
                disabled={archiveMutation.isPending}
              >
                <Archive size={16} aria-hidden="true" />
              </Button>
            }
            onConfirm={() => archiveMutation.mutate()}
          />
        </div>
      </div>

      <div className="mt-1 grid grid-cols-2 gap-4 border-t border-[var(--border)] pt-3">
        <div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
            <Users size={13} aria-hidden="true" /> {t("students.title")}
          </div>
          <strong className="text-xl">{students}</strong>
        </div>
        <div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
            <BookOpen size={13} aria-hidden="true" /> {t("teacher.active_assignments")}
          </div>
          <strong className="text-xl">{assignments}</strong>
        </div>
      </div>

      <div className="mt-1 flex items-center justify-between gap-3">
        <span className="muted text-xs">
          {classroom.created_at ? t("teacher.created_on", { date: shortDate(classroom.created_at) }) : ""}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--primary)]">
          <Users size={14} aria-hidden="true" /> {t("teacher.manage")}
        </span>
      </div>
    </article>
  );
}
