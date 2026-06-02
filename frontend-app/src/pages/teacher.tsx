import "../styles/main.css";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  GraduationCap,
  LayoutGrid,
  Monitor,
  Plus,
  RefreshCw,
  Rocket,
  Trash2,
  Users,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { PageHeader } from "../components/AppShell";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  ResourceMeter,
  StatusBadge,
  TabContent,
  TabList,
  TabTrigger,
  Tabs,
  showToast,
} from "../components/ui";
import { ClassroomCard } from "../components/teacher/ClassroomCard";
import { ClassroomDialog } from "../components/teacher/ClassroomDialog";
import { AddStudentDialog } from "../components/teacher/AddStudentDialog";
import { AssignmentDialog } from "../components/teacher/AssignmentDialog";
import type { Assignment, BulkSpawnReport, Classroom, StudentLabStatus, TeacherDashboard, User } from "../types/api";
import {
  deleteAssignment,
  deployAllAssignments,
  getAssignments,
  getClassroomLabStatus,
  getClassrooms,
  getClassroomStudents,
  getTeacherDashboard,
  getTemplates,
  unenrollStudent,
} from "../lib/api";
import { fullDate, presetLabel, shortDate } from "../lib/format";
import { useI18n } from "../lib/i18n";

export default function TeacherPage() {
  const user = useOutletContext<User>();
  const queryClient = useQueryClient();
  const { locale, t } = useI18n();

  const initialTab = window.location.hash?.replace("#", "") || new URLSearchParams(window.location.search).get("tab") || "overview";
  const [tab, setTab] = useState(initialTab);
  const [showClassroomDialog, setShowClassroomDialog] = useState(false);
  const [editClassroom, setEditClassroom] = useState<Classroom | null>(null);
  const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(null);
  const [showAddStudent, setShowAddStudent] = useState(false);
  const [showAssignmentDialog, setShowAssignmentDialog] = useState(false);
  const [editAssignment, setEditAssignment] = useState<Assignment | null>(null);
  const [overviewFilter, setOverviewFilter] = useState("all");
  const [deployProgress, setDeployProgress] = useState<(BulkSpawnReport & { done: boolean }) | null>(null);

  const classrooms = useQuery({ queryKey: ["classrooms"], queryFn: getClassrooms });
  const teacherDashboard = useQuery({ queryKey: ["teacher-dashboard"], queryFn: getTeacherDashboard, refetchInterval: 30_000 });
  const templates = useQuery({ queryKey: ["templates"], queryFn: getTemplates });
  const selectedClassroom = classrooms.data?.find((c) => c.id === selectedClassroomId) || null;

  const students = useQuery({
    queryKey: ["classroom-students", selectedClassroomId],
    queryFn: () => getClassroomStudents(selectedClassroomId!),
    enabled: selectedClassroomId !== null,
  });

  const assignments = useQuery({
    queryKey: ["assignments", selectedClassroomId],
    queryFn: () => getAssignments(selectedClassroomId!),
    enabled: selectedClassroomId !== null,
  });

  const labStatus = useQuery({
    queryKey: ["lab-status", selectedClassroomId],
    queryFn: () => getClassroomLabStatus(selectedClassroomId!),
    enabled: tab === "monitor",
    refetchInterval: 30_000,
  });

  const deployMutation = useMutation({
    mutationFn: ({ cid, aid }: { cid: number; aid: number }) => deployAllAssignments(cid, aid),
    onSuccess: (data) => {
      setDeployProgress({ ...data, done: true });
      queryClient.invalidateQueries({ queryKey: ["lab-status", selectedClassroomId] });
      queryClient.invalidateQueries({ queryKey: ["deployments"] });
      queryClient.invalidateQueries({ queryKey: ["quotas"] });
      showToast(
        locale === "fr" 
          ? `Déploiement terminé: ${data.ok} ok, ${data.errors} erreurs` 
          : `Deployment finished: ${data.ok} ok, ${data.errors} errors`, 
        data.errors > 0 ? "error" : "success"
      );
    },
  });

  useEffect(() => {
    const allowed = selectedClassroom ? ["students", "assignments", "monitor"] : ["overview", "classrooms", "monitor"];
    if (allowed.includes(tab)) window.history.replaceState(null, "", `${window.location.pathname}#${tab}`);
  }, [selectedClassroom, tab]);

  const unenrollMutation = useMutation({
    mutationFn: ({ userId }: { userId: number }) => unenrollStudent(selectedClassroomId!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-students", selectedClassroomId] });
      queryClient.invalidateQueries({ queryKey: ["lab-status", selectedClassroomId] });
      queryClient.invalidateQueries({ queryKey: ["classrooms"] });
      queryClient.invalidateQueries({ queryKey: ["teacher-dashboard"] });
      showToast(locale === "fr" ? "Étudiant désinscrit" : "Student unenrolled", "success");
    },
  });

  const deleteAssignMutation = useMutation({
    mutationFn: ({ aid }: { aid: number }) => deleteAssignment(selectedClassroomId!, aid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments", selectedClassroomId] });
      queryClient.invalidateQueries({ queryKey: ["classrooms"] });
      queryClient.invalidateQueries({ queryKey: ["teacher-dashboard"] });
      showToast(locale === "fr" ? "Devoir archivé" : "Assignment archived", "success");
    },
  });

  const filteredLabStatus = useMemo(() => {
    const items = labStatus.data || [];
    if (overviewFilter === "all") return items;
    if (overviewFilter === "active") return items.filter((s) => s.lab_status === "active");
    if (overviewFilter === "paused") return items.filter((s) => s.lab_status === "paused");
    if (overviewFilter === "none") return items.filter((s) => !s.lab_status || s.lab_status === "none");
    return items;
  }, [labStatus.data, overviewFilter]);

  if (selectedClassroom) {
    return (
      <>
        <PageHeader
          title={selectedClassroom.name}
          subtitle={selectedClassroom.description || (locale === "fr" ? "Gestion de la classe" : "Class management")}
          actions={
            <Button onClick={() => setSelectedClassroomId(null)}>
              <ArrowLeft size={16} /> {locale === "fr" ? "Retour" : "Back"}
            </Button>
          }
        />

        <Tabs value={tab} onChange={setTab}>
          <TabList>
            <TabTrigger value="students"><Users size={16} /> {t("students.title")} ({students.data?.length || 0})</TabTrigger>
            <TabTrigger value="assignments"><BookOpen size={16} /> {t("assignment.title")} ({assignments.data?.length || 0})</TabTrigger>
            <TabTrigger value="monitor"><Monitor size={16} /> {locale === "fr" ? "Supervision" : "Monitoring"}</TabTrigger>
          </TabList>

          <TabContent value="students">
            <ClassroomStudentsView
              students={students.data || []}
              isLoading={students.isLoading}
              error={students.error}
              onAdd={() => setShowAddStudent(true)}
              onUnenroll={(userId) => unenrollMutation.mutate({ userId })}
            />
          </TabContent>

          <TabContent value="assignments">
            <AssignmentsView
              assignments={assignments.data || []}
              isLoading={assignments.isLoading}
              error={assignments.error}
              onCreate={() => {
                setEditAssignment(null);
                setShowAssignmentDialog(true);
              }}
              onEdit={(a) => {
                setEditAssignment(a);
                setShowAssignmentDialog(true);
              }}
              onDelete={(aid) => deleteAssignMutation.mutate({ aid })}
              onDeploy={(aid) => {
                setDeployProgress({ assignment_id: aid, classroom_id: selectedClassroom.id, total: 0, ok: 0, errors: 0, skipped: 0, results: [], done: false });
                deployMutation.mutate({ cid: selectedClassroom.id, aid });
              }}
              isDeploying={deployMutation.isPending}
              deployProgress={deployProgress}
            />
          </TabContent>

          <TabContent value="monitor">
            <LabMonitorView
              students={filteredLabStatus}
              isLoading={labStatus.isLoading}
              error={labStatus.error}
              filter={overviewFilter}
              onFilterChange={setOverviewFilter}
              onRefresh={() => queryClient.invalidateQueries({ queryKey: ["lab-status", selectedClassroomId] })}
            />
          </TabContent>
        </Tabs>

        <AddStudentDialog
          classroomId={selectedClassroom.id}
          open={showAddStudent}
          onOpenChange={setShowAddStudent}
        />
        <AssignmentDialog
          key={editAssignment?.id ?? "new"}
          classroomId={selectedClassroom.id}
          assignment={editAssignment}
          templates={templates.data || []}
          open={showAssignmentDialog}
          onOpenChange={setShowAssignmentDialog}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={t("classroom.title")}
        subtitle={locale === "fr" ? "Créez et gérez vos classes, étudiants, devoirs et supervisez les labs." : "Create and manage your classes, students, assignments, and monitor labs."}
        actions={
          <>
            <Button variant="primary" onClick={() => { setEditClassroom(null); setShowClassroomDialog(true); }}>
              <Plus size={16} /> {t("classroom.new")}
            </Button>
            <Button onClick={() => queryClient.invalidateQueries({ queryKey: ["classrooms"] })}>
              <RefreshCw size={16} /> {t("overview.refresh")}
            </Button>
          </>
        }
      />

      <Tabs value={tab} onChange={setTab}>
        <TabList>
          <TabTrigger value="overview"><LayoutGrid size={16} /> {locale === "fr" ? "Vue globale" : "Global view"}</TabTrigger>
          <TabTrigger value="classrooms"><GraduationCap size={16} /> {t("classroom.title")}</TabTrigger>
          <TabTrigger value="monitor"><Monitor size={16} /> {locale === "fr" ? "Supervision" : "Monitoring"}</TabTrigger>
        </TabList>

        <TabContent value="overview">
          <TeacherOverview dashboard={teacherDashboard.data} isLoading={teacherDashboard.isLoading} error={teacherDashboard.error} />
        </TabContent>

        <TabContent value="classrooms">
          {classrooms.isLoading ? <LoadingState /> : null}
          {classrooms.error ? <ErrorState>{locale === "fr" ? "Impossible de charger les classes." : "Unable to load classes."}</ErrorState> : null}
          {!classrooms.isLoading && !classrooms.error && (classrooms.data || []).length === 0 ? (
            <EmptyState title={t("classroom.empty")}>{t("classroom.empty_hint")}</EmptyState>
          ) : null}

          <section className="grid-teacher">
            {(classrooms.data || []).map((classroom) => (
              <ClassroomCard
                key={classroom.id}
                classroom={classroom}
                onEdit={(c) => { setEditClassroom(c); setShowClassroomDialog(true); }}
                onSelect={(id) => {
                  setSelectedClassroomId(id);
                  setTab("students");
                }}
              />
            ))}
          </section>
        </TabContent>

        <TabContent value="monitor">
          <GlobalMonitor classrooms={classrooms.data || []} />
        </TabContent>
      </Tabs>

      <ClassroomDialog
        classroom={editClassroom}
        open={showClassroomDialog}
        onOpenChange={setShowClassroomDialog}
      />
    </>
  );
}

function TeacherOverview({
  dashboard,
  isLoading,
  error,
}: {
  dashboard?: TeacherDashboard;
  isLoading: boolean;
  error: unknown;
}) {
  const { locale, t } = useI18n();
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState>{locale === "fr" ? "Impossible de charger la vue globale." : "Unable to load global view."}</ErrorState>;

  const classrooms = dashboard?.classrooms || [];
  const totalStudents = classrooms.reduce((sum, classroom) => sum + classroom.student_count, 0);
  const totalAssignments = classrooms.reduce((sum, classroom) => sum + classroom.active_assignment_count, 0);

  return (
    <div className="grid gap-4">
      <section className="metric-grid">
        <div className="card metric-card">
          <div className="metric-top"><span>{t("classroom.title")}</span><GraduationCap size={18} /></div>
          <strong className="metric-value">{dashboard?.classroom_count || 0}</strong>
        </div>
        <div className="card metric-card">
          <div className="metric-top"><span>{t("students.title")}</span><Users size={18} /></div>
          <strong className="metric-value">{totalStudents}</strong>
        </div>
        <div className="card metric-card">
          <div className="metric-top"><span>{locale === "fr" ? "Devoirs actifs" : "Active assignments"}</span><BookOpen size={18} /></div>
          <strong className="metric-value">{totalAssignments}</strong>
        </div>
      </section>

      <section className="panel">
        <div className="section-head">
          <h2>{locale === "fr" ? "Classes récentes" : "Recent classes"}</h2>
        </div>
        {classrooms.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>Classe</th><th>{t("students.title")}</th><th>{locale === "fr" ? "Devoirs actifs" : "Active assignments"}</th><th>{locale === "fr" ? "Créé le" : "Created at"}</th></tr>
              </thead>
              <tbody>
                {classrooms.map((classroom) => (
                  <tr key={classroom.id}>
                    <td>{classroom.name}</td>
                    <td>{classroom.student_count}</td>
                    <td>{classroom.active_assignment_count}</td>
                    <td>{shortDate(classroom.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title={t("classroom.empty")}>{locale === "fr" ? "Créez une classe pour afficher la synthèse." : "Create a class to view summary."}</EmptyState>
        )}
      </section>
    </div>
  );
}

function GlobalMonitor({ classrooms }: { classrooms: Classroom[] }) {
  const { locale } = useI18n();
  const [classroomFilter, setClassroomFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const activeClassrooms = classrooms.filter((classroom) => !classroom.archived);
  const statusQueries = useQueries({
    queries: activeClassrooms.map((classroom) => ({
      queryKey: ["lab-status", classroom.id],
      queryFn: () => getClassroomLabStatus(classroom.id),
      refetchInterval: 30_000,
    })),
  });
  const rows = activeClassrooms.flatMap((classroom, index) => {
    const statuses = statusQueries[index]?.data || [];
    return statuses.map((status) => ({ ...status, classroom_id: classroom.id, classroom_name: classroom.name }));
  });
  const filtered = rows.filter((row) => {
    const status = row.lab_status || "none";
    return (!classroomFilter || String(row.classroom_id) === classroomFilter) && (statusFilter === "all" || status === statusFilter);
  });
  const summary = {
    active: rows.filter((row) => row.lab_status === "active").length,
    paused: rows.filter((row) => row.lab_status === "paused").length,
    none: rows.filter((row) => !row.lab_status || row.lab_status === "none").length,
  };

  return (
    <section className="panel">
      <div className="section-head">
        <h2>{locale === "fr" ? "Monitoring multi-classes" : "Multi-class monitoring"}</h2>
        <span className="badge blue">Auto-refresh 30s</span>
      </div>
      <section className="metric-grid mb-4">
        <div className="card metric-card"><div className="metric-top"><span>{locale === "fr" ? "Actifs" : "Active"}</span><CheckCircle2 size={18} /></div><strong className="metric-value">{summary.active}</strong></div>
        <div className="card metric-card"><div className="metric-top"><span>{locale === "fr" ? "En pause" : "Paused"}</span><Archive size={18} /></div><strong className="metric-value">{summary.paused}</strong></div>
        <div className="card metric-card"><div className="metric-top"><span>{locale === "fr" ? "Sans lab" : "Without lab"}</span><XCircle size={18} /></div><strong className="metric-value">{summary.none}</strong></div>
      </section>
      <div className="actions-row mb-3">
        <select className="control" value={classroomFilter} onChange={(e) => setClassroomFilter(e.target.value)}>
          <option value="">{locale === "fr" ? "Toutes classes" : "All classes"}</option>
          {activeClassrooms.map((classroom) => <option value={classroom.id} key={classroom.id}>{classroom.name}</option>)}
        </select>
        <select className="control" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">{locale === "fr" ? "Tous statuts" : "All statuses"}</option>
          <option value="active">{locale === "fr" ? "Actifs" : "Active"}</option>
          <option value="paused">{locale === "fr" ? "En pause" : "Paused"}</option>
          <option value="none">{locale === "fr" ? "Sans lab" : "Without lab"}</option>
        </select>
      </div>
      {statusQueries.some((query) => query.isLoading) ? <LoadingState /> : null}
      {filtered.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Classe</th><th>{locale === "fr" ? "Étudiant" : "Student"}</th><th>Lab</th><th>{locale === "fr" ? "Statut" : "Status"}</th><th>{locale === "fr" ? "Expire" : "Expires"}</th></tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={`${row.classroom_id}-${row.user_id}`}>
                  <td>{row.classroom_name}</td>
                  <td>{row.username}</td>
                  <td>{row.lab_name || "Aucun"}</td>
                  <td><StatusBadge state={row.lab_status || "none"} /></td>
                  <td>{row.lab_expires_at ? shortDate(row.lab_expires_at) : "N/A"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title={locale === "fr" ? "Aucune donnée" : "No data"}>{locale === "fr" ? "Aucun étudiant ne correspond aux filtres." : "No student matches filters."}</EmptyState>
      )}
    </section>
  );
}

function ClassroomStudentsView({
  students,
  isLoading,
  error,
  onAdd,
  onUnenroll,
}: {
  students: StudentLabStatus[];
  isLoading: boolean;
  error: unknown;
  onAdd: () => void;
  onUnenroll: (userId: number) => void;
}) {
  const { locale, t } = useI18n();
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState>{locale === "fr" ? "Impossible de charger les étudiants." : "Unable to load students."}</ErrorState>;

  return (
    <section className="panel">
      <div className="section-head">
        <h2>{locale === "fr" ? "Étudiants inscrits" : "Enrolled students"}</h2>
        <Button variant="primary" onClick={onAdd}><Plus size={16} /> {t("students.add")}</Button>
      </div>
      {students.length === 0 ? (
        <EmptyState title={t("students.empty")}>{locale === "fr" ? "Ajoutez des étudiants à cette classe." : "Add students to this class."}</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("students.username")}</th>
                <th>{t("students.email")}</th>
                <th>{locale === "fr" ? "Inscrit le" : "Enrolled at"}</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {students.map((s) => (
                <tr key={s.user_id}>
                  <td>{s.username || `User #${s.user_id}`}</td>
                  <td>{s.email || "N/A"}</td>
                  <td>{shortDate(s.enrolled_at)}</td>
                  <td>
                    <ConfirmDialog
                      destructive
                      title={t("students.unenroll")}
                      description={locale === "fr" ? `Retirer ${s.username || "cet étudiant"} de la classe ?` : `Remove ${s.username || "this student"} from the class?`}
                      confirmLabel={t("students.unenroll")}
                      trigger={<Button variant="danger"><Trash2 size={14} /></Button>}
                      onConfirm={() => onUnenroll(s.user_id)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AssignmentsView({
  assignments,
  isLoading,
  error,
  onCreate,
  onEdit,
  onDelete,
  onDeploy,
  isDeploying,
  deployProgress,
}: {
  assignments: Assignment[];
  isLoading: boolean;
  error: unknown;
  onCreate: () => void;
  onEdit: (a: Assignment) => void;
  onDelete: (aid: number) => void;
  onDeploy: (aid: number) => void;
  isDeploying: boolean;
  deployProgress: (BulkSpawnReport & { done: boolean }) | null;
}) {
  const { locale, t } = useI18n();
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState>{locale === "fr" ? "Impossible de charger les devoirs." : "Unable to load assignments."}</ErrorState>;

  return (
    <section className="panel">
      <div className="section-head">
        <h2>{t("assignment.title")}</h2>
        <Button variant="primary" onClick={onCreate}><Plus size={16} /> {t("assignment.new")}</Button>
      </div>
      {deployProgress ? (
        <div className="card mb-4 p-4">
          <div className="flex flex-wrap justify-between gap-4">
            <span><strong>{deployProgress.done ? (locale === "fr" ? "Terminé" : "Completed") : (locale === "fr" ? "En cours" : "In progress")}</strong></span>
            <span>{deployProgress.ok} ok / {deployProgress.errors} {locale === "fr" ? "erreurs" : "errors"} / {deployProgress.skipped} {locale === "fr" ? "ignorés" : "skipped"}</span>
          </div>
          {!deployProgress.done && <ResourceMeter label={locale === "fr" ? "Progression" : "Progress"} used={deployProgress.ok + deployProgress.errors + deployProgress.skipped} max={deployProgress.total} />}
          {deployProgress.done && deployProgress.results.length ? (
            <div className="table-wrap mt-3">
              <table className="data-table">
                <thead>
                  <tr><th>{locale === "fr" ? "Étudiant" : "Student"}</th><th>{locale === "fr" ? "Statut" : "Status"}</th><th>Lab</th><th>{locale === "fr" ? "Erreur" : "Error"}</th></tr>
                </thead>
                <tbody>
                  {deployProgress.results.map((result) => (
                    <tr key={result.user_id}>
                      <td>{result.username}</td>
                      <td><StatusBadge state={result.status === "ok" ? "active" : result.status === "skipped" ? "paused" : "error"} /></td>
                      <td>{result.deployment_name || "N/A"}</td>
                      <td>{result.error || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
      {assignments.length === 0 ? (
        <EmptyState title={t("assignment.empty")}>{locale === "fr" ? "Créez un devoir pour le distribuer aux étudiants." : "Create an assignment to distribute to students."}</EmptyState>
      ) : (
        <div className="grid gap-3">
          {assignments.map((a) => (
            <article className="card p-4" key={a.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <strong>{a.title}</strong>
                  <div className="lab-meta mt-1.5">
                    {a.template_key ? <span className="badge">{a.template_key}</span> : null}
                    <span className="badge">CPU {presetLabel(a.cpu_preset)}</span>
                    <span className="badge">RAM {presetLabel(a.ram_preset)}</span>
                    {a.due_at ? <span className="badge">{t("assignment.due")} {fullDate(a.due_at)}</span> : null}
                  </div>
                  {a.instructions ? (
                    <p className="muted mt-2 text-[0.85rem]">
                      {a.instructions.slice(0, 200)}{a.instructions.length > 200 ? "..." : ""}
                    </p>
                  ) : null}
                </div>
                <div className="actions-row">
                  <Button variant="primary" onClick={() => onDeploy(a.id)} disabled={isDeploying}>
                    <Rocket size={16} /> {t("assignment.distribute")}
                  </Button>
                  <Link
                    to={`/teacher/classrooms/${a.classroom_id}/assignments/${a.id}/submissions`}
                    className="btn inline-flex items-center gap-1 no-underline"
                  >
                    <ClipboardList size={16} /> {t("assignment.view_submissions")}
                  </Link>
                  <Button onClick={() => onEdit(a)}>{locale === "fr" ? "Modifier" : "Modify"}</Button>
                  <ConfirmDialog
                    destructive
                    title={t("assignment.archive")}
                    description={locale === "fr" ? `Archiver "${a.title}" ?` : `Archive "${a.title}"?`}
                    confirmLabel={t("assignment.archive")}
                    trigger={<Button variant="danger"><Archive size={14} /></Button>}
                    onConfirm={() => onDelete(a.id)}
                  />
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function LabMonitorView({
  students,
  isLoading,
  error,
  filter,
  onFilterChange,
  onRefresh,
}: {
  students: StudentLabStatus[];
  isLoading: boolean;
  error: unknown;
  filter: string;
  onFilterChange: (f: string) => void;
  onRefresh: () => void;
}) {
  const { locale } = useI18n();
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState>{locale === "fr" ? "Impossible de charger le monitoring." : "Unable to load monitoring."}</ErrorState>;

  const filters: Array<{ value: string; label: string }> = [
    { value: "all", label: locale === "fr" ? "Tous" : "All" },
    { value: "active", label: locale === "fr" ? "Actifs" : "Active" },
    { value: "paused", label: locale === "fr" ? "En pause" : "Paused" },
    { value: "none", label: locale === "fr" ? "Sans lab" : "Without lab" },
  ];

  return (
    <section className="panel">
      <div className="section-head">
        <div className="actions-row">
          {filters.map((f) => (
            <Button
              key={f.value}
              variant={filter === f.value ? "primary" : "default"}
              onClick={() => onFilterChange(f.value)}
            >
              {f.label}
              {filter === f.value ? ` (${students.length})` : ""}
            </Button>
          ))}
        </div>
        <Button onClick={onRefresh}><RefreshCw size={16} /></Button>
      </div>
      {students.length === 0 ? (
        <EmptyState title={locale === "fr" ? "Aucun étudiant" : "No student"}>{locale === "fr" ? "Aucun étudiant ne correspond au filtre." : "No student matches the filter."}</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{locale === "fr" ? "Étudiant" : "Student"}</th>
                <th>Lab</th>
                <th>{locale === "fr" ? "Statut" : "Status"}</th>
                <th>{locale === "fr" ? "Expire" : "Expires"}</th>
                <th>{locale === "fr" ? "Inscrit le" : "Enrolled at"}</th>
              </tr>
            </thead>
            <tbody>
              {students.map((s) => (
                <tr key={s.user_id}>
                  <td>{s.username || `User #${s.user_id}`}</td>
                  <td>{s.lab_name || (locale === "fr" ? "Aucun" : "None")}</td>
                  <td><StatusBadge state={s.lab_status || "none"} /></td>
                  <td>{s.lab_expires_at ? shortDate(s.lab_expires_at) : "N/A"}</td>
                  <td>{shortDate(s.enrolled_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
