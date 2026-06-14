import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, BookOpen, Edit2, GraduationCap, Users } from "lucide-react";
import type { Classroom } from "../../types/api";
import { deleteClassroom } from "../../lib/api";
import { colorForId, shortDate } from "../../lib/format";
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
  const color = colorForId(classroom.id);

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
      className="card card-interactive teacher-classroom-card relative overflow-hidden"
      style={{ borderLeft: `4px solid ${color}` }}
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
      {/* Halo tinté en arrière-plan */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-10 -top-12 h-32 w-32 rounded-full opacity-60 blur-2xl"
        style={{ background: `${color}22` }}
      />

      <div className="teacher-cls-head relative">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="runtime-mark h-11 w-11 flex-none"
            style={{ background: `${color}1f`, color, borderColor: `${color}40` }}
          >
            <GraduationCap size={20} />
          </span>
          <div className="min-w-0">
            <strong className="block truncate text-[1.02rem]">{classroom.name}</strong>
            <div className="muted truncate text-[0.83rem]">
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

      <div className="relative mt-1 grid grid-cols-2 gap-2.5">
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-[0.74rem] font-medium uppercase tracking-wide text-[var(--muted)]">
            <Users size={13} /> {locale === "fr" ? "Étudiants" : "Students"}
          </div>
          <strong className="text-[1.35rem] leading-none" style={{ fontFamily: "var(--font-display)" }}>
            {students}
          </strong>
        </div>
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-[0.74rem] font-medium uppercase tracking-wide text-[var(--muted)]">
            <BookOpen size={13} /> {locale === "fr" ? "Devoirs actifs" : "Active work"}
          </div>
          <strong className="text-[1.35rem] leading-none" style={{ fontFamily: "var(--font-display)" }}>
            {assignments}
          </strong>
        </div>
      </div>

      <div className="relative mt-1 flex items-center justify-between gap-3">
        <span className="muted text-[0.78rem]">
          {classroom.created_at
            ? `${locale === "fr" ? "Créée" : "Created"} ${shortDate(classroom.created_at)}`
            : ""}
        </span>
        <span className="inline-flex items-center gap-1.5 text-[0.82rem] font-semibold text-[var(--primary)]">
          <Users size={14} /> {locale === "fr" ? "Gérer" : "Manage"}
        </span>
      </div>
    </article>
  );
}
