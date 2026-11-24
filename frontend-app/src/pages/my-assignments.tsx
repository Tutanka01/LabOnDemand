import { useQuery } from "@tanstack/react-query";
import { BookOpen, CalendarClock, ChevronRight, FlaskConical } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../components/AppShell";
import { Badge, EmptyState, SkeletonCards } from "../components/ui";
import { QueryProblem } from "../components/dashboard/QueryProblem";
import { getStudentAssignments } from "../lib/api";
import { type FormatLocale, fullDate, unitAmount } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { StudentAssignmentItem } from "../types/api";

function isPastDue(due?: string | null): boolean {
  if (!due) return false;
  return new Date(due).getTime() < Date.now();
}

type Translate = (key: string, replacements?: Record<string, string | number>) => string;

/** Relative due-date emphasis ("in 2 days" / overdue) for the to-do cards. */
function dueProximity(
  due: string | null | undefined,
  locale: FormatLocale,
  t: Translate,
): { label: string; tone: "urgent" | "soon" | "calm" } | null {
  if (!due) return null;
  const ms = new Date(due).getTime() - Date.now();
  if (Number.isNaN(ms)) return null;
  if (ms < 0) {
    const overdue = Math.floor(Math.abs(ms) / 86_400_000);
    return {
      tone: "urgent",
      label: overdue > 0 ? t("assignments.overdue_by", { duration: unitAmount(overdue, "day", locale) }) : t("assignments.overdue"),
    };
  }
  const days = Math.round(ms / 86_400_000);
  if (days === 0) return { tone: "urgent", label: t("assignments.due_today") };
  if (days === 1) return { tone: "soon", label: t("assignments.due_tomorrow") };
  return { tone: days <= 3 ? "soon" : "calm", label: t("assignments.due_in", { duration: unitAmount(days, "day", locale) }) };
}

function labLabel(item: StudentAssignmentItem, t: Translate): string {
  if (item.lab_ready) return t("myassignments.lab_ready");
  if (item.lab_status === "paused") return t("assignments.lab_paused");
  return t("myassignments.lab_not_ready");
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

function AssignmentCard({ item }: { item: StudentAssignmentItem }) {
  const { t, locale } = useI18n();
  // Due-date urgency is only meaningful while the work is still open.
  const proximity =
    item.submission_status === "not_started" ? dueProximity(item.due_at, locale, t) : null;
  const proximityColor =
    proximity?.tone === "urgent"
      ? "var(--danger)"
      : proximity?.tone === "soon"
        ? "var(--warning)"
        : "var(--muted)";

  return (
    <Link to={`/assignments/${item.id}`} className="assignment-card">
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
                  <span className="muted" style={{ fontWeight: 400 }}>· {fullDate(item.due_at, locale)}</span>
                </span>
              ) : (
                `${t("myassignments.due")} ${fullDate(item.due_at, locale)}`
              )
            ) : (
              t("myassignments.no_due")
            )}
          </span>
          <span style={{ color: item.lab_ready ? "var(--primary)" : undefined }}>
            <FlaskConical size={15} aria-hidden="true" />
            {labLabel(item, t)}
          </span>
          {item.grade ? (
            <span>
              <BookOpen size={15} />
              {t("submission.grade")}: <strong>{item.grade}</strong>
            </span>
          ) : null}
        </div>

        <div className="assignment-card-footer">
          <span className="btn">
            {item.submission_status === "graded"
              ? t("myassignments.view_feedback")
              : item.submission_status === "submitted"
                ? t("myassignments.view")
                : t("myassignments.open")}
            <ChevronRight size={15} />
          </span>
        </div>
      </Link>
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
      {assignments.error ? (
        <QueryProblem
          error={assignments.error}
          title={t("assignments.load_error")}
          onRetry={() => void assignments.refetch()}
          retrying={assignments.isFetching}
          stale={Boolean(assignments.data)}
        />
      ) : null}

      {assignments.data && assignments.data.length === 0 ? (
        <EmptyState title={t("myassignments.empty")}>{t("myassignments.empty_hint")}</EmptyState>
      ) : null}

      {(["todo", "submitted", "graded"] as const).map((key) =>
        groups[key].length > 0 ? (
          <section className="assignment-group" key={key}>
            <h2 className="assignment-group-title">
              {t(`myassignments.group_${key}`)}
              <span className="count-chip">{groups[key].length}</span>
            </h2>
            <div className="assignment-grid">
              {groups[key].map((item) => (
                <AssignmentCard key={item.id} item={item} />
              ))}
            </div>
          </section>
        ) : null,
      )}
    </>
  );
}
