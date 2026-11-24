import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../lib/i18n";
import { Button, EmptyState, QueryState, SkeletonRows } from "../ui";
import { LabFilterButtons, LabStatusTable } from "./LabStatusTable";
import { countByLabFilter, type LabFilter, matchesLabFilter, useClassroomLabStatus } from "./queries";

/** Lab status of every student of one classroom (polled). */
export function ClassroomMonitorTab({ classroomId }: { classroomId: number }) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<LabFilter>("all");
  const labStatus = useClassroomLabStatus(classroomId);

  const rows = labStatus.data || [];
  const filtered = rows.filter((row) => matchesLabFilter(row, filter));

  return (
    <section className="panel">
      <div className="section-head">
        <LabFilterButtons value={filter} counts={countByLabFilter(rows)} onChange={setFilter} />
        <Button
          onClick={() => void labStatus.refetch()}
          disabled={labStatus.isFetching}
          aria-label={t("common.refresh")}
          title={t("teacher.auto_refresh_hint")}
        >
          <RefreshCw size={16} className={labStatus.isFetching ? "animate-spin" : undefined} aria-hidden="true" />
        </Button>
      </div>
      <QueryState
        query={labStatus}
        skeleton={<SkeletonRows rows={6} cols={5} />}
        errorTitle={t("teacher.error_monitor")}
        isEmpty={filtered.length === 0}
        empty={
          rows.length === 0 ? (
            <EmptyState title={t("students.empty")}>{t("teacher.students_empty_hint")}</EmptyState>
          ) : (
            <EmptyState title={t("teacher.monitor_no_match")}>{t("teacher.monitor_no_match_hint")}</EmptyState>
          )
        }
      >
        <LabStatusTable rows={filtered} showEnrolledAt />
      </QueryState>
    </section>
  );
}
