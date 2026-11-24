import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  deployAllAssignments,
  getAssignments,
  getClassroomLabStatus,
  getClassroomStudents,
} from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { BulkSpawnReport, StudentLabStatus } from "../../types/api";
import { errorMessage, showToast } from "../ui";

/**
 * Student labs change in the background (students start, pause, expire them), so the
 * monitoring views poll. TanStack Query pauses interval refetches while the tab is hidden
 * (`refetchIntervalInBackground` defaults to false).
 */
export const LAB_STATUS_POLL_MS = 30_000;

export function useClassroomStudents(classroomId: number) {
  return useQuery({
    queryKey: ["classroom-students", classroomId],
    queryFn: () => getClassroomStudents(classroomId),
  });
}

export function useClassroomAssignments(classroomId: number) {
  return useQuery({
    queryKey: ["assignments", classroomId],
    queryFn: () => getAssignments(classroomId),
  });
}

export function useClassroomLabStatus(classroomId: number, enabled = true) {
  return useQuery({
    queryKey: ["lab-status", classroomId],
    queryFn: () => getClassroomLabStatus(classroomId),
    enabled,
    refetchInterval: LAB_STATUS_POLL_MS,
  });
}

/** Invalidates every query that shows classroom membership or counts. */
export function useInvalidateClassroom() {
  const queryClient = useQueryClient();
  return (classroomId?: number) => {
    if (classroomId !== undefined) {
      queryClient.invalidateQueries({ queryKey: ["classroom-students", classroomId] });
      queryClient.invalidateQueries({ queryKey: ["lab-status", classroomId] });
      queryClient.invalidateQueries({ queryKey: ["assignments", classroomId] });
    }
    queryClient.invalidateQueries({ queryKey: ["classrooms"] });
    queryClient.invalidateQueries({ queryKey: ["teacher-dashboard"] });
  };
}

// ─── Lab status filtering ────────────────────────────────────────────────────

export type LabFilter = "all" | "active" | "paused" | "none";

export const LAB_FILTERS: LabFilter[] = ["all", "active", "paused", "none"];

export function matchesLabFilter(row: Pick<StudentLabStatus, "lab_status">, filter: LabFilter): boolean {
  if (filter === "all") return true;
  if (filter === "none") return !row.lab_status || row.lab_status === "none";
  return row.lab_status === filter;
}

export function countByLabFilter(rows: Array<Pick<StudentLabStatus, "lab_status">>): Record<LabFilter, number> {
  return {
    all: rows.length,
    active: rows.filter((r) => matchesLabFilter(r, "active")).length,
    paused: rows.filter((r) => matchesLabFilter(r, "paused")).length,
    none: rows.filter((r) => matchesLabFilter(r, "none")).length,
  };
}

// ─── Bulk distribution of an assignment ──────────────────────────────────────

export type DistributionState = { assignmentId: number; report: BulkSpawnReport | null };

/**
 * Distributes an assignment to the whole class. Kept above the tabs so the report
 * survives switching tabs while the request runs.
 */
export function useDistributeAssignment(classroomId: number) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [state, setState] = useState<DistributionState | null>(null);

  const mutation = useMutation({
    mutationFn: (assignmentId: number) => deployAllAssignments(classroomId, assignmentId),
    onMutate: (assignmentId) => setState({ assignmentId, report: null }),
    onSuccess: (report, assignmentId) => {
      setState({ assignmentId, report });
      queryClient.invalidateQueries({ queryKey: ["lab-status", classroomId] });
      queryClient.invalidateQueries({ queryKey: ["deployments"] });
      queryClient.invalidateQueries({ queryKey: ["quotas"] });
      showToast(
        t("teacher.toast_distribution_done", { ok: report.ok, errors: report.errors }),
        report.errors > 0 ? "error" : "success",
      );
    },
    onError: (error) => {
      setState(null);
      showToast(errorMessage(error, t("teacher.error_distribution")), "error");
    },
  });

  return {
    state,
    isPending: mutation.isPending,
    distribute: (assignmentId: number) => mutation.mutate(assignmentId),
    dismiss: () => setState(null),
  };
}

export type AssignmentDistribution = ReturnType<typeof useDistributeAssignment>;
