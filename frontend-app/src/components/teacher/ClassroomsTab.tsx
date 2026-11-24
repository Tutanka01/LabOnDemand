import type { UseQueryResult } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import type { Classroom } from "../../types/api";
import { Button, EmptyState, QueryState, SkeletonCards } from "../ui";
import { ClassroomCard } from "./ClassroomCard";

/** Grid of the teacher's classrooms. */
export function ClassroomsTab({
  classrooms,
  onCreate,
  onEdit,
  onSelect,
}: {
  classrooms: UseQueryResult<Classroom[]>;
  onCreate: () => void;
  onEdit: (classroom: Classroom) => void;
  onSelect: (classroomId: number) => void;
}) {
  const { t } = useI18n();
  const items = classrooms.data || [];

  return (
    <QueryState
      query={classrooms}
      skeleton={<SkeletonCards count={4} lines={2} />}
      errorTitle={t("teacher.error_classrooms")}
      isEmpty={items.length === 0}
      empty={
        <EmptyState
          title={t("classroom.empty")}
          action={
            <Button variant="primary" onClick={onCreate}>
              <Plus size={16} aria-hidden="true" /> {t("classroom.new")}
            </Button>
          }
        >
          {t("classroom.empty_hint")}
        </EmptyState>
      }
    >
      <section className="grid-teacher">
        {items.map((classroom) => (
          <ClassroomCard key={classroom.id} classroom={classroom} onEdit={onEdit} onSelect={onSelect} />
        ))}
      </section>
    </QueryState>
  );
}
