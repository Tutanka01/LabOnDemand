import { useQuery } from "@tanstack/react-query";
import { BookOpen, GraduationCap, Plus, Users } from "lucide-react";
import { useMemo } from "react";
import { getTeacherDashboard } from "../../lib/api";
import { shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { TeacherDashboard } from "../../types/api";
import { Button, EmptyState, MetricCard, QueryState, SkeletonCards } from "../ui";
import { type ColumnDef, DataTable } from "../DataTable";

type DashboardClassroom = NonNullable<TeacherDashboard["classrooms"]>[number];

/** Totals across the teacher's classrooms plus a sortable summary table. */
export function TeacherOverviewTab({ onCreateClassroom }: { onCreateClassroom: () => void }) {
  const { t } = useI18n();
  // Counts only change through the teacher's own actions, which invalidate this query: no polling.
  const dashboard = useQuery({ queryKey: ["teacher-dashboard"], queryFn: getTeacherDashboard });

  const classrooms = dashboard.data?.classrooms || [];
  const totalStudents = classrooms.reduce((sum, classroom) => sum + classroom.student_count, 0);
  const totalAssignments = classrooms.reduce((sum, classroom) => sum + classroom.active_assignment_count, 0);

  const columns = useMemo<ColumnDef<DashboardClassroom>[]>(
    () => [
      { id: "name", header: t("teacher.col_classroom"), accessorFn: (c) => c.name },
      { id: "students", header: t("students.title"), accessorFn: (c) => c.student_count },
      { id: "assignments", header: t("teacher.active_assignments"), accessorFn: (c) => c.active_assignment_count },
      {
        id: "created",
        header: t("teacher.col_created_at"),
        accessorFn: (c) => c.created_at ?? "",
        cell: ({ row }) => shortDate(row.original.created_at),
      },
    ],
    [t],
  );

  return (
    <QueryState
      query={dashboard}
      skeleton={<SkeletonCards count={3} lines={2} />}
      errorTitle={t("teacher.error_overview")}
    >
      <div className="grid gap-4">
        <section className="metric-grid grid-cols-3">
          <MetricCard
            label={t("classroom.title")}
            value={dashboard.data?.classroom_count || 0}
            icon={<GraduationCap size={18} />}
            hint={t("teacher.metric_managed_classes")}
          />
          <MetricCard
            label={t("students.title")}
            value={totalStudents}
            icon={<Users size={18} />}
            hint={t("teacher.metric_total_enrolled")}
          />
          <MetricCard
            label={t("teacher.active_assignments")}
            value={totalAssignments}
            icon={<BookOpen size={18} />}
            hint={t("teacher.metric_all_classes")}
          />
        </section>

        <section className="panel">
          <div className="section-head">
            <h2>{t("teacher.recent_classes")}</h2>
          </div>
          {classrooms.length ? (
            <DataTable data={classrooms} columns={columns} getRowId={(c) => String(c.id)} label={t("teacher.recent_classes")} />
          ) : (
            <EmptyState
              title={t("classroom.empty")}
              action={
                <Button variant="primary" onClick={onCreateClassroom}>
                  <Plus size={16} aria-hidden="true" /> {t("classroom.new")}
                </Button>
              }
            >
              {t("teacher.overview_empty_hint")}
            </EmptyState>
          )}
        </section>
      </div>
    </QueryState>
  );
}
