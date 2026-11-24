import { useMemo } from "react";
import { shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { StudentLabStatus } from "../../types/api";
import { Button, StatusBadge } from "../ui";
import { type ColumnDef, DataTable } from "../DataTable";
import { LAB_FILTERS, type LabFilter } from "./queries";

export type LabStatusRow = StudentLabStatus & { classroom_id?: number; classroom_name?: string };

/** Segmented filter (all / active / paused / without lab) with a count on each button. */
export function LabFilterButtons({
  value,
  counts,
  onChange,
}: {
  value: LabFilter;
  counts: Record<LabFilter, number>;
  onChange: (value: LabFilter) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="actions-row" role="group" aria-label={t("teacher.monitor_filter_label")}>
      {LAB_FILTERS.map((filter) => (
        <Button
          key={filter}
          variant={value === filter ? "primary" : "default"}
          aria-pressed={value === filter}
          onClick={() => onChange(filter)}
        >
          {t(`teacher.lab_filter_${filter}`)} ({counts[filter]})
        </Button>
      ))}
    </div>
  );
}

/** Sortable table of students and their current lab, shared by both monitoring views. */
export function LabStatusTable({
  rows,
  showClassroom = false,
  showEnrolledAt = false,
}: {
  rows: LabStatusRow[];
  showClassroom?: boolean;
  showEnrolledAt?: boolean;
}) {
  const { t } = useI18n();

  const columns = useMemo<ColumnDef<LabStatusRow>[]>(() => {
    const cols: ColumnDef<LabStatusRow>[] = [];
    if (showClassroom) {
      cols.push({ id: "classroom", header: t("teacher.col_classroom"), accessorFn: (r) => r.classroom_name ?? "" });
    }
    cols.push(
      {
        id: "student",
        header: t("overview.student"),
        accessorFn: (r) => r.username || `#${r.user_id}`,
      },
      {
        id: "lab",
        header: t("teacher.col_lab"),
        accessorFn: (r) => r.lab_name ?? "",
        cell: ({ row }) => row.original.lab_name || <span className="muted">{t("students.lab_none")}</span>,
      },
      {
        id: "status",
        header: t("submission.status"),
        accessorFn: (r) => r.lab_status || "none",
        cell: ({ row }) => <StatusBadge state={row.original.lab_status || "none"} />,
      },
      {
        id: "expires",
        header: t("teacher.col_expires"),
        accessorFn: (r) => r.lab_expires_at ?? "",
        cell: ({ row }) => (row.original.lab_expires_at ? shortDate(row.original.lab_expires_at) : "—"),
      },
    );
    if (showEnrolledAt) {
      cols.push({
        id: "enrolled",
        header: t("teacher.col_enrolled_at"),
        accessorFn: (r) => r.enrolled_at ?? "",
        cell: ({ row }) => shortDate(row.original.enrolled_at),
      });
    }
    return cols;
  }, [showClassroom, showEnrolledAt, t]);

  return (
    <DataTable
      data={rows}
      columns={columns}
      getRowId={(r) => `${r.classroom_id ?? ""}-${r.user_id}`}
      label={t("teacher.monitor_table_label")}
    />
  );
}
