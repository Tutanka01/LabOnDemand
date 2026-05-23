import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, Edit2, GraduationCap, Plus, Trash2, Users } from "lucide-react";
import type { Classroom } from "../../types/api";
import { deleteClassroom } from "../../lib/api";
import { colorForId, shortDate } from "../../lib/format";
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
  const color = colorForId(classroom.id);

  const archiveMutation = useMutation({
    mutationFn: () => deleteClassroom(classroom.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classrooms"] });
      showToast("Classe archivee", "success");
    },
  });

  return (
    <article className="card teacher-classroom-card" style={{ borderLeft: `4px solid ${color}` }}>
      <div className="teacher-cls-head">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="runtime-mark" style={{ background: `${color}18`, color }}>
            <GraduationCap size={18} />
          </span>
          <div>
            <strong>{classroom.name}</strong>
            <div className="muted" style={{ fontSize: "0.83rem" }}>
              {classroom.description || "Aucune description"}
            </div>
          </div>
        </div>
        <div className="actions-row">
          <Button onClick={() => onSelect(classroom.id)}>
            <Users size={16} /> Gerer
          </Button>
          <Button onClick={() => onEdit(classroom)}>
            <Edit2 size={16} />
          </Button>
          <ConfirmDialog
            destructive
            title="Archiver la classe"
            description={`Archiver ${classroom.name} ? Elle sera masquee mais conservee.`}
            confirmLabel="Archiver"
            trigger={<Button variant="danger"><Archive size={16} /></Button>}
            onConfirm={() => archiveMutation.mutate()}
          />
        </div>
      </div>
      <div className="lab-meta" style={{ marginTop: 10 }}>
        <span className="badge">{classroom.student_count || 0} etudiants</span>
        <span className="badge">{classroom.active_assignment_count || 0} devoirs</span>
        {classroom.created_at ? <span className="badge">Cree {shortDate(classroom.created_at)}</span> : null}
      </div>
    </article>
  );
}
