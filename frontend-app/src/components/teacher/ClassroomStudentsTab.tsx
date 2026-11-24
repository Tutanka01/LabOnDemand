import { useMutation } from "@tanstack/react-query";
import { Plus, UserMinus } from "lucide-react";
import { useMemo, useState } from "react";
import { unenrollStudent } from "../../lib/api";
import { shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { StudentLabStatus } from "../../types/api";
import { Button, ConfirmDialog, EmptyState, errorMessage, QueryState, SearchBox, showToast, SkeletonRows } from "../ui";
import { type ColumnDef, DataTable } from "../DataTable";
import { useClassroomStudents, useInvalidateClassroom } from "./queries";

/** Enrolled students of a classroom, with search, sorting and unenrolment. */
export function ClassroomStudentsTab({ classroomId, onAdd }: { classroomId: number; onAdd: () => void }) {
  const { t } = useI18n();
  const students = useClassroomStudents(classroomId);
  const invalidateClassroom = useInvalidateClassroom();
  const [search, setSearch] = useState("");

  const unenroll = useMutation({
    mutationFn: (userId: number) => unenrollStudent(classroomId, userId),
    onSuccess: () => {
      invalidateClassroom(classroomId);
      showToast(t("teacher.toast_unenrolled"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("teacher.error_unenroll")), "error"),
  });

  const columns = useMemo<ColumnDef<StudentLabStatus>[]>(
    () => [
      { id: "username", header: t("students.username"), accessorFn: (s) => s.username || `#${s.user_id}` },
      {
        id: "email",
        header: t("students.email"),
        accessorFn: (s) => s.email ?? "",
        cell: ({ row }) => row.original.email || <span className="muted">—</span>,
      },
      {
        id: "enrolled",
        header: t("teacher.col_enrolled_at"),
        accessorFn: (s) => s.enrolled_at ?? "",
        cell: ({ row }) => shortDate(row.original.enrolled_at),
      },
      {
        id: "actions",
        header: t("students.actions"),
        enableSorting: false,
        cell: ({ row }) => {
          const s = row.original;
          const name = s.username || `#${s.user_id}`;
          const pending = unenroll.isPending && unenroll.variables === s.user_id;
          return (
            <ConfirmDialog
              destructive
              title={t("students.unenroll")}
              description={t("teacher.unenroll_body", { name })}
              confirmLabel={t("students.unenroll")}
              trigger={
                <Button
                  variant="danger"
                  disabled={pending}
                  aria-label={t("teacher.unenroll_named", { name })}
                  title={t("students.unenroll")}
                >
                  <UserMinus size={14} aria-hidden="true" />
                </Button>
              }
              onConfirm={() => unenroll.mutate(s.user_id)}
            />
          );
        },
      },
    ],
    [t, unenroll],
  );

  const items = students.data || [];
  const q = search.trim().toLowerCase();
  const filtered = q
    ? items.filter((s) => `${s.username || ""} ${s.email || ""}`.toLowerCase().includes(q))
    : items;

  return (
    <section className="panel">
      <div className="section-head">
        <h2>{t("teacher.enrolled_students")}</h2>
        <Button variant="primary" onClick={onAdd}>
          <Plus size={16} aria-hidden="true" /> {t("students.add")}
        </Button>
      </div>
      <QueryState
        query={students}
        skeleton={<SkeletonRows rows={6} cols={4} />}
        errorTitle={t("teacher.error_students")}
        isEmpty={items.length === 0}
        empty={
          <EmptyState
            title={t("students.empty")}
            action={
              <Button variant="primary" onClick={onAdd}>
                <Plus size={16} aria-hidden="true" /> {t("students.add")}
              </Button>
            }
          >
            {t("teacher.students_empty_hint")}
          </EmptyState>
        }
      >
        <div className="actions-row mb-3">
          <SearchBox placeholder={t("students.search_label")} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {filtered.length ? (
          <DataTable data={filtered} columns={columns} getRowId={(s) => String(s.user_id)} label={t("teacher.enrolled_students")} />
        ) : (
          <EmptyState title={t("teacher.search_no_match")} />
        )}
      </QueryState>
    </section>
  );
}
