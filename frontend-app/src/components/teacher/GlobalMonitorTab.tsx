import { useQueries } from "@tanstack/react-query";
import { Archive, CheckCircle2, XCircle } from "lucide-react";
import { useState } from "react";
import { getClassroomLabStatus } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { Classroom } from "../../types/api";
import { EmptyState, ErrorState, MetricCard, SkeletonRows } from "../ui";
import { LabFilterButtons, type LabStatusRow, LabStatusTable } from "./LabStatusTable";
import { countByLabFilter, LAB_STATUS_POLL_MS, type LabFilter, matchesLabFilter } from "./queries";

/** Lab status across all active classrooms of the teacher (one polled query per classroom). */
export function GlobalMonitorTab({ classrooms }: { classrooms: Classroom[] }) {
  const { t } = useI18n();
  const [classroomFilter, setClassroomFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<LabFilter>("all");
  const activeClassrooms = classrooms.filter((classroom) => !classroom.archived);

  const statusQueries = useQueries({
    queries: activeClassrooms.map((classroom) => ({
      queryKey: ["lab-status", classroom.id],
      queryFn: () => getClassroomLabStatus(classroom.id),
      refetchInterval: LAB_STATUS_POLL_MS,
    })),
  });

  const rows: LabStatusRow[] = activeClassrooms.flatMap((classroom, index) =>
    (statusQueries[index]?.data || []).map((status) => ({
      ...status,
      classroom_id: classroom.id,
      classroom_name: classroom.name,
    })),
  );
  const inClassroom = rows.filter((row) => !classroomFilter || String(row.classroom_id) === classroomFilter);
  const filtered = inClassroom.filter((row) => matchesLabFilter(row, statusFilter));
  const summary = countByLabFilter(rows);

  const isLoading = statusQueries.some((query) => query.isLoading);
  const failed = statusQueries
    .map((query, index) => ({ query, classroom: activeClassrooms[index] }))
    .filter(({ query }) => query.error);
  const retryFailed = () => failed.forEach(({ query }) => void query.refetch());

  return (
    <section className="panel">
      <div className="section-head">
        <h2>{t("teacher.global_monitor_title")}</h2>
        <span className="badge" title={t("teacher.auto_refresh_hint")}>
          {t("teacher.auto_refresh")}
        </span>
      </div>

      <section className="metric-grid grid-cols-3 mb-4">
        <MetricCard
          label={t("teacher.lab_filter_active")}
          value={summary.active}
          icon={<CheckCircle2 size={18} />}
          hint={t("teacher.metric_running_labs")}
        />
        <MetricCard
          label={t("teacher.lab_filter_paused")}
          value={summary.paused}
          icon={<Archive size={18} />}
          hint={t("teacher.metric_suspended")}
        />
        <MetricCard
          label={t("teacher.lab_filter_none")}
          value={summary.none}
          icon={<XCircle size={18} />}
          hint={t("teacher.metric_to_deploy")}
        />
      </section>

      <div className="actions-row mb-3">
        <select
          className="control"
          value={classroomFilter}
          onChange={(e) => setClassroomFilter(e.target.value)}
          aria-label={t("overview.filter_class")}
        >
          <option value="">{t("overview.all_classes")}</option>
          {activeClassrooms.map((classroom) => (
            <option value={classroom.id} key={classroom.id}>
              {classroom.name}
            </option>
          ))}
        </select>
        <LabFilterButtons value={statusFilter} counts={countByLabFilter(inClassroom)} onChange={setStatusFilter} />
      </div>

      {failed.length > 0 ? (
        <ErrorState
          title={t("teacher.error_monitor_partial", { names: failed.map(({ classroom }) => classroom.name).join(", ") })}
          error={failed[0].query.error}
          onRetry={retryFailed}
          retrying={failed.some(({ query }) => query.isFetching)}
        />
      ) : null}

      {isLoading ? (
        <SkeletonRows rows={5} cols={5} />
      ) : activeClassrooms.length === 0 ? (
        <EmptyState title={t("classroom.empty")}>{t("classroom.empty_hint")}</EmptyState>
      ) : filtered.length ? (
        <LabStatusTable rows={filtered} showClassroom />
      ) : rows.length === 0 && failed.length === 0 ? (
        <EmptyState title={t("teacher.monitor_no_students")}>{t("teacher.students_empty_hint")}</EmptyState>
      ) : failed.length === 0 || rows.length > 0 ? (
        <EmptyState title={t("teacher.monitor_no_match")}>{t("teacher.monitor_no_match_hint")}</EmptyState>
      ) : null}
    </section>
  );
}
