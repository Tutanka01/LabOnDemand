import { useQuery } from "@tanstack/react-query";
import { BookOpen, CalendarClock, ChevronRight, FlaskConical } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { PageHeader } from "../components/AppShell";
import { Badge, EmptyState, ErrorState, SkeletonCards } from "../components/ui";
import { getStudentAssignments } from "../lib/api";
import { fullDate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { StudentAssignmentItem } from "../types/api";

function isPastDue(due?: string | null): boolean {
  if (!due) return false;
  return new Date(due).getTime() < Date.now();
}

/** Relative due-date emphasis ("dans 2 j" / overdue) for the to-do cards. */
function dueProximity(
  due: string | null | undefined,
  locale: string,
): { label: string; tone: "urgent" | "soon" | "calm" } | null {
  if (!due) return null;
  const ms = new Date(due).getTime() - Date.now();
  const days = Math.round(ms / 86_400_000);
  if (ms < 0) {
    const overdue = Math.abs(days);
    return {
      tone: "urgent",
      label: locale === "fr" ? `En retard de ${overdue} j` : `${overdue}d overdue`,
    };
  }
  if (days === 0) return { tone: "urgent", label: locale === "fr" ? "Aujourd'hui" : "Due today" };
  if (days === 1) return { tone: "soon", label: locale === "fr" ? "Demain" : "Tomorrow" };
  const tone = days <= 3 ? "soon" : "calm";
  return { tone, label: locale === "fr" ? `Dans ${days} j` : `In ${days}d` };
}

function cardTone(item: StudentAssignmentItem): string {
  if (item.submission_status === "graded") return "tone-graded";
  if (item.submission_status === "submitted") return item.is_late ? "tone-late" : "tone-submitted";
  if (isPastDue(item.due_at)) return "tone-overdue";
  return "tone-todo";
}

function StatusBadge({ item }: { item: StudentAssignmentItem }) {
  const { t } = useI18n();
  if (item.submission_status === "graded") return <Badge tone="green">{t("myassignments.status_graded")}</Badge>;
  if (item.submission_status === "submitted")
    return item.is_late ? (
      <Badge tone="amber">{t("myassignments.status_late")}</Badge>
    ) : (
      <Badge tone="blue">{t("myassignments.status_submitted")}</Badge>
    );
  if (isPastDue(item.due_at)) return <Badge tone="red">{t("myassignments.status_overdue")}</Badge>;
  return <Badge>{t("myassignments.status_not_started")}</Badge>;
}

function AssignmentCard({ item, index }: { item: StudentAssignmentItem; index: number }) {
  const { t, locale } = useI18n();
  // Due-date urgency is only meaningful while the work is still open.
  const proximity =
    item.submission_status === "not_started" ? dueProximity(item.due_at, locale) : null;
  const proximityColor =
    proximity?.tone === "urgent"
      ? "var(--danger)"
      : proximity?.tone === "soon"
        ? "var(--warning)"
        : "var(--muted)";

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, delay: Math.min(index, 8) * 0.05, ease: [0.22, 1, 0.36, 1] }}
    >
      <Link to={`/assignments/${item.id}`} className={`assignment-card ${cardTone(item)}`}>
        <div className="assignment-card-head">
          <div className="flex flex-col gap-1 min-w-0">
            <span className="assignment-card-title">{item.title}</span>
            {item.classroom_name ? <span className="muted text-sm">{item.classroom_name}</span> : null}
          </div>
          <StatusBadge item={item} />
        </div>

        <div className="assignment-card-meta">
          <span style={proximity ? { color: proximityColor, fontWeight: 600 } : undefined}>
            <CalendarClock size={15} />
            {item.due_at ? (
              proximity ? (
                <span className="inline-flex items-baseline gap-1">
                  {proximity.label}
                  <span className="muted" style={{ fontWeight: 400 }}>· {fullDate(item.due_at)}</span>
                </span>
              ) : (
                `${t("myassignments.due")} ${fullDate(item.due_at)}`
              )
            ) : (
              t("myassignments.no_due")
            )}
          </span>
          <span style={{ color: item.lab_ready ? "var(--primary)" : undefined }}>
            <FlaskConical size={15} />
            {item.lab_ready ? t("myassignments.lab_ready") : t("myassignments.lab_not_ready")}
          </span>
          {item.grade ? (
            <span>
              <BookOpen size={15} />
              {t("submission.grade")}: <strong>{item.grade}</strong>
            </span>
          ) : null}
        </div>

        <div className="assignment-card-footer">
          <span className="btn primary inline-flex items-center gap-1">
            {item.submission_status === "graded"
              ? t("myassignments.view_feedback")
              : item.submission_status === "submitted"
                ? t("myassignments.view")
                : t("myassignments.open")}
            <ChevronRight size={16} />
          </span>
        </div>
      </Link>
    </motion.div>
  );
}

export default function MyAssignmentsPage() {
  const { t } = useI18n();
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: getStudentAssignments });

  const groups = useMemo(() => {
    const items = assignments.data || [];
    return {
      todo: items.filter((a) => a.submission_status === "not_started"),
      submitted: items.filter((a) => a.submission_status === "submitted"),
      graded: items.filter((a) => a.submission_status === "graded"),
    };
  }, [assignments.data]);

  return (
    <>
      <PageHeader title={t("myassignments.title")} subtitle={t("myassignments.subtitle")} />

      {assignments.isLoading ? (
        <div className="assignment-grid">
          <SkeletonCards count={6} lines={3} />
        </div>
      ) : null}
      {assignments.error ? <ErrorState>{(assignments.error as Error).message}</ErrorState> : null}

      {!assignments.isLoading && !assignments.error && (assignments.data?.length || 0) === 0 ? (
        <EmptyState title={t("myassignments.empty")}>{t("myassignments.empty_hint")}</EmptyState>
      ) : null}

      {(["todo", "submitted", "graded"] as const).map((key, gi) =>
        groups[key].length > 0 ? (
          <section className="assignment-group" key={key}>
            <h2 className="assignment-group-title">
              {t(`myassignments.group_${key}`)}
              <span className="count-chip">{groups[key].length}</span>
            </h2>
            <div className="assignment-grid">
              {groups[key].map((item, i) => (
                <AssignmentCard key={item.id} item={item} index={gi * 2 + i} />
              ))}
            </div>
          </section>
        ) : null,
      )}
    </>
  );
}
