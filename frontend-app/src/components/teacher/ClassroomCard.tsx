import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, BookOpen, Edit2, GraduationCap, Users } from "lucide-react";
import type { Classroom } from "../../types/api";
import { deleteClassroom } from "../../lib/api";
import { shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { Button, ConfirmDialog, showToast } from "../ui";

export function ClassroomCard({
  classroom,
  onEdit,
  onSelect,
}: {
  classroom: Classroom;
  onEdit: (c: Classroom) => void;
  onSelect: (id: number) => void;
}) {
  const queryClient = useQueryClient();
  const { locale } = useI18n();

  const archiveMutation = useMutation({
    mutationFn: () => deleteClassroom(classroom.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classrooms"] });
      queryClient.invalidateQueries({ queryKey: ["teacher-dashboard"] });
      showToast(locale === "fr" ? "Classe archivée" : "Class archived", "success");
    },
  });

  const students = classroom.student_count || 0;
  const assignments = classroom.active_assignment_count || 0;

  return (
    <article
      className="card card-interactive teacher-classroom-card"
      onClick={() => onSelect(classroom.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(classroom.id);
        }
      }}
    >
      <div className="teacher-cls-head">
        <div className="flex min-w-0 items-center gap-3">
          <span className="runtime-mark flex-none">
            <GraduationCap size={18} />
          </span>
          <div className="min-w-0">
            <strong className="block truncate text-base">{classroom.name}</strong>
            <div className="muted truncate text-xs">
              {classroom.description || (locale === "fr" ? "Aucune description" : "No description")}
            </div>
          </div>
        </div>
        <div className="actions-row" onClick={(e) => e.stopPropagation()}>
          <Button onClick={() => onEdit(classroom)} aria-label={locale === "fr" ? "Modifier" : "Edit"}>
            <Edit2 size={16} />
          </Button>
          <ConfirmDialog
            destructive
            title={locale === "fr" ? "Archiver la classe" : "Archive class"}
            description={
              locale === "fr"
                ? `Archiver ${classroom.name} ? Elle sera masquée mais conservée.`
                : `Archive ${classroom.name}? It will be hidden but preserved.`
            }
            confirmLabel={locale === "fr" ? "Archiver" : "Archive"}
            trigger={
              <Button variant="danger" aria-label={locale === "fr" ? "Archiver" : "Archive"}>
                <Archive size={16} />
              </Button>
            }
            onConfirm={() => archiveMutation.mutate()}
          />
        </div>
      </div>

      <div className="mt-1 grid grid-cols-2 gap-4 border-t border-[var(--border)] pt-3">
        <div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
            <Users size={13} /> {locale === "fr" ? "Étudiants" : "Students"}
          </div>
          <strong className="text-xl">{students}</strong>
        </div>
        <div>
          <div className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
            <BookOpen size={13} /> {locale === "fr" ? "Devoirs actifs" : "Active work"}
          </div>
          <strong className="text-xl">{assignments}</strong>
        </div>
      </div>

      <div className="mt-1 flex items-center justify-between gap-3">
        <span className="muted text-xs">
          {classroom.created_at
            ? `${locale === "fr" ? "Créée" : "Created"} ${shortDate(classroom.created_at)}`
            : ""}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--primary)]">
          <Users size={14} /> {locale === "fr" ? "Gérer" : "Manage"}
        </span>
      </div>
    </article>
  );
}
