import "../styles/main.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
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
import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AppShell, PageHeader } from "../components/AppShell";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  ModalShell,
  ResourceMeter,
  SearchBox,
  StatusBadge,
  TabContent,
  TabList,
  TabTrigger,
  Tabs,
  ToastContainer,
  showToast,
} from "../components/ui";
import { ClassroomCard } from "../components/teacher/ClassroomCard";
import { ClassroomDialog } from "../components/teacher/ClassroomDialog";
import { AddStudentDialog } from "../components/teacher/AddStudentDialog";
import { AssignmentDialog } from "../components/teacher/AssignmentDialog";
import type { Assignment, Classroom, Enrollment, StudentLabStatus, Template, User } from "../types/api";
import {
  deleteAssignment,
  deployAllAssignments,
  getAssignments,
  getClassroomLabStatus,
  getClassrooms,
  getClassroomStudents,
  getTemplates,
  unenrollStudent,
} from "../lib/api";
import { fullDate, presetLabel, shortDate } from "../lib/format";
import { QueryProvider } from "../lib/query";

function TeacherPage({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("classrooms");
  const [showClassroomDialog, setShowClassroomDialog] = useState(false);
  const [editClassroom, setEditClassroom] = useState<Classroom | null>(null);
  const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(null);
  const [showAddStudent, setShowAddStudent] = useState(false);
  const [showAssignmentDialog, setShowAssignmentDialog] = useState(false);
  const [editAssignment, setEditAssignment] = useState<Assignment | null>(null);
  const [overviewFilter, setOverviewFilter] = useState("all");
  const [deployProgress, setDeployProgress] = useState<{
    total: number;
    ok: number;
    errors: number;
    skipped: number;
    done: boolean;
  } | null>(null);

  const classrooms = useQuery({ queryKey: ["classrooms"], queryFn: getClassrooms });
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
  });

  const deployMutation = useMutation({
    mutationFn: ({ cid, aid }: { cid: number; aid: number }) => deployAllAssignments(cid, aid),
    onSuccess: (data) => {
      setDeployProgress({ total: data.total, ok: data.ok, errors: data.errors, skipped: data.skipped, done: true });
      showToast(`Deploiement termine: ${data.ok} ok, ${data.errors} erreurs`, data.errors > 0 ? "error" : "success");
    },
  });

  const unenrollMutation = useMutation({
    mutationFn: ({ userId }: { userId: number }) => unenrollStudent(selectedClassroomId!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-students", selectedClassroomId] });
      showToast("Etudiant desinscrit", "success");
    },
  });

  const deleteAssignMutation = useMutation({
    mutationFn: ({ aid }: { aid: number }) => deleteAssignment(selectedClassroomId!, aid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments", selectedClassroomId] });
      showToast("Devoir archive", "success");
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
        <ToastContainer />
        <PageHeader
          title={selectedClassroom.name}
          subtitle={selectedClassroom.description || "Gestion de la classe"}
          actions={
            <Button onClick={() => setSelectedClassroomId(null)}>
              <ArrowLeft size={16} /> Retour
            </Button>
          }
        />

        <Tabs value={tab} onChange={setTab}>
          <TabList>
            <TabTrigger value="students"><Users size={16} /> Etudiants ({students.data?.length || 0})</TabTrigger>
            <TabTrigger value="assignments"><BookOpen size={16} /> Devoirs ({assignments.data?.length || 0})</TabTrigger>
            <TabTrigger value="monitor"><Monitor size={16} /> Monitoring</TabTrigger>
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
                setDeployProgress({ total: 0, ok: 0, errors: 0, skipped: 0, done: false });
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
      <ToastContainer />
      <PageHeader
        title="Classes"
        subtitle="Creez et gerez vos classes, etudiants, devoirs et supervisez les labs."
        actions={
          <>
            <Button variant="primary" onClick={() => { setEditClassroom(null); setShowClassroomDialog(true); }}>
              <Plus size={16} /> Nouvelle classe
            </Button>
            <Button onClick={() => queryClient.invalidateQueries({ queryKey: ["classrooms"] })}>
              <RefreshCw size={16} /> Actualiser
            </Button>
          </>
        }
      />

      {classrooms.isLoading ? <LoadingState /> : null}
      {classrooms.error ? <ErrorState>Impossible de charger les classes.</ErrorState> : null}
      {!classrooms.isLoading && !classrooms.error && (classrooms.data || []).length === 0 ? (
        <EmptyState title="Aucune classe">Creez votre premiere classe pour commencer.</EmptyState>
      ) : null}

      <section className="grid-teacher">
        {(classrooms.data || []).map((classroom) => (
          <ClassroomCard
            key={classroom.id}
            classroom={classroom}
            onEdit={(c) => { setEditClassroom(c); setShowClassroomDialog(true); }}
            onSelect={setSelectedClassroomId}
          />
        ))}
      </section>

      <ClassroomDialog
        classroom={editClassroom}
        open={showClassroomDialog}
        onOpenChange={setShowClassroomDialog}
      />
    </>
  );
}

function ClassroomStudentsView({
  students,
  isLoading,
  error,
  onAdd,
  onUnenroll,
}: {
  students: Enrollment[];
  isLoading: boolean;
  error: unknown;
  onAdd: () => void;
  onUnenroll: (userId: number) => void;
}) {
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState>Impossible de charger les etudiants.</ErrorState>;

  return (
    <section className="panel">
      <div className="section-head">
        <h2>Etudiants inscrits</h2>
        <Button variant="primary" onClick={onAdd}><Plus size={16} /> Ajouter</Button>
      </div>
      {students.length === 0 ? (
        <EmptyState title="Aucun etudiant">Ajoutez des etudiants a cette classe.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Nom</th>
                <th>Email</th>
                <th>Inscrit le</th>
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
                      title="Desinscrire"
                      description={`Retirer ${s.username || "cet etudiant"} de la classe ?`}
                      confirmLabel="Desinscrire"
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
  deployProgress: { total: number; ok: number; errors: number; skipped: number; done: boolean } | null;
}) {
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState>Impossible de charger les devoirs.</ErrorState>;

  return (
    <section className="panel">
      <div className="section-head">
        <h2>Devoirs</h2>
        <Button variant="primary" onClick={onCreate}><Plus size={16} /> Nouveau devoir</Button>
      </div>
      {deployProgress ? (
        <div className="card" style={{ padding: 16, marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 16, justifyContent: "space-between", flexWrap: "wrap" }}>
            <span><strong>{deployProgress.done ? "Termine" : "En cours"}</strong></span>
            <span>{deployProgress.ok} ok / {deployProgress.errors} erreurs / {deployProgress.skipped} ignores</span>
          </div>
          {!deployProgress.done && <ResourceMeter label="Progression" used={deployProgress.ok + deployProgress.errors + deployProgress.skipped} max={deployProgress.total} />}
        </div>
      ) : null}
      {assignments.length === 0 ? (
        <EmptyState title="Aucun devoir">Creez un devoir pour le distribuer aux etudiants.</EmptyState>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {assignments.map((a) => (
            <article className="card" key={a.id} style={{ padding: 16 }}>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "space-between", alignItems: "start" }}>
                <div>
                  <strong>{a.title}</strong>
                  <div className="lab-meta" style={{ marginTop: 6 }}>
                    {a.template_key ? <span className="badge">{a.template_key}</span> : null}
                    <span className="badge">CPU {presetLabel(a.cpu_preset)}</span>
                    <span className="badge">RAM {presetLabel(a.ram_preset)}</span>
                    {a.due_at ? <span className="badge">Echeance {fullDate(a.due_at)}</span> : null}
                  </div>
                  {a.instructions ? (
                    <p className="muted" style={{ marginTop: 8, fontSize: "0.85rem" }}>
                      {a.instructions.slice(0, 200)}{a.instructions.length > 200 ? "..." : ""}
                    </p>
                  ) : null}
                </div>
                <div className="actions-row">
                  <Button variant="primary" onClick={() => onDeploy(a.id)} disabled={isDeploying}>
                    <Rocket size={16} /> Deployer
                  </Button>
                  <Button onClick={() => onEdit(a)}>Modifier</Button>
                  <ConfirmDialog
                    destructive
                    title="Archiver le devoir"
                    description={`Archiver "${a.title}" ?`}
                    confirmLabel="Archiver"
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
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState>Impossible de charger le monitoring.</ErrorState>;

  const filters: Array<{ value: string; label: string }> = [
    { value: "all", label: "Tous" },
    { value: "active", label: "Actifs" },
    { value: "paused", label: "En pause" },
    { value: "none", label: "Sans lab" },
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
        <EmptyState title="Aucun etudiant">Aucun etudiant ne correspond au filtre.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Etudiant</th>
                <th>Lab</th>
                <th>Statut</th>
                <th>Expire</th>
                <th>Inscrit le</th>
              </tr>
            </thead>
            <tbody>
              {students.map((s) => (
                <tr key={s.user_id}>
                  <td>{s.username || `User #${s.user_id}`}</td>
                  <td>{s.lab_name || "Aucun"}</td>
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

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <AppShell page="teacher" requireRole={["teacher", "admin"]}>
      {(user) => <TeacherPage user={user} />}
    </AppShell>
  </QueryProvider>,
);
