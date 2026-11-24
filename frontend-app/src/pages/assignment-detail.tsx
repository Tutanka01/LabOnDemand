import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, FlaskConical, Loader2, PlayCircle, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../components/AppShell";
import {
  Badge,
  Button,
  LoadingState,
  StatusBadge,
  showToast,
} from "../components/ui";
import { LabStatusBadge } from "../components/dashboard/LabStatusBadge";
import { QueryProblem } from "../components/dashboard/QueryProblem";
import { canOpen, openLabViaDetails, useDeployments } from "../hooks/useDeployments";
import { GradingResultList, RunSummary } from "../components/GradingResults";
import {
  getGradingRun,
  getStudentAssignment,
  runTestsStudent,
  submitAssignment,
} from "../lib/api";
import { fullDate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { Markdown } from "../components/Markdown";
import type { GradingRun, SubmissionLink } from "../types/api";

interface LinkRow {
  label: string;
  url: string;
}

export default function AssignmentDetailPage() {
  const { aid } = useParams();
  const assignmentId = Number(aid);
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  // The live lab list gives the real readiness and the URL to open, and refreshes while it changes.
  const labsState = useDeployments();
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: ["student-assignment", assignmentId],
    queryFn: () => getStudentAssignment(assignmentId),
    enabled: Number.isFinite(assignmentId),
  });

  const [text, setText] = useState("");
  const [links, setLinks] = useState<LinkRow[]>([]);
  const [opening, setOpening] = useState(false);

  // Pré-remplir le formulaire avec la dernière soumission.
  useEffect(() => {
    const sub = detail.data?.submission;
    if (sub) {
      setText(sub.text || "");
      setLinks(
        (sub.links || []).map((l: SubmissionLink) => ({ label: l.label || "", url: l.url })),
      );
    }
  }, [detail.data?.submission]);

  const submitMut = useMutation({
    mutationFn: () =>
      submitAssignment(assignmentId, {
        text: text.trim() || undefined,
        links: links
          .filter((l) => l.url.trim())
          .map((l) => ({ label: l.label.trim() || undefined, url: l.url.trim() })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["student-assignment", assignmentId] });
      queryClient.invalidateQueries({ queryKey: ["my-assignments"] });
      showToast(t("submission.submitted_ok"), "success");
    },
    onError: (e) => showToast((e as Error).message, "error"),
  });

  // ── Tests boîte noire (self-check) ──────────────────────────────────────
  const [activeRunId, setActiveRunId] = useState<number | null>(null);

  // Reprendre le suivi du dernier run au chargement (ex: run encore en cours).
  useEffect(() => {
    const latest = detail.data?.latest_run;
    if (latest && activeRunId === null) setActiveRunId(latest.id);
  }, [detail.data?.latest_run, activeRunId]);

  const runQuery = useQuery({
    queryKey: ["grading-run", assignmentId, activeRunId],
    queryFn: () => getGradingRun(assignmentId, activeRunId as number),
    enabled: activeRunId !== null,
    refetchInterval: (query) => {
      const s = (query.state.data as GradingRun | undefined)?.status;
      return s === "queued" || s === "running" ? 1500 : false;
    },
  });

  // Rafraîchir la fiche (latest_run, statut) quand un run se termine.
  const runStatus = runQuery.data?.status;
  useEffect(() => {
    if (runStatus === "done" || runStatus === "error") {
      queryClient.invalidateQueries({ queryKey: ["my-assignments"] });
    }
  }, [runStatus, queryClient]);

  const runTestsMut = useMutation({
    mutationFn: () => runTestsStudent(assignmentId),
    onSuccess: (run) => {
      setActiveRunId(run.id);
      queryClient.setQueryData(["grading-run", assignmentId, run.id], run);
    },
    onError: (e) => showToast((e as Error).message, "error"),
  });

  const labName = detail.data?.lab_deployment_name;
  const labNamespace = detail.data?.lab_namespace;
  const lab = labName
    ? labsState.labs.find(
        (candidate) =>
          candidate.deployment.name === labName && (!labNamespace || candidate.deployment.namespace === labNamespace),
      )
    : undefined;

  /** Opens the lab without a pop-up blocker: the tab is created in the click handler itself. */
  function openLabFallback() {
    if (!labNamespace || !labName) return;
    setOpening(true);
    void openLabViaDetails({ namespace: labNamespace, name: labName }, t).finally(() => setOpening(false));
  }

  if (detail.isLoading) return <LoadingState label={t("common.loading")} />;
  if (detail.error) {
    return (
      <QueryProblem
        error={detail.error}
        title={t("assignments.load_error")}
        onRetry={() => void detail.refetch()}
        retrying={detail.isFetching}
      />
    );
  }
  if (!detail.data) return null;

  const item = detail.data;
  // Prefer the live cluster state; fall back to the server's record when the list is unavailable.
  const labReady = lab ? lab.phase === "ready" : item.lab_ready;
  const labOpenable = lab ? canOpen(lab) && !lab.busy : item.lab_ready;
  const labUrl = lab?.deployment.access_url || null;
  const sub = item.submission;
  const canSubmit = Boolean(text.trim()) || links.some((l) => l.url.trim());

  const run = runQuery.data || item.latest_run || null;
  const runActive = run?.status === "queued" || run?.status === "running" || runTestsMut.isPending;
  const showTests = item.grading_mode !== "none";

  return (
    <>
      <div>
        <Link
          to="/"
          className="muted inline-flex items-center gap-1.5 text-sm no-underline transition-colors hover:text-[var(--text)]"
        >
          <ArrowLeft size={15} /> {t("myassignments.back")}
        </Link>
      </div>
      <PageHeader
        title={item.title}
        subtitle={item.classroom_name || undefined}
      />

      <div className="assignment-detail-grid">
        {/* Colonne consignes */}
        <div className="flex flex-col gap-4">
          <section className="panel">
            <div className="section-head">
              <h2>{t("assignment.statement")}</h2>
            </div>
            {item.instructions ? (
              <Markdown>{item.instructions}</Markdown>
            ) : (
              <p className="muted">{t("assignment.no_instructions")}</p>
            )}
          </section>

          {item.deliverables ? (
            <section className="panel deliverables-panel">
              <div className="section-head">
                <h2>{t("assignment.deliverables")}</h2>
              </div>
              <Markdown>{item.deliverables}</Markdown>
            </section>
          ) : null}

          {/* Tests automatiques (self-check) */}
          {showTests ? (
            <section className="panel tests-panel">
              <div className="section-head">
                <h2 className="inline-flex items-center gap-2">
                  <FlaskConical size={18} /> {t("probe.tab_title")}
                </h2>
                <Button
                  variant="primary"
                  disabled={!labReady || runActive}
                  onClick={() => runTestsMut.mutate()}
                >
                  {runActive ? t("probe.running") : t("probe.run_tests")}
                </Button>
              </div>
              <p className="muted text-sm">{t("probe.run_intro")}</p>
              {!labReady ? (
                <p className="text-sm mt-1" style={{ color: "var(--warning)" }}>
                  {t("probe.lab_required")}
                </p>
              ) : null}
              {run ? (
                <div className="mt-3 mb-3">
                  <RunSummary run={run} />
                </div>
              ) : null}
              <div className="mt-2">
                <GradingResultList run={run} visibleProbes={item.visible_probes} />
              </div>
            </section>
          ) : null}
        </div>

        {/* Colonne action */}
        <aside className="assignment-aside">
          {/* Lab */}
          <section className="panel">
            <div className="section-head">
              <h2>{t("submission.lab")}</h2>
              {lab ? <LabStatusBadge phase={lab.phase} /> : <StatusBadge state={item.lab_status || "none"} />}
            </div>
            <div className="flex flex-col gap-2">
              {labOpenable && labUrl ? (
                <a className="btn primary justify-center" href={labUrl} target="_blank" rel="noopener noreferrer">
                  <ExternalLink size={16} aria-hidden="true" />
                  {t("submission.open_lab")}
                </a>
              ) : lab?.phase === "paused" || lab?.phase === "resuming" ? (
                <Button
                  variant="primary"
                  className="justify-center"
                  disabled={lab.busy}
                  onClick={() => labsState.runAction(lab.deployment, "resume")}
                >
                  {lab.busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <PlayCircle size={16} aria-hidden="true" />}
                  {lab.busy ? t("labs.phase_resuming") : t("assignments.resume_lab")}
                </Button>
              ) : (
                <Button
                  variant="primary"
                  disabled={!labOpenable || opening}
                  onClick={openLabFallback}
                  className="justify-center"
                >
                  {opening ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <ExternalLink size={16} aria-hidden="true" />}
                  {opening ? t("submission.opening") : t("submission.open_lab")}
                </Button>
              )}
              {lab && (lab.phase === "starting" || lab.phase === "creating" || lab.phase === "resuming") ? (
                <span className="muted text-sm">{t("labs.hint_starting")}</span>
              ) : lab?.phase === "paused" ? (
                <span className="muted text-sm">{t("assignments.paused_hint")}</span>
              ) : !labOpenable ? (
                <span className="muted text-sm">{t("submission.lab_not_ready_hint")}</span>
              ) : null}
            </div>
          </section>

          {/* Échéance / état */}
          <section className="panel">
            <div className="detail-meta-row">
              <span className="muted">{t("myassignments.due")}</span>
              <span
                style={
                  item.due_at && !sub && new Date(item.due_at).getTime() < Date.now()
                    ? { color: "var(--danger)", fontWeight: 600 }
                    : undefined
                }
              >
                {item.due_at ? fullDate(item.due_at, locale) : t("myassignments.no_due")}
              </span>
            </div>
            <div className="detail-meta-row">
              <span className="muted">{t("submission.status")}</span>
              {sub ? (
                sub.status === "graded" ? (
                  <Badge tone="green">{t("myassignments.status_graded")}</Badge>
                ) : sub.is_late ? (
                  <Badge tone="amber">{t("myassignments.status_late")}</Badge>
                ) : (
                  <Badge tone="blue">{t("myassignments.status_submitted")}</Badge>
                )
              ) : (
                <Badge>{t("myassignments.status_not_started")}</Badge>
              )}
            </div>
            {sub?.submitted_at ? (
              <div className="detail-meta-row">
                <span className="muted">{t("submission.submitted_at")}</span>
                <span>{fullDate(sub.submitted_at, locale)}</span>
              </div>
            ) : null}
          </section>
        </aside>
      </div>

      {/* Feedback du prof */}
      {sub?.status === "graded" ? (
        <section className="panel feedback-panel">
          <div className="section-head">
            <h2>{t("submission.feedback")}</h2>
            {sub.grade ? <Badge tone="green">{t("submission.grade")}: {sub.grade}</Badge> : null}
          </div>
          {sub.feedback ? (
            <Markdown>{sub.feedback}</Markdown>
          ) : (
            <p className="muted">{t("submission.no_feedback")}</p>
          )}
        </section>
      ) : null}

      {/* Formulaire de rendu */}
      <section className="panel">
        <div className="section-head">
          <h2>{sub ? t("submission.update_title") : t("submission.title")}</h2>
        </div>

        <div className="field full">
          <label>{t("submission.comment")}</label>
          <textarea
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("submission.comment_placeholder")}
          />
        </div>

        <div className="field full">
          <label>{t("submission.links")}</label>
          <div className="flex flex-col gap-2">
            {links.map((link, idx) => (
              <div key={idx} className="submission-link-row">
                <input
                  style={{ flex: "0 0 30%" }}
                  placeholder={t("submission.link_label")}
                  value={link.label}
                  onChange={(e) =>
                    setLinks((prev) => prev.map((l, i) => (i === idx ? { ...l, label: e.target.value } : l)))
                  }
                />
                <input
                  style={{ flex: 1 }}
                  placeholder="https://..."
                  value={link.url}
                  onChange={(e) =>
                    setLinks((prev) => prev.map((l, i) => (i === idx ? { ...l, url: e.target.value } : l)))
                  }
                />
                <Button
                  variant="ghost"
                  type="button"
                  aria-label={t("common.delete")}
                  onClick={() => setLinks((prev) => prev.filter((_, i) => i !== idx))}
                >
                  <Trash2 size={16} />
                </Button>
              </div>
            ))}
            <div>
              <Button type="button" onClick={() => setLinks((prev) => [...prev, { label: "", url: "" }])}>
                <Plus size={16} /> {t("submission.add_link")}
              </Button>
            </div>
          </div>
        </div>

        <div className="actions-row justify-end">
          <Button onClick={() => navigate("/")}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!canSubmit || submitMut.isPending}
            onClick={() => submitMut.mutate()}
          >
            {submitMut.isPending ? t("submission.submitting") : sub ? t("submission.resubmit") : t("submission.submit")}
          </Button>
        </div>
      </section>
    </>
  );
}
